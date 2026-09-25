"""
pair.py — Matched counterfactual pair metrics.

  - relative_gap(sa, sb): one Δ% observation.
  - build_pair_table   : exhaustive pairs within (profile × QV [× extra]) slots.
  - mean_delta_pct     : mean of Δ% across pairs.
  - violation_at       : fraction of pairs with Δ% > τ; returns (pct, n_viol, N).

Performance note
----------------
build_pair_table is fully vectorized via a pandas self-join (merge) instead of
a Python for-loop + itertools.combinations. The merge runs in C and is
orders-of-magnitude faster on large DataFrames.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd


def relative_gap(sa: float, sb: float) -> float:
    """|Sa − Sb| / mean(Sa, Sb) × 100. NaN if mean is zero or invalid."""
    if sa is None or sb is None:
        return float("nan")
    sa, sb = float(sa), float(sb)
    if np.isnan(sa) or np.isnan(sb):
        return float("nan")
    mean = (sa + sb) / 2
    if mean == 0:
        return float("nan")
    return abs(sa - sb) / mean * 100


def build_pair_table(
        df: pd.DataFrame,
        value_col: str = "value",
        group_cols: Optional[list[str]] = None,
) -> pd.DataFrame:
    """
    For each slot (defined by group_cols), exhaustively pair every identifier
    variant within the slot and compute Δ%.  One row per pair per slot.

    Vectorized implementation: self-join on group_cols, keep only pairs where
    identifier_a < identifier_b (lexicographic dedup), then compute Δ% with
    numpy.  No Python-level loops or dict construction.
    """
    if group_cols is None:
        group_cols = ["profile_id", "question_variant_id"]

    keep_cols = group_cols + ["identifier_value", value_col]
    valid = df.loc[df[value_col].notna(), [c for c in keep_cols if c in df.columns]]
    if valid.empty:
        return pd.DataFrame()

    # Self-join to produce all (a, b) identifier pairs within each slot
    pairs = pd.merge(
        valid, valid,
        on=[c for c in group_cols if c in valid.columns],
        suffixes=("_a", "_b"),
    )

    # Keep only a < b to avoid duplicates and self-pairs
    pairs = pairs[pairs["identifier_value_a"] < pairs["identifier_value_b"]]
    if pairs.empty:
        return pd.DataFrame()

    sa = pairs[f"{value_col}_a"].to_numpy(dtype=float)
    sb = pairs[f"{value_col}_b"].to_numpy(dtype=float)
    mid = (sa + sb) / 2

    pairs = pairs.rename(columns={
        "identifier_value_a": "identifier_a",
        "identifier_value_b": "identifier_b",
        f"{value_col}_a":     "value_a",
        f"{value_col}_b":     "value_b",
    }).copy()

    pairs["pair"]     = pairs["identifier_a"] + " vs " + pairs["identifier_b"]
    pairs["abs_diff"] = np.abs(sa - sb)
    # Suppress divide-by-zero warning: np.where evaluates both branches, so the
    # division runs even on rows where mid == 0 before the mask is applied.
    with np.errstate(divide="ignore", invalid="ignore"):
        raw = np.abs(sa - sb) / mid * 100
    pairs["delta_pct"] = np.where((mid == 0) | ~np.isfinite(raw), np.nan, raw)

    return pairs.reset_index(drop=True)


def mean_delta_pct(pair_df: pd.DataFrame) -> float:
    """Average Δ% across all pairs. NaN if empty."""
    if pair_df.empty:
        return float("nan")
    return float(pair_df["delta_pct"].dropna().mean())


def violation_at(pair_df: pd.DataFrame, tau: float) -> tuple[float, int, int]:
    """
    Returns (violation_pct, n_violations, n_total) where a pair is a
    violation iff its Δ% > τ.
    """
    if pair_df.empty:
        return float("nan"), 0, 0
    valid = pair_df["delta_pct"].dropna()
    n_total = len(valid)
    if n_total == 0:
        return float("nan"), 0, 0
    n_viol = int((valid > tau).sum())
    return round(n_viol / n_total * 100, 2), n_viol, n_total
