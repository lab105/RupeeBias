"""
row.py — Single result row dataclass + flat() for DataFrame export.

ROW_STRING_COLUMNS lets callers (retry, revalidate) coerce a loaded DataFrame's
string-valued Row columns to object dtype before per-row mutation. Without
this, pandas can infer a column as int64/float64/datetime64 from the loaded
data and then refuse to overwrite it with a Row's str value.
"""

import sys
from dataclasses import dataclass, asdict, field
from typing import Literal

import pandas as pd

RUNNER_VERSION = "0.3.0"

ROW_STRING_COLUMNS: frozenset[str] = frozenset({
    "model", "prompt", "response", "finish_reason",
    "reasoning_content", "reasoning_effort", "created_at",
    "system_prompt", "git_sha", "runner_version", "python_version",
    "validation_status", "validation_reason", "validation_severity",
})


def coerce_row_columns_to_object(df: pd.DataFrame) -> pd.DataFrame:
    """Cast every Row string column present in df to object dtype, in place."""
    for col in ROW_STRING_COLUMNS:
        if col in df.columns and not pd.api.types.is_object_dtype(df[col]):
            df[col] = df[col].astype(object)
    return df


@dataclass
class Row:
    model: str
    prompt: str
    temperature: float
    response: str
    tokens_prompt: int = 0
    tokens_completion: int = 0
    tokens_total: int = 0
    finish_reason: str = ""
    reasoning_content: str = ""
    reasoning_effort: Literal[
        "none", "minimal", "low", "medium", "high", "xhigh"
    ] = "none"
    created_at: str = ""
    request_duration: float = 0.0
    features: dict = field(default_factory=dict)
    system_prompt: str = ""
    git_sha: str = "unknown"
    runner_version: str = RUNNER_VERSION
    python_version: str = field(default_factory=lambda: sys.version.split()[0])
    validation_status: str = "valid"
    validation_reason: str = ""
    validation_severity: str = "valid"

    def flat(self) -> dict:
        """Flatten features dict into top-level keys for DataFrame export."""
        d = asdict(self)
        feats = d.pop("features", {})
        return {**feats, **d}
