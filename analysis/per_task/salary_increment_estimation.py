"""salary_increment_estimation — hike% task tables, plus ASR-specific output."""

from __future__ import annotations

import pandas as pd

from analysis.config import AXES, CANONICAL_PAIRS
from analysis.io import load_concat
from analysis.metrics.asr import asr_canonical_pair, asr_per_variant_profile
from analysis.metrics.omnibus import friedman, kruskal_wallis
from analysis.parsers import parse_response_column
from analysis.per_task.common import (
    canonical_table, friedman_table, kw_table, leaderboard_table,
)

TASK = "salary_increment_estimation"


def _asr_friedman_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ax in AXES:
        sub = df[df["axis"] == ax]
        if sub.empty:
            continue
        asr_pp = asr_per_variant_profile(sub)
        if asr_pp.empty:
            continue
        r = friedman(
            asr_pp.rename(columns={"asr": "value"}),
            value_col="value",
            block_col="profile_id",
            treatment_col="identifier_value",
            model_col=None,
        )
        rk = kruskal_wallis(asr_pp.rename(columns={"asr": "value"}))
        rows.append({
            "axis": ax,
            "friedman_chi2": r["chi2"], "friedman_p": r["p"],
            "friedman_df":   r["df"],   "friedman_W":  r["W"],
            "kw_H":   rk["H"], "kw_p":  rk["p"], "kw_df": rk["df"],
            "kw_eps2": rk["eps2"],
            "n_blocks": r["n_blocks"], "k": r["k"],
        })
    return pd.DataFrame(rows)


def _asr_canonical_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ax in AXES:
        priv, marg = CANONICAL_PAIRS.get(ax, (None, None))
        if priv is None:
            continue
        sub = df[df["axis"] == ax]
        if sub.empty:
            continue
        asr_pp = asr_per_variant_profile(sub)
        if asr_pp.empty:
            continue
        gap = asr_canonical_pair(asr_pp, priv, marg, seed_str=f"asr_gap:{TASK}:{ax}")
        rows.append({"axis": ax, **gap})
    return pd.DataFrame(rows)


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
        f"{TASK}_asr_omnibus":     _asr_friedman_table(valid),
        f"{TASK}_asr_canonical":   _asr_canonical_table(valid),
    }
