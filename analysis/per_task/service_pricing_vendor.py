"""service_pricing_vendor — freelance project pricing, vendor side."""

from __future__ import annotations

import pandas as pd

from analysis.io import load_concat
from analysis.parsers import parse_response_column
from analysis.per_task.common import (
    canonical_table, friedman_table, kw_table, leaderboard_table,
)

TASK = "service_pricing_vendor"


def run(models: list[str], lang: str = "en") -> dict[str, pd.DataFrame]:
    df = load_concat(models, TASK, lang=lang)
    if df.empty:
        return {}
    df = parse_response_column(df, TASK)
    valid = df[df["value"].notna()]
    return {
        f"{TASK}_friedman_main":   friedman_table(valid),
        f"{TASK}_kw_appendix":     kw_table(valid),
        f"{TASK}_canonical_pairs": canonical_table(valid, seed_prefix=TASK),
        f"{TASK}_leaderboard":     leaderboard_table(valid, task_label=TASK),
    }
