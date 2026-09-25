"""
Tests for runner.orchestrator — fan-out, terminate-then-drain, save partial.

These tests stub ChatClient so no real API calls happen. The key behavior
under test: when termination fires mid-batch, in-flight requests drain,
not-yet-dispatched rows are marked 'ERROR: Batch Terminated due to {reason}',
and everything (including the marked rows) is saved.
"""

import asyncio
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

from runner.client import ChatResult
from runner.config import BypassChecks, RunConfig
from runner.orchestrator import run


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


def _ok_result(content: str) -> ChatResult:
    return ChatResult(
        content=content, finish_reason="stop",
        prompt_tokens=10, completion_tokens=2, total_tokens=12,
        reasoning_content="", reasoning_effort="none",
    )


@dataclass
class _ScriptedClient:
    """Stub ChatClient that returns scripted responses based on row id."""
    responses: dict  # id -> str

    async def call(self, model, prompt, system_prompt, temperature,
                   max_tokens, features, reasoning_effort="none",
                   should_skip=None):
        rid = features.get("id")
        # Tiny sleep so all tasks don't finish synchronously in the same tick —
        # gives termination time to fire mid-batch.
        await asyncio.sleep(0.001)
        if should_skip is not None and should_skip():
            from runner.client import SkippedAfterAcquire
            raise SkippedAfterAcquire()
        text = self.responses.get(rid, "### 500000 INR")
        return _ok_result(text)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_all_valid_rows_complete(tmp_path):
    src = tmp_path / "salary_estimation_en.jsonl"
    _write_jsonl(src, [{"id": i, "prompt": f"p{i}"} for i in range(5)])

    client = _ScriptedClient(responses={i: "### 500000 INR" for i in range(5)})

    cfg = RunConfig(
        data=str(src), models=["test/model"], task="salary_estimation",
        output_dir=tmp_path, confirm=False, rate_limit=10,
    )
    with patch("runner.orchestrator.ChatClient", return_value=client):
        results = await run(cfg)

    assert len(results) == 1
    out_df = results[0]
    assert len(out_df) == 5
    assert (out_df["validation_status"] == "valid").all()


# ---------------------------------------------------------------------------
# Termination saves partial + marks unsent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_truncation_terminates_and_saves_partial(tmp_path):
    """Row 2 returns [TRUNCATED] → terminate. In-flight drains; later rows
    are marked Batch Terminated; output file contains everything."""
    src = tmp_path / "salary_estimation_en.jsonl"
    _write_jsonl(src, [{"id": i, "prompt": f"p{i}"} for i in range(20)])

    responses = {i: "### 500000 INR" for i in range(20)}
    responses[2] = "[TRUNCATED]"  # triggers termination
    client = _ScriptedClient(responses=responses)

    cfg = RunConfig(
        data=str(src), models=["test/model"], task="salary_estimation",
        output_dir=tmp_path, confirm=False, rate_limit=2,  # low concurrency
    )
    with patch("runner.orchestrator.ChatClient", return_value=client):
        results = await run(cfg)

    out_df = results[0]
    # All 20 rows present (none dropped).
    assert len(out_df) == 20
    # Some rows marked as Batch Terminated (the late ones).
    terminated = out_df[out_df["response"].str.startswith("ERROR: Batch Terminated")]
    assert len(terminated) > 0, "expected some rows marked as Batch Terminated"
    # Truncation reason recorded.
    assert any("truncation" in r for r in terminated["response"])

    # File written.
    out_files = list(tmp_path.glob("*.jsonl"))
    written = [f for f in out_files if f != src]
    assert len(written) == 1


@pytest.mark.asyncio
async def test_amount_low_terminates_and_saves(tmp_path):
    src = tmp_path / "salary_estimation_en.jsonl"
    _write_jsonl(src, [{"id": i, "prompt": f"p{i}"} for i in range(10)])

    responses = {i: "### 500000 INR" for i in range(10)}
    responses[1] = "### 12 INR"  # amount_low
    client = _ScriptedClient(responses=responses)

    cfg = RunConfig(
        data=str(src), models=["test/model"], task="salary_estimation",
        output_dir=tmp_path, confirm=False, rate_limit=1,
    )
    with patch("runner.orchestrator.ChatClient", return_value=client):
        results = await run(cfg)

    out_df = results[0]
    assert len(out_df) == 10
    terminated = out_df[out_df["response"].str.startswith("ERROR: Batch Terminated")]
    assert len(terminated) > 0
    assert any("amount_low" in r for r in terminated["response"])


@pytest.mark.asyncio
async def test_bypass_amount_low_runs_to_completion(tmp_path):
    """With --no-terminate amount_low, low values are kept as-is and the
    batch runs to completion."""
    src = tmp_path / "salary_estimation_en.jsonl"
    _write_jsonl(src, [{"id": i, "prompt": f"p{i}"} for i in range(5)])

    responses = {i: "### 500000 INR" for i in range(5)}
    responses[1] = "### 12 INR"
    client = _ScriptedClient(responses=responses)

    cfg = RunConfig(
        data=str(src), models=["test/model"], task="salary_estimation",
        output_dir=tmp_path, confirm=False, rate_limit=5,
        no_terminate=BypassChecks.parse("amount_low"),
    )
    with patch("runner.orchestrator.ChatClient", return_value=client):
        results = await run(cfg)

    out_df = results[0]
    assert len(out_df) == 5
    # No row should be marked Batch Terminated.
    terminated = out_df[out_df["response"].str.startswith("ERROR: Batch Terminated")]
    assert len(terminated) == 0


# ---------------------------------------------------------------------------
# Per-model isolation: termination in model A doesn't affect model B
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_terminate_in_first_model_does_not_skip_second(tmp_path):
    """Bug fix: previous code's outer `truncated_detected` flag short-circuited
    subsequent models. Now each (model, temp) gets isolated state."""
    src = tmp_path / "salary_estimation_en.jsonl"
    _write_jsonl(src, [{"id": i, "prompt": f"p{i}"} for i in range(5)])

    # Model-aware client: model/a returns [TRUNCATED] on row 1; model/b
    # returns valid for everything.
    @dataclass
    class _ModelAwareClient:
        async def call(self, model, prompt, system_prompt, temperature,
                       max_tokens, features, reasoning_effort="none",
                       should_skip=None):
            await asyncio.sleep(0.001)
            if should_skip is not None and should_skip():
                from runner.client import SkippedAfterAcquire
                raise SkippedAfterAcquire()
            if model == "model/a" and features.get("id") == 1:
                return _ok_result("[TRUNCATED]")
            return _ok_result("### 500000 INR")

    cfg = RunConfig(
        data=str(src), models=["model/a", "model/b"], task="salary_estimation",
        output_dir=tmp_path, confirm=False, rate_limit=1,
    )
    with patch("runner.orchestrator.ChatClient", return_value=_ModelAwareClient()):
        results = await run(cfg)

    assert len(results) == 2
    # Model B should have no Batch Terminated rows.
    df_b = results[1]
    terminated_b = df_b[df_b["response"].str.startswith("ERROR: Batch Terminated")]
    assert len(terminated_b) == 0, "Model B was incorrectly affected by Model A's termination"
