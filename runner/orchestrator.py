"""
orchestrator.py — Main runner loop.

Per (model, temperature):
  1. Resume diff (if cfg.resume) → trim already-completed rows.
  2. Confirmation prompt (if cfg.confirm).
  3. Fan out tasks at cfg.rate_limit concurrency.
  4. Validate each response via ValidationHook.
  5. On termination signal: stop dispatching, drain in-flight,
     mark NOT-YET-SENT rows as 'ERROR: Batch Terminated due to {reason}',
     save everything so nothing is lost.
  6. Save the final DataFrame.
"""

import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from runner.client import (
    ChatClient,
    HTTPRetryExhausted,
    RequestTimeoutError,
    SkippedAfterAcquire,
)
from runner.confirmation import confirm
from runner.config import RunConfig
from runner.io import get_git_sha, load, output_path, save
from runner.resume import diff_input_vs_output
from runner.row import Row
from runner.validation_hook import ValidationHook

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal: build a Row for a single dispatched task
# ---------------------------------------------------------------------------


async def _process_one(
        idx: int,
        total: int,
        prompt: str,
        features: dict,
        model: str,
        temperature: float,
        cfg: RunConfig,
        client: ChatClient,
        hook: ValidationHook,
        terminated: asyncio.Event,
        terminate_reason: list,  # mutable container to share reason across tasks
        git_sha: str,
) -> Row:
    """Dispatch one prompt and turn it into a Row. Honors termination flag."""

    # Pre-check: if termination already signaled, mark this row as ERROR
    # without sending a request.
    if terminated.is_set():
        return _terminated_row(
            prompt, features, model, temperature, cfg, git_sha,
            reason=terminate_reason[0] if terminate_reason else "unknown",
        )

    t0 = datetime.now()
    try:
        result = await client.call(
            model=model, prompt=prompt, system_prompt=cfg.system_prompt,
            temperature=temperature, max_tokens=cfg.max_tokens,
            features=features, reasoning_effort=cfg.reasoning_effort,
            should_skip=terminated.is_set,
        )
        dur = (datetime.now() - t0).total_seconds()
        log.info(
            f"✓ done     [{idx + 1}/{total}] model={model} t={temperature} "
            f"id={features.get('id', '?')} ({dur:.1f}s)"
        )

        decision = hook.evaluate(result.content)
        if decision.should_terminate and not terminated.is_set():
            terminated.set()
            terminate_reason.append(decision.terminate_reason)
            log.warning(
                f"✗ TERMINATE signal raised: {decision.terminate_reason}. "
                f"In-flight requests will drain; no new requests will be sent."
            )

        return Row(
            model=model, prompt=prompt, temperature=temperature,
            response=result.content,
            tokens_prompt=result.prompt_tokens,
            tokens_completion=result.completion_tokens,
            tokens_total=result.total_tokens,
            finish_reason=result.finish_reason,
            reasoning_content=result.reasoning_content,
            reasoning_effort=result.reasoning_effort,
            created_at=datetime.now().isoformat(),
            request_duration=dur,
            features=features,
            system_prompt=cfg.system_prompt or "",
            git_sha=git_sha,
            validation_status=(
                "valid" if decision.result.is_valid else "invalid"
            ),
            validation_reason=decision.result.reason,
            validation_severity=decision.result.severity.value,
        )

    except SkippedAfterAcquire:
        # Termination fired while this row was queued at the semaphore.
        return _terminated_row(
            prompt, features, model, temperature, cfg, git_sha,
            reason=terminate_reason[0] if terminate_reason else "unknown",
        )

    except RequestTimeoutError as e:
        dur = (datetime.now() - t0).total_seconds()
        log.warning(f"⚠ timeout  [{idx + 1}/{total}] model={model} ({dur:.1f}s)")
        decision = hook.record_timeout()
        if decision.should_terminate and not terminated.is_set():
            terminated.set()
            terminate_reason.append(decision.terminate_reason)
        return _error_row(
            prompt, features, model, temperature, cfg, git_sha,
            reason=f"TIMEOUT: {e}", duration=dur,
        )

    except (HTTPRetryExhausted, Exception) as e:
        dur = (datetime.now() - t0).total_seconds()
        log.error(f"✗ error    [{idx + 1}/{total}] model={model}: {e}")
        return _error_row(
            prompt, features, model, temperature, cfg, git_sha,
            reason=f"ERROR: {e}", duration=dur,
        )


def _error_row(
        prompt: str, features: dict, model: str, temperature: float,
        cfg: RunConfig, git_sha: str, reason: str, duration: float = 0.0,
) -> Row:
    return Row(
        model=model, prompt=prompt, temperature=temperature,
        response=reason,
        finish_reason="error",
        created_at=datetime.now().isoformat(),
        request_duration=duration,
        features=features,
        system_prompt=cfg.system_prompt or "",
        git_sha=git_sha,
        validation_status="invalid",
        validation_reason=reason,
        validation_severity="terminate",
    )


def _terminated_row(
        prompt: str, features: dict, model: str, temperature: float,
        cfg: RunConfig, git_sha: str, reason: str,
) -> Row:
    msg = f"ERROR: Batch Terminated due to {reason}"
    return _error_row(
        prompt, features, model, temperature, cfg, git_sha,
        reason=msg, duration=0.0,
    )


# ---------------------------------------------------------------------------
# Per-(model, temp) loop
# ---------------------------------------------------------------------------


