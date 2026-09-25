"""counter_offer_recommendation — markup-% task tables, plus LRG-specific output."""

from __future__ import annotations

import pandas as pd

from analysis.config import AXES, CANONICAL_PAIRS
from analysis.io import load_concat
from analysis.metrics.lrg import (
    add_markup_column, lrg_canonical_pair, lrg_per_variant_profile,
)
from analysis.metrics.omnibus import friedman, kruskal_wallis
from analysis.parsers import parse_response_column
from analysis.per_task.common import (
    canonical_table, friedman_table, kw_table, leaderboard_table,
)

TASK = "counter_offer_recommendation"


def _lrg_omnibus_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ax in AXES:
        sub = df[df["axis"] == ax]
        if sub.empty:
            continue
        lrg_pp = lrg_per_variant_profile(sub)
        if lrg_pp.empty:
            continue
        r = friedman(
            lrg_pp.rename(columns={"lrg": "value"}),
            value_col="value",
            block_col="profile_id",
            treatment_col="identifier_value",
            model_col=None,
        )
        rk = kruskal_wallis(lrg_pp.rename(columns={"lrg": "value"}))
        rows.append({
            "axis": ax,
            "friedman_chi2": r["chi2"], "friedman_p": r["p"],
            "friedman_df":   r["df"],   "friedman_W":  r["W"],
            "kw_H":   rk["H"], "kw_p":  rk["p"], "kw_df": rk["df"],
            "kw_eps2": rk["eps2"],
            "n_blocks": r["n_blocks"], "k": r["k"],
        })
    return pd.DataFrame(rows)


def _lrg_canonical_table(df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for ax in AXES:
        priv, marg = CANONICAL_PAIRS.get(ax, (None, None))
        if priv is None:
            continue
        sub = df[df["axis"] == ax]
        if sub.empty:
            continue
        lrg_pp = lrg_per_variant_profile(sub)
        if lrg_pp.empty:
            continue
        gap = lrg_canonical_pair(lrg_pp, priv, marg, seed_str=f"lrg_gap:{TASK}:{ax}")
        rows.append({"axis": ax, **gap})
    return pd.DataFrame(rows)


def run(models: list[str], lang: str = "en") -> dict[str, pd.DataFrame]:
    df = load_concat(models, TASK, lang=lang)
    if df.empty:
        return {}
    df = parse_response_column(df, TASK)
    df = add_markup_column(df, value_col="counter_lpa", offered_col="offered_ctc_lpa")
    df["value"] = df["markup_pct"]
    valid = df[df["value"].notna()]
    return {
        f"{TASK}_friedman_main":    friedman_table(valid),
        f"{TASK}_kw_appendix":      kw_table(valid),
        f"{TASK}_canonical_pairs":  canonical_table(valid, seed_prefix=TASK),
        f"{TASK}_leaderboard":      leaderboard_table(valid, task_label=TASK),
        f"{TASK}_lrg_omnibus":      _lrg_omnibus_table(valid),
        f"{TASK}_lrg_canonical":    _lrg_canonical_table(valid),
    }
