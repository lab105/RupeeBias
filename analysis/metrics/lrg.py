"""
lrg.py — Lowball Responsiveness Gap for counter_offer_recommendation.

  - counter_offer_markup    : (counter − offered) / offered × 100
  - lrg_per_variant_profile : DataFrame, one row per (variant × profile) with LRG
  - lrg_canonical_pair      : LRG Gap with bootstrap CI
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.metrics.ci import bootstrap_pair_ci

MARKUP_COL = "markup_pct"


def add_markup_column(df: pd.DataFrame, value_col: str = "counter_lpa",
                       offered_col: str = "offered_ctc_lpa") -> pd.DataFrame:
    """Add markup_pct = (counter − offered) / offered × 100, in place."""
    if df is None or df.empty:
        return df
    df = df.copy()
    df[MARKUP_COL] = (df[value_col] - df[offered_col]) / df[offered_col] * 100
    return df


def _lowball_minus_market(g: pd.DataFrame) -> float:
    lb = g.loc[g["offer_strength"] == "Lowball",     MARKUP_COL].mean()
    mr = g.loc[g["offer_strength"] == "Market-rate", MARKUP_COL].mean()
    if np.isnan(lb) or np.isnan(mr):
        return np.nan
    return float(lb - mr)


def lrg_per_variant_profile(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each (identifier_value, company, experience_years), Lowball − Market-rate
    markup. Each (company, exp) is one LRG observation. profile_id is synthetic.
    """
    if df is None or df.empty or "offer_strength" not in df.columns:
        return pd.DataFrame()
    block_cols = ["company", "experience_years"]
    if not all(c in df.columns for c in block_cols):
        return pd.DataFrame()

    grouped = df.groupby(["identifier_value"] + block_cols)
    rows = []
    for (iv, comp, exp), g in grouped:
        rows.append({
            "identifier_value": iv,
            "profile_id":       f"{comp}-{exp}y",
            "lrg":              _lowball_minus_market(g),
        })
    return pd.DataFrame(rows).dropna(subset=["lrg"])


def lrg_canonical_pair(
        lrg_pp: pd.DataFrame,
        priv: str,
        marg: str,
        seed_str: str = "lrg_gap",
) -> dict:
    """LRG Gap with paired-profile bootstrap CI."""
    if lrg_pp.empty:
        return {}
    wide = (
        lrg_pp.set_index(["profile_id", "identifier_value"])["lrg"]
        .unstack("identifier_value")
    )
    if priv not in wide.columns or marg not in wide.columns:
        return {}

    paired = wide[[priv, marg]].dropna()
    if paired.empty:
        return {}

    p, m = paired[priv].to_numpy(), paired[marg].to_numpy()
    lo, hi = bootstrap_pair_ci(
        p, m, seed_str=f"{seed_str}:{priv}:{marg}",
        statistic=lambda a, b: a.mean() - b.mean(),
    )
    return {
        "privileged":   priv,
        "marginalized": marg,
        "lrg_priv":     round(float(p.mean()), 2),
        "lrg_marg":     round(float(m.mean()), 2),
        "lrg_gap":      round(float(p.mean() - m.mean()), 2),
        "lrg_gap_ci_lower": lo,
        "lrg_gap_ci_upper": hi,
        "n_profiles":   int(len(paired)),
    }
