"""
retry.py — In-place retry of ERROR rows from a previous output file.

Reads <prefix>.jsonl, finds rows where response startswith 'ERROR:',
re-runs only those rows (using each row's own model + temperature), writes
the result to <prefix>_retried.jsonl. All non-ERROR rows pass through
unchanged so the retried file is a complete drop-in replacement.

The task and system prompt are auto-detected from the file:
  - task         : most common value of df['task']
  - system_prompt: looked up from the task → prompt mapping passed in by main.py
"""

import asyncio
import logging
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from runner.client import ChatClient, HTTPRetryExhausted, RequestTimeoutError
from runner.confirmation import confirm
from runner.io import get_git_sha, load, retry_path, save
from runner.row import Row, coerce_row_columns_to_object
from scripts.validation import (
    ValidationContext, ValidationSeverity, validate_response_during_eval,
)

log = logging.getLogger(__name__)


def _is_error(response) -> bool:
    return isinstance(response, str) and response.startswith("ERROR:")


def _detect_task(df: pd.DataFrame) -> str:
    """Most common task value in df['task']. Errors if column is missing/empty."""
    if "task" not in df.columns:
        raise ValueError(
            "Cannot auto-detect task: file has no 'task' column. "
            "Re-run with an output file that includes the task feature."
        )
    tasks = df["task"].dropna().astype(str).str.lower()
    if tasks.empty:
        raise ValueError("Cannot auto-detect task: 'task' column is empty.")
    counts = Counter(tasks)
    if len(counts) > 1:
        log.warning(f"Mixed tasks in file: {dict(counts)} — using most common.")
    return counts.most_common(1)[0][0]