async def _run_one_combo(
        model: str,
        temperature: float,
        df: pd.DataFrame,
        src_path: Optional[Path],
        cfg: RunConfig,
        client: ChatClient,
        git_sha: str,
) -> pd.DataFrame:
    """Run all prompts for a single (model, temperature) combo."""

    # ── Resume diff ─────────────────────────────────────────────────────────
    out_path = output_path(
        src_path or Path(f"{cfg.task}.jsonl"), model, temperature,
        cfg.output_dir, cfg.output_filename,
    ) if (src_path or cfg.output_dir) else None

    resume_report = None
    rows_already_done: list[Row] = []
    if cfg.resume and out_path is not None:
        df, resume_report = diff_input_vs_output(
            df, output_path=out_path, input_path=src_path or Path("(in-memory)"),
        )
        if resume_report.is_complete:
            log.info(f"All {resume_report.total} rows already done — nothing to do.")
            return load(out_path) if out_path.exists() else pd.DataFrame()

    # ── Confirmation ────────────────────────────────────────────────────────
    proceed = confirm(
        title="RUN",
        input_path=src_path or Path("(in-memory)"),
        models=[model],
        task=cfg.task,
        rows_to_run=len(df),
        system_prompt=cfg.system_prompt,
        temperatures=[temperature],
        reasoning_effort=cfg.reasoning_effort,
        max_tokens=cfg.max_tokens,
        rate_limit=cfg.rate_limit,
        output_path=out_path,
        bypass=cfg.no_terminate,
        resume_report=resume_report,
        skip=not cfg.confirm,
    )
    if not proceed:
        log.info("Cancelled by user.")
        return pd.DataFrame()

    # ── Fan-out ────────────────────────────────────────────────────────────
    prompts = df[cfg.prompt_column].tolist()
    feat_cols = (
        [c for c in cfg.feature_columns if c in df.columns]
        if cfg.feature_columns is not None
        else [c for c in df.columns if c != cfg.prompt_column]
    )
    features_list = [{c: row[c] for c in feat_cols} for _, row in df.iterrows()]
    total = len(prompts)

    log.info(
        f"┌─ Running model={model} temp={temperature} "
        f"on {total} rows from {src_path or '(in-memory)'}"
    )

    hook = ValidationHook(model=model, task=cfg.task, temperature=temperature, bypass=cfg.no_terminate)
    terminated = asyncio.Event()
    terminate_reason: list[str] = []

    tasks = [
        asyncio.create_task(_process_one(
            idx=i, total=total, prompt=p, features=feats,
            model=model, temperature=temperature, cfg=cfg,
            client=client, hook=hook,
            terminated=terminated, terminate_reason=terminate_reason,
            git_sha=git_sha,
        ))
        for i, (p, feats) in enumerate(zip(prompts, features_list))
    ]

    rows: list[Row] = await asyncio.gather(*tasks, return_exceptions=False)

    # ── Merge with prior output if resuming ────────────────────────────────
    out_df = pd.DataFrame([r.flat() for r in rows])
    if cfg.resume and out_path is not None and out_path.exists():
        try:
            prior = load(out_path)
            out_df = pd.concat([prior, out_df], ignore_index=True)
            log.info(
                f"Merged with prior output ({len(prior)} existing + "
                f"{len(rows)} new = {len(out_df)})"
            )
        except Exception as e:
            log.warning(f"Could not merge with prior {out_path}: {e}")

    # ── Save ───────────────────────────────────────────────────────────────
    if cfg.export and out_path is not None:
        save(out_df, out_path)

    if terminated.is_set():
        n_terminated = sum(
            1 for r in rows if r.response.startswith("ERROR: Batch Terminated")
        )
        log.warning(
            f"└─ Terminated. Reason: {terminate_reason[0]}. "
            f"{n_terminated}/{total} rows marked as Batch Terminated."
        )
    else:
        log.info(f"└─ Completed model={model} temp={temperature}: {len(rows)} rows")

    return out_df


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


async def run(cfg: RunConfig) -> list[pd.DataFrame]:
    """
    End-to-end run. main.py calls this.

    Returns one DataFrame per (model × temperature) combo.
    """
    # Resolve input
    if isinstance(cfg.data, (str, Path)):
        src_path = Path(cfg.data)
        df = load(src_path, cfg.prompt_column)
    elif isinstance(cfg.data, pd.DataFrame):
        df = cfg.data.copy()
        src_path = Path(cfg.input_path) if cfg.input_path else None
    elif isinstance(cfg.data, list):
        df = pd.DataFrame({cfg.prompt_column: cfg.data})
        src_path = Path(cfg.input_path) if cfg.input_path else None
    else:
        raise TypeError(f"Unsupported data type: {type(cfg.data)}")

    # Smoke test
    if cfg.smoke_test is not None:
        n = min(cfg.smoke_test, len(df))
        df = df.sample(n, random_state=cfg.seed).reset_index(drop=True)
        log.info(f"[smoke test] sampled {n} rows")

    # Pin created_at as string if present
    if "created_at" in df.columns:
        df["created_at"] = df["created_at"].astype(str)

    client = ChatClient(
        rate_limit=cfg.rate_limit,
        max_retries=cfg.http_max_retries,
        max_backoff=cfg.http_max_backoff,
        timeout=cfg.http_timeout,
    )
    git_sha = get_git_sha()

    results: list[pd.DataFrame] = []
    for model in cfg.models:
        for temp in cfg.temperatures:
            # NOTE: each (model, temp) gets its own ValidationHook + terminate
            # event. Termination in one combo does NOT affect the next.
            try:
                out_df = await _run_one_combo(
                    model=model, temperature=temp, df=df.copy(),
                    src_path=src_path, cfg=cfg, client=client, git_sha=git_sha,
                )
                results.append(out_df)
            except Exception as e:
                log.error(f"✗ Combo failed model={model} t={temp}: {e}")
                results.append(pd.DataFrame())

    return results
