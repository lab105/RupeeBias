"""
config.py — RunConfig: every parameter the runner needs in one dataclass.

main.py builds one of these from CLI args, then calls runner.run(cfg).
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional, Union

import pandas as pd

ReasoningEffort = Literal["none", "minimal", "low", "medium", "high", "xhigh"]

# ---------------------------------------------------------------------------
# Bypass checks — which validation severities should be downgraded to FLAG
# ---------------------------------------------------------------------------

# Each name corresponds to a check_type or termination path.
# Pass any subset of these to RunConfig.no_terminate to disable that path.
BYPASS_CHECKS: set[str] = {
    "refusal",       # high refusal rate
    "consecutive",   # too many consecutive failures
    "amount_high",   # numeric value above max range
    "amount_low",    # numeric value below min range
    "truncation",    # response truncated by API
    "timeout",       # request timeout (counted as consecutive failure)
    "format",        # format errors (missing ###, wrong unit, etc.)
}


@dataclass(frozen=True)
class BypassChecks:
    """Wrapper around the set of bypassed check names with a parser."""

    checks: frozenset[str] = frozenset()

    @classmethod
    def parse(cls, raw: Optional[str]) -> "BypassChecks":
        """
        Parse a CLI string like 'refusal,consecutive' into BypassChecks.

        Accepts None / '' / 'all'. 'all' bypasses every termination path.
        Unknown names raise ValueError so typos surface immediately.
        """
        if not raw:
            return cls()
        if raw.strip().lower() == "all":
            return cls(checks=frozenset(BYPASS_CHECKS))

        names = {n.strip().lower() for n in raw.split(",") if n.strip()}
        unknown = names - BYPASS_CHECKS
        if unknown:
            raise ValueError(
                f"Unknown --no-terminate checks: {sorted(unknown)}. "
                f"Valid: {sorted(BYPASS_CHECKS)}"
            )
        return cls(checks=frozenset(names))

    def __contains__(self, check: str) -> bool:
        return check in self.checks

    def __bool__(self) -> bool:
        return bool(self.checks)

    def __str__(self) -> str:
        return ",".join(sorted(self.checks)) if self.checks else "(none)"


# ---------------------------------------------------------------------------
# Main config dataclass
# ---------------------------------------------------------------------------


@dataclass
class RunConfig:
    """All parameters for a single runner invocation."""

    # — Required —
    data: Union[str, Path, pd.DataFrame, list]
    models: list[str]
    task: str  # snake_case task identifier — drives validation + system prompt

    # — Prompting —
    system_prompt: Optional[str] = None
    temperatures: list[float] = field(default_factory=lambda: [0.0])
    reasoning_effort: ReasoningEffort = "none"
    max_tokens: int = 1200
    prompt_column: str = "prompt"
    feature_columns: Optional[list[str]] = None

    # — I/O —
    input_path: Optional[Union[str, Path]] = None
    output_dir: Optional[Union[str, Path]] = None
    output_filename: Optional[str] = None
    export: bool = True

    # — Concurrency / HTTP —
    rate_limit: int = 60
    http_max_retries: int = 5
    http_max_backoff: float = 30.0
    http_timeout: float = 600.0

    # — Behavior toggles —
    resume: bool = False
    smoke_test: Optional[int] = None       # if set, sample N rows
    confirm: bool = True                   # show confirmation prompt
    no_terminate: BypassChecks = field(default_factory=BypassChecks)

    # — Sampling tracking —
    seed: int = 42

    def __post_init__(self) -> None:
        self.task = self.task.lower()
        if self.output_dir is not None:
            self.output_dir = Path(self.output_dir)
        if self.input_path is not None:
            self.input_path = Path(self.input_path)
