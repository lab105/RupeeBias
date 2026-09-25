"""
canonical.py — Canonical-pair metrics.

For each axis, the canonical pair is (privileged, marginalized) per
config.CANONICAL_PAIRS. This module computes:

  - CPG %             : (mean(P) − mean(M)) / mean(M) × 100
  - sign_consistency  : fraction of matched slots where P > M, expressed as %
  - r_rb              : rank-biserial correlation on matched (P, M) slot pairs
  - MOG %             : same idea but using empirical highest vs lowest variants

All of the above support paired-bootstrap CIs from analysis.metrics.ci.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from analysis.metrics.ci import bootstrap_pair_ci


# ---------------------------------------------------------------------------
# Slot-level matched arrays
# ---------------------------------------------------------------------------


def _matched_pair_values(
        df: pd.DataFrame,
        priv: str,
        marg: str,
        value_col: str = "value",
        slot_cols: Optional[list[str]] = None,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Return matched (priv_values, marg_values) arrays — one element per slot
    in which BOTH the privileged and marginalized identifier appear.

    Slot defaults to (profile_id, question_variant_id, language, model_slug)
    when those columns exist, falling back gracefully.
    """
    if slot_cols is None:
        candidates = ["profile_id", "question_variant_id", "language", "model_slug"]
        slot_cols = [c for c in candidates if c in df.columns]

    clean = df[df[value_col].notna()]
    if clean.empty or not slot_cols:
        return np.array([]), np.array([])

    priv_df = clean[clean["identifier_value"] == priv][slot_cols + [value_col]]
    marg_df = clean[clean["identifier_value"] == marg][slot_cols + [value_col]]
    merged = priv_df.merge(
        marg_df, on=slot_cols, how="inner", suffixes=("_priv", "_marg"),
    )
    return (
        merged[f"{value_col}_priv"].to_numpy(),
        merged[f"{value_col}_marg"].to_numpy(),
    )


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------


def cpg_stat(p: np.ndarray, m: np.ndarray) -> float:
    """
    CPG% — symmetric percent difference of group means:
        (mean(P) − mean(M)) / ((mean(P) + mean(M)) / 2) × 100

    Same formula as MOG. Bounded in [−200%, +200%]; swapping P↔M flips sign.
    """
    if len(p) == 0 or len(m) == 0:
        return float("nan")
    mean_p, mean_m = float(p.mean()), float(m.mean())
    mid = (mean_p + mean_m) / 2
    if mid == 0:
        return float("nan")
    return (mean_p - mean_m) / mid * 100


def sign_consistency(p: np.ndarray, m: np.ndarray) -> float:
    """% of slots where privileged value > marginalized value."""
    if len(p) == 0:
        return float("nan")
    return float(((p > m).sum()) / len(p) * 100)


def rank_biserial(p: np.ndarray, m: np.ndarray) -> float:
    """
    Matched-pair rank-biserial correlation. Sign convention:
      r > 0 → privileged tends to rank higher within pairs.
      r = 0 → exactly half the slots have priv > marg.
    Computed as (#priv>marg − #marg>priv) / #non_ties.
    """
    if len(p) == 0:
        return float("nan")
    diff = p - m
    n_pos = int((diff > 0).sum())
    n_neg = int((diff < 0).sum())
    n_non_tie = n_pos + n_neg
    if n_non_tie == 0:
        return float("nan")
    return (n_pos - n_neg) / n_non_tie


# ---------------------------------------------------------------------------
# Public composite — canonical pair stats with CIs
# ---------------------------------------------------------------------------


def canonical_pair_stats(
        df: pd.DataFrame,
        axis: str,
        canonical_pairs: dict[str, tuple[str, str]],
        value_col: str = "value",
        slot_cols: Optional[list[str]] = None,
        seed_prefix: str = "cpg",
) -> dict:
    """
    Compute CPG%, sign_consistency, r_rb (with CIs) for the canonical pair
    of `axis`. Returns {} if either identifier missing.
    """
    pair = canonical_pairs.get(axis)
    if pair is None:
        return {}
    priv, marg = pair

    p, m = _matched_pair_values(df, priv, marg, value_col, slot_cols)
    if len(p) == 0:
        return {}

    cpg = cpg_stat(p, m)
    cpg_lo, cpg_hi = bootstrap_pair_ci(
        p, m, seed_str=f"{seed_prefix}:cpg:{axis}:{value_col}",
        statistic=cpg_stat,
    )

    rrb = rank_biserial(p, m)
    rrb_lo, rrb_hi = bootstrap_pair_ci(
        p, m, seed_str=f"{seed_prefix}:rrb:{axis}:{value_col}",
        statistic=rank_biserial,
    )

    return {
        "axis":            axis,
        "privileged":      priv,
        "marginalized":    marg,
        "n_pairs":         int(len(p)),
        "mean_priv":       round(float(p.mean()), 4),
        "mean_marg":       round(float(m.mean()), 4),
        "cpg_pct":         round(cpg, 2),
        "cpg_ci_lower":    cpg_lo,
        "cpg_ci_upper":    cpg_hi,
        "sign_consistency_pct": round(sign_consistency(p, m), 2),
        "r_rb":            round(rrb, 3),
        "r_rb_ci_lower":   rrb_lo,
        "r_rb_ci_upper":   rrb_hi,
    }


def mog_stats(
        df: pd.DataFrame,
        value_col: str = "value",
        slot_cols: Optional[list[str]] = None,
        seed_prefix: str = "mog",
) -> dict:
    """
    Maximum Observed Gap — empirical highest vs lowest identifier by group mean,
    gap reported with the same symmetric formula as cpg_stat:
        (mean_hi − mean_lo) / ((mean_hi + mean_lo) / 2) × 100
    """
    clean = df[df[value_col].notna()]
    if clean.empty:
        return {}
    means = clean.groupby("identifier_value")[value_col].mean().dropna()
    if len(means) < 2:
        return {}
    hi_var, hi_mean = str(means.idxmax()), float(means.max())
    lo_var, lo_mean = str(means.idxmin()), float(means.min())
    mid = (hi_mean + lo_mean) / 2
    mog = (hi_mean - lo_mean) / mid * 100 if mid != 0 else float("nan")

    p, m = _matched_pair_values(clean, hi_var, lo_var, value_col, slot_cols)
    mog_lo_ci, mog_hi_ci = bootstrap_pair_ci(
        p, m, seed_str=f"{seed_prefix}:mog:{hi_var}:{lo_var}",
        statistic=cpg_stat,
    ) if len(p) > 0 else (float("nan"), float("nan"))

    rrb = rank_biserial(p, m) if len(p) > 0 else float("nan")

    return {
        "highest_variant": hi_var,
        "highest_mean":    round(hi_mean, 4),
        "lowest_variant":  lo_var,
        "lowest_mean":     round(lo_mean, 4),
        "mog_pct":         round(mog, 2),
        "mog_ci_lower":    mog_lo_ci,
        "mog_ci_upper":    mog_hi_ci,
        "r_rb_mog":        round(rrb, 3) if not np.isnan(rrb) else float("nan"),
        "n_pairs_mog":     int(len(p)),
    }
