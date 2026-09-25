"""
common.py — Shared per-task helpers used by every task module.

Functions here build the standard per-axis table shapes:
  - friedman_table    : Friedman primary, per axis.
  - kw_table          : Kruskal-Wallis (kept for appendix), per axis.
  - canonical_table   : CPG + sign_consistency + r_rb (+CIs) per axis.
  - leaderboard_table : per-(model × axis) Mean Δ% and V@10%, plus overall.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.config import AXES, CANONICAL_PAIRS
from analysis.metrics.canonical import canonical_pair_stats, mog_stats
from analysis.metrics.ci import bootstrap_mean_ci, wilson_ci
from analysis.metrics.omnibus import (
    friedman, kruskal_wallis, mean_center_per_model,
)
from analysis.metrics.pair import (
    build_pair_table, mean_delta_pct, violation_at,
)


# ---------------------------------------------------------------------------
# Omnibus tables
# ---------------------------------------------------------------------------


def friedman_table(df: pd.DataFrame, value_col: str = "value") -> pd.DataFrame:
    """Friedman per axis. Uses per-model mean-centered values."""
    if df is None or df.empty:
        return pd.DataFrame()
    rows = []
    for ax in sorted(df["axis"].dropna().unique()):
        sub = df[df["axis"] == ax]
        sub_c = mean_center_per_model(sub, value_col=value_col)
        r = friedman(sub_c, value_col="value_centered")
        rows.append({"axis": ax, **r})
    return pd.DataFrame(rows)


def kw_table(df: pd.DataFrame, value_col: str = "value") -> pd.DataFrame:
    """Kruskal-Wallis per axis (kept for appendix)."""
    if df is None or df.empty:
        return pd.DataFrame()
    rows = []
    for ax in sorted(df["axis"].dropna().unique()):
        sub = df[df["axis"] == ax]
        sub_c = mean_center_per_model(sub, value_col=value_col)
        r = kruskal_wallis(sub_c, value_col="value_centered")
        rows.append({"axis": ax, **r})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Canonical-pair / MOG table
# ---------------------------------------------------------------------------


def canonical_table(
        df: pd.DataFrame,
        value_col: str = "value",
        seed_prefix: str = "cpg",
) -> pd.DataFrame:
    """One row per axis with CPG, sign_consistency, r_rb, MOG."""
    if df is None or df.empty:
        return pd.DataFrame()
    rows = []
    for ax in AXES:
        sub = df[df["axis"] == ax]
        if sub.empty:
            continue
        cp = canonical_pair_stats(
            sub, ax, CANONICAL_PAIRS, value_col=value_col, seed_prefix=seed_prefix,
        )
        mg = mog_stats(sub, value_col=value_col, seed_prefix=seed_prefix)
        if not cp and not mg:
            continue
        rows.append({**cp, **mg})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Mini leaderboard
# ---------------------------------------------------------------------------


def _mean_delta_per_axis(model_df: pd.DataFrame) -> dict[str, float]:
    """Per-axis Mean Δ% for one model's data."""
    out = {}
    for ax in AXES:
        sub = model_df[model_df["axis"] == ax]
        if sub.empty:
            out[ax] = float("nan")
            continue
        pt = build_pair_table(sub)
        out[ax] = round(mean_delta_pct(pt), 2)
    return out


def leaderboard_table(
        df_all_models: pd.DataFrame,
        task_label: str = "task",
) -> pd.DataFrame:
    """
    Per-model leaderboard for one task. Columns:
      model | Mean Δ% per-axis × 6 | Mean Δ% Overall + 95% CI | V@10% Overall + Wilson CI
    """
    if df_all_models is None or df_all_models.empty:
        return pd.DataFrame()

    rows = []
    for model in sorted(df_all_models["model_slug"].dropna().unique()):
        m_df = df_all_models[df_all_models["model_slug"] == model]
        per_ax = _mean_delta_per_axis(m_df)

        pair_frames = [
            build_pair_table(m_df[m_df["axis"] == ax])
            for ax in m_df["axis"].dropna().unique()
        ]
        pair_frames = [p for p in pair_frames if not p.empty]
        if not pair_frames:
            continue
        pairs = pd.concat(pair_frames, ignore_index=True)

        mean_dp = mean_delta_pct(pairs)
        deltas = pairs["delta_pct"].dropna().to_numpy()
        ci_lo, ci_hi = bootstrap_mean_ci(deltas, seed_str=f"mdp:{task_label}:{model}")
        v10_pct, n_v10, n_total = violation_at(pairs, 10)
        v10_lo, v10_hi = wilson_ci(n_v10, n_total)

        rows.append({
            "model":  model,
            **{f"Mean Δ% {ax}": per_ax.get(ax, np.nan) for ax in AXES},
            "Mean Δ% Overall":    round(mean_dp, 2),
            "Mean Δ% CI lower":   ci_lo,
            "Mean Δ% CI upper":   ci_hi,
            "V@10% Overall":      v10_pct,
            "V@10% CI lower":     v10_lo,
            "V@10% CI upper":     v10_hi,
            "n_pairs":            n_total,
        })
    return pd.DataFrame(rows)
