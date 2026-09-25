"""Tests for runner.retry — in-place ERROR row retry."""

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

from runner.client import ChatResult
from runner.retry import retry_file

_PROMPTS = {
    "salary_estimation":            "salary in INR",
    "salary_increment_estimation":  "hike in %",
    "service_pricing_vendor":       "freelance in INR (vendor)",
    "service_pricing_client":       "freelance in INR (client)",
    "counter_offer_recommendation": "counter offer in INR",
}


def _ok(content: str) -> ChatResult:
    return ChatResult(
        content=content, finish_reason="stop",
        prompt_tokens=10, completion_tokens=2, total_tokens=12,
        reasoning_content="", reasoning_effort="none",
    )


@dataclass
class _StubClient:
    responses: dict  # id -> str

    async def call(self, model, prompt, system_prompt, temperature,
                   max_tokens, features, reasoning_effort="none",
                   should_skip=None):
        return _ok(self.responses.get(features.get("id"), "### 500000 INR"))


def _row(rid, response, *, model="m", temperature=0.0, task="salary_estimation"):
    return {
        "id": rid, "prompt": f"p{rid}", "task": task,
        "model": model, "temperature": temperature,
        "response": response,
    }


def _write_output_file(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


@pytest.mark.asyncio
async def test_retry_replaces_error_rows_only(tmp_path):
    src = tmp_path / "out.jsonl"
    _write_output_file(src, [
        _row(1, "### 500000 INR"),
        _row(2, "ERROR: timeout"),
        _row(3, "### 600000 INR"),
        _row(4, "ERROR: rate limited"),
    ])

    client = _StubClient(responses={2: "### 700000 INR", 4: "### 800000 INR"})
    with patch("runner.retry.ChatClient", return_value=client):
        await retry_file(src, task_to_system_prompt=_PROMPTS, confirm_prompt=False)

    out = tmp_path / "out_retried.jsonl"
    assert out.exists()
    written = pd.read_json(out, lines=True)
    assert len(written) == 4
    assert written.loc[written["id"] == 1, "response"].iloc[0] == "### 500000 INR"
    assert written.loc[written["id"] == 3, "response"].iloc[0] == "### 600000 INR"
    assert written.loc[written["id"] == 2, "response"].iloc[0] == "### 700000 INR"
    assert written.loc[written["id"] == 4, "response"].iloc[0] == "### 800000 INR"


@pytest.mark.asyncio
async def test_retry_no_errors_returns_unchanged(tmp_path):
    src = tmp_path / "out.jsonl"
    _write_output_file(src, [_row(1, "### 500000 INR")])

    df = await retry_file(src, task_to_system_prompt=_PROMPTS, confirm_prompt=False)
    assert len(df) == 1
    assert not (tmp_path / "out_retried.jsonl").exists()


@pytest.mark.asyncio
async def test_retry_uses_per_row_model_and_temp(tmp_path):
    """Each error row is retried with its own model/temp from the file."""
    src = tmp_path / "out.jsonl"
    _write_output_file(src, [
        _row(1, "ERROR: x", model="model-a", temperature=0.5),
        _row(2, "ERROR: y", model="model-b", temperature=0.0),
    ])

    captured = []

    @dataclass
    class _Recorder:
        async def call(self, model, prompt, system_prompt, temperature,
                       max_tokens, features, reasoning_effort="none",
                       should_skip=None):
            captured.append((features["id"], model, temperature))
            return _ok("### 500000 INR")

    with patch("runner.retry.ChatClient", return_value=_Recorder()):
        await retry_file(src, task_to_system_prompt=_PROMPTS, confirm_prompt=False)

    assert (1, "model-a", 0.5) in captured
    assert (2, "model-b", 0.0) in captured


@pytest.mark.asyncio
async def test_task_auto_detected_from_file(tmp_path):
    """Task comes from df['task'], not from caller. System prompt looked up by task."""
    src = tmp_path / "out.jsonl"
    _write_output_file(src, [_row(1, "ERROR: x", task="service_pricing_vendor")])

    captured = {}

    @dataclass
    class _Recorder:
        async def call(self, model, prompt, system_prompt, temperature,
                       max_tokens, features, reasoning_effort="none",
                       should_skip=None):
            captured["system_prompt"] = system_prompt
            return _ok("### 500000 INR")

    with patch("runner.retry.ChatClient", return_value=_Recorder()):
        await retry_file(src, task_to_system_prompt=_PROMPTS, confirm_prompt=False)

    assert captured["system_prompt"] == _PROMPTS["service_pricing_vendor"]


@pytest.mark.asyncio
async def test_missing_task_column_raises(tmp_path):
    src = tmp_path / "out.jsonl"
    _write_output_file(src, [{
        "id": 1, "prompt": "p1", "model": "m", "temperature": 0.0,
        "response": "ERROR: x",
    }])

    with pytest.raises(ValueError, match="no 'task' column"):
        await retry_file(src, task_to_system_prompt=_PROMPTS, confirm_prompt=False)


@pytest.mark.asyncio
async def test_unknown_task_raises(tmp_path):
    src = tmp_path / "out.jsonl"
    _write_output_file(src, [_row(1, "ERROR: x", task="not_a_task")])

    with pytest.raises(ValueError, match="No system prompt"):
        await retry_file(src, task_to_system_prompt=_PROMPTS, confirm_prompt=False)