async def retry_file(
        path: str | Path,
        task_to_system_prompt: dict[str, str],
        rate_limit: int = 60,
        max_tokens: int = 1200,
        reasoning_effort: str = "none",
        confirm_prompt: bool = True,
        max_rounds: int = 3,
) -> pd.DataFrame:
    """
    Retry every ERROR row in `path`.

    Per-row uses that row's own model and temperature. Task is auto-detected
    from df['task'] and used to look up the system prompt.

    Returns the merged DataFrame (passthrough rows + retried rows).
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"No such output file: {path}")

    df = load(path, prompt_column="prompt")
    coerce_row_columns_to_object(df)

    # Ensure validation columns exist so per-row writes from validated retries
    # actually land. Older output files may predate validation tracking.
    for col, default in (("validation_status",   "valid"),
                         ("validation_reason",   ""),
                         ("validation_severity", "valid")):
        if col not in df.columns:
            df[col] = default

    task = _detect_task(df)
    system_prompt = task_to_system_prompt.get(task)
    if system_prompt is None:
        raise ValueError(
            f"No system prompt registered for task='{task}'. "
            f"Known: {sorted(task_to_system_prompt)}"
        )
    if "model" not in df.columns or "temperature" not in df.columns:
        raise ValueError(
            f"{path} missing 'model' or 'temperature' columns — cannot retry."
        )

    out_path = retry_path(path)
    client = ChatClient(rate_limit=rate_limit)
    git_sha = get_git_sha()

    feat_cols = [
        c for c in df.columns
        if c not in {
            "prompt", "response", "tokens_prompt", "tokens_completion",
            "tokens_total", "finish_reason", "reasoning_content",
            "reasoning_effort", "created_at", "request_duration",
            "system_prompt", "git_sha", "runner_version", "python_version",
            "validation_status", "validation_reason", "validation_severity",
            "model", "temperature",
        }
    ]

    round_num = 0
    while True:
        round_num += 1
        error_mask = df["response"].apply(_is_error)
        error_idxs = df[error_mask].index.tolist()
        n_errors = len(error_idxs)

        if n_errors == 0:
            if round_num == 1:
                log.info(f"No ERROR rows in {path} — nothing to retry.")
            else:
                log.info(f"All rows clean after {round_num - 1} round(s).")
            break

        # ── Confirmation per round ──
        if round_num == 1:
            models_in_file = sorted(
                df.loc[error_mask, "model"].dropna().astype(str).unique()
            )
            proceed = confirm(
                title="RETRY",
                input_path=path,
                models=models_in_file,
                task=task,
                rows_to_run=n_errors,
                system_prompt=system_prompt,
                reasoning_effort=reasoning_effort,
                max_tokens=max_tokens,
                rate_limit=rate_limit,
                output_path=out_path,
                skip=not confirm_prompt,
            )
            if not proceed:
                log.info("Cancelled.")
                return df
        else:
            # Subsequent rounds: validation produced new ERROR rows.
            log.warning(
                f"Round {round_num}: {n_errors} row(s) still failing validation."
            )
            if round_num > max_rounds:
                log.warning(
                    f"Hit max_rounds={max_rounds}; leaving {n_errors} row(s) "
                    f"as ERROR for a future retry pass."
                )
                break
            if confirm_prompt:
                try:
                    ans = input(
                        f"  Re-retry {n_errors} validation-failed row(s)? [y/N]: "
                    ).strip().lower()
                except EOFError:
                    ans = "n"
                if ans not in ("y", "yes"):
                    log.info("Stopping after this round.")
                    break

        # ── Run one retry round ──
        coros = [
            _retry_one_row(
                row=df.loc[i],
                features={c: df.at[i, c] for c in feat_cols},
                client=client, system_prompt=system_prompt,
                max_tokens=max_tokens, reasoning_effort=reasoning_effort,
                git_sha=git_sha, task=task,
            )
            for i in error_idxs
        ]
        log.info(f"Round {round_num}: retrying {n_errors} row(s)…")
        new_rows: list[Row] = await asyncio.gather(*coros)

        for i, row in zip(error_idxs, new_rows):
            for k, v in row.flat().items():
                if k in df.columns:
                    df.at[i, k] = v

        # Save after each round so progress survives Ctrl-C.
        save(df, out_path)

        n_still_failing = int(df["response"].apply(_is_error).sum())
        log.info(
            f"Round {round_num} done: {n_errors - n_still_failing}/{n_errors} "
            f"recovered, {n_still_failing} still failing → {out_path}"
        )

    return df


# OpenAI-style finish_reason values that mean the response was cut off
# rather than completed naturally. Anything outside {"stop", "end_turn"}
# is suspicious — "length" is the most common for max_tokens truncation.
_TRUNCATING_FINISH_REASONS = {"length", "max_tokens", "content_filter"}


def _validate_retried_response(
        response: str, task: str, finish_reason: str = "stop",
) -> tuple[str, str, str, str]:
    """
    Validate a retried response. Returns (effective_response, status,
    reason, severity).

    Two failure paths:
      1. finish_reason indicates truncation (e.g. "length") — rewrite as
         ERROR even if the partial text happens to parse cleanly.
      2. validate_response_during_eval returns TERMINATE severity (format
         error, amount_low, [TRUNCATED] marker, ellipsis-truncation, etc.)

    Either path produces an ERROR row that the next retry pass will pick up.
    """
    if finish_reason in _TRUNCATING_FINISH_REASONS:
        reason = f"Response truncated (finish_reason={finish_reason})"
        effective = f"ERROR: Validation failed [truncation]: {reason}"
        return effective, "invalid", reason, "terminate"

    ctx = ValidationContext(model="retry", task=task, temperature=0.0)
    result, _ = validate_response_during_eval(
        response=response, task=task, context=ctx,
    )
    severity = result.severity.value
    status = "valid" if result.is_valid else "invalid"
    reason = result.reason

    if result.severity == ValidationSeverity.TERMINATE:
        effective = (
            f"ERROR: Validation failed [{result.check_type}]: {result.reason}"
        )
    else:
        effective = response
    return effective, status, reason, severity


async def _retry_one_row(
        row: pd.Series,
        features: dict,
        client: ChatClient,
        system_prompt: str,
        max_tokens: int,
        reasoning_effort: str,
        git_sha: str,
        task: str,
) -> Row:
    """Retry a single row using its own model/temp, then validate the response."""
    model = str(row["model"])
    temperature = float(row["temperature"])
    prompt = str(row["prompt"])

    t0 = datetime.now()
    try:
        result = await client.call(
            model=model, prompt=prompt, system_prompt=system_prompt,
            temperature=temperature, max_tokens=max_tokens,
            features=features, reasoning_effort=reasoning_effort,
        )
        dur = (datetime.now() - t0).total_seconds()

        effective, status, reason, severity = _validate_retried_response(
            response=result.content, task=task,
            finish_reason=result.finish_reason,
        )

        return Row(
            model=model, prompt=prompt, temperature=temperature,
            response=effective,
            tokens_prompt=result.prompt_tokens,
            tokens_completion=result.completion_tokens,
            tokens_total=result.total_tokens,
            finish_reason=result.finish_reason,
            reasoning_content=result.reasoning_content,
            reasoning_effort=result.reasoning_effort,
            created_at=datetime.now().isoformat(),
            request_duration=dur,
            features=features,
            system_prompt=system_prompt,
            git_sha=git_sha,
            validation_status=status,
            validation_reason=reason,
            validation_severity=severity,
        )
    except (RequestTimeoutError, HTTPRetryExhausted, Exception) as e:
        dur = (datetime.now() - t0).total_seconds()
        log.error(f"Retry still failed for {features.get('id', '?')}: {e}")
        return Row(
            model=model, prompt=prompt, temperature=temperature,
            response=f"ERROR: {e}",
            finish_reason="error",
            created_at=datetime.now().isoformat(),
            request_duration=dur,
            features=features,
            system_prompt=system_prompt,
            git_sha=git_sha,
            validation_status="invalid",
            validation_reason=str(e),
            validation_severity="terminate",
        )
