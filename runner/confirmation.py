"""
confirmation.py — Pre-run interactive confirmation.

One generic block used by both fresh runs and in-place retries. Shows the
file, model(s), task, system prompt preview, and bypass list. Returns True
on user confirmation.
"""

import logging
from pathlib import Path
from typing import Optional

from runner.config import BypassChecks
from runner.resume import ResumeReport
from scripts.confirmation import MODEL_PRICING, _calculate_cost, _estimate_time

log = logging.getLogger(__name__)

_BAR = "═" * 70
_MAX_PROMPT_PREVIEW = 240   # chars shown of system prompt before truncating


def _yes_no(prompt: str) -> bool:
    try:
        ans = input(prompt).strip().lower()
    except EOFError:
        return False
    return ans in ("y", "yes")


def _format_prompt(prompt: Optional[str]) -> str:
    if not prompt:
        return "(none)"
    flat = " ".join(prompt.split())
    if len(flat) <= _MAX_PROMPT_PREVIEW:
        return flat
    return flat[:_MAX_PROMPT_PREVIEW].rstrip() + " …"


def _models_str(models: list[str]) -> str:
    if len(models) == 1:
        return models[0]
    if len(models) <= 3:
        return ", ".join(models)
    return f"{len(models)} models: " + ", ".join(models[:2]) + ", …"


def confirm(
        *,
        title: str,
        input_path: Path,
        models: list[str],
        task: str,
        rows_to_run: int,
        system_prompt: Optional[str],
        temperatures: Optional[list[float]] = None,
        reasoning_effort: str = "none",
        max_tokens: int = 1200,
        rate_limit: int = 60,
        output_path: Optional[Path] = None,
        bypass: Optional[BypassChecks] = None,
        resume_report: Optional[ResumeReport] = None,
        skip: bool = False,
) -> bool:
    """
    Generic confirmation block. Returns True if `skip` or user types y/yes.

    title:        "RUN" or "RETRY" — header label.
    models:       one or many model IDs (retry can have multiple per row).
    system_prompt: full system prompt; truncated for display.
    output_path:  destination file (run) or *_retried file (retry).
    """
    if skip:
        return True

    cost = sum(
        _calculate_cost(m, rows_to_run) if m in MODEL_PRICING else 0.0
        for m in models
    )
    eta = _estimate_time(rows_to_run) if rows_to_run > 0 else "—"

    print(f"\n{_BAR}")
    print(f"  {title} CONFIRMATION")
    print(_BAR)
    print(f"  File          : {input_path}")
    print(f"  Model         : {_models_str(models)}")
    print(f"  Task          : {task}")
    if temperatures is not None:
        print(f"  Temperature   : {temperatures if len(temperatures) > 1 else temperatures[0]}")
    print(f"  Reasoning     : {reasoning_effort}")
    print(f"  Max tokens    : {max_tokens}")
    print(f"  Rate limit    : {rate_limit}")
    if output_path is not None:
        print(f"  Output        : {output_path}")
    if bypass is not None:
        print(f"  Bypass        : {bypass}")
    print(f"  System prompt : {_format_prompt(system_prompt)}")
    if resume_report:
        print(
            f"  Resume        : {resume_report.completed}/{resume_report.total} "
            f"already done → running {resume_report.remaining} new"
        )
    print(f"  Rows to run   : {rows_to_run}")
    print(f"  Est. cost     : ${cost:.2f}")
    print(f"  Est. time     : {eta}")
    print(_BAR)

    return _yes_no("  Proceed? [y/N]: ")
