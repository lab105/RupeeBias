"""
resume.py — Compute the input ↔ output diff for resume mode.

Strategy: read the input file, read the existing output file (if any),
return only the rows whose 'id' isn't already in the output.
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd

from runner.io import load

log = logging.getLogger(__name__)


@dataclass
class ResumeReport:
    """Summary of what resume mode found."""
    input_path: Path
    output_path: Optional[Path]
    total: int           # rows in input
    completed: int       # rows already present in output (by id)
    remaining: int       # rows still to run

    @property
    def is_complete(self) -> bool:
        return self.remaining == 0


def diff_input_vs_output(
        df: pd.DataFrame,
        output_path: Optional[Path],
        input_path: Path,
        id_column: str = "id",
) -> tuple[pd.DataFrame, ResumeReport]:
    """
    Return (remaining_df, report) by removing rows whose id is already in
    the output file.

    If output_path doesn't exist, the entire input is treated as remaining.
    If the input lacks an id column, no diff is possible — input is returned
    unchanged with a warning.
    """
    total = len(df)

    if id_column not in df.columns:
        log.warning(
            f"Input has no '{id_column}' column — cannot diff. "
            f"Returning all {total} rows."
        )
        return df, ResumeReport(
            input_path=input_path, output_path=output_path,
            total=total, completed=0, remaining=total,
        )

    if output_path is None or not output_path.exists():
        log.info(f"No prior output at {output_path} — running all {total} rows.")
        return df, ResumeReport(
            input_path=input_path, output_path=output_path,
            total=total, completed=0, remaining=total,
        )

    try:
        prior = load(output_path, prompt_column=id_column)
    except Exception as e:
        log.warning(f"Could not read prior output {output_path}: {e} — running all rows.")
        return df, ResumeReport(
            input_path=input_path, output_path=output_path,
            total=total, completed=0, remaining=total,
        )

    completed_ids = set(prior[id_column].dropna().tolist())
    remaining_df = df[~df[id_column].isin(completed_ids)].reset_index(drop=True)
    completed = total - len(remaining_df)

    return remaining_df, ResumeReport(
        input_path=input_path, output_path=output_path,
        total=total, completed=completed, remaining=len(remaining_df),
    )
