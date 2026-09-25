"""
asr.py — Achievement Sensitivity Ratio for salary_increment_estimation.

  - asr_per_variant_profile : DataFrame with one row per (variant × profile)
                              giving Strong−Weak hike. Used as the unit for
                              omnibus tests (Friedman/KW) within an axis.
  - asr_per_variant         : mean ASR per variant, averaged across profiles.
  - asr_canonical_pair      : ASR Gap = ASR(priv) − ASR(marg) with bootstrap CI.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from analysis.metrics.ci import bootstrap_pair_ci
from analysis.metrics.canonical import _matched_pair_values  # reuse


HIKE_COL = "hike_pct"


def _strong_minus_weak(g: pd.DataFrame) -> float:
    s = g.loc[g["achievement_level"] == "Strong", HIKE_COL].mean()
    w = g.loc[g["achievement_level"] == "Weak",   HIKE_COL].mean()
    if np.isnan(s) or np.isnan(w):
        return np.nan
    return float(s - w)


def asr_per_variant_profile(df: pd.DataFrame) -> pd.DataFrame:
    """
    For each (identifier_value, company, experience_years), compute
    Strong − Weak mean hike. Each (company, exp) pair is one ASR observation;
    9 per variant given 3 companies × 3 experience levels.

    Returns columns: identifier_value, profile_id (synthetic = company-exp), asr.
    """
    if df is None or df.empty or "achievement_level" not in df.columns:
        return pd.DataFrame()
    block_cols = ["company", "experience_years"]
    if not all(c in df.columns for c in block_cols):
        return pd.DataFrame()

    grouped = df.groupby(["identifier_value"] + block_cols)
    rows = []
    for (iv, comp, exp), g in grouped:
        rows.append({
            "identifier_value": iv,
            "profile_id":       f"{comp}-{exp}y",   # synthetic block id
            "asr":              _strong_minus_weak(g),
        })
    return pd.DataFrame(rows).dropna(subset=["asr"])


def asr_per_variant(asr_pp: pd.DataFrame) -> pd.Series:
    """Average ASR across profiles for each variant."""
    if asr_pp.empty:
        return pd.Series(dtype=float)
    return asr_pp.groupby("identifier_value")["asr"].mean()


def asr_canonical_pair(
        asr_pp: pd.DataFrame,
        priv: str,
        marg: str,
        seed_str: str = "asr_gap",
) -> dict:
    """
    ASR Gap = ASR(priv) − ASR(marg), with paired-profile bootstrap CI.
    """
    if asr_pp.empty:
        return {}

    # Wide table: profile_id × variant
    wide = (
        asr_pp.set_index(["profile_id", "identifier_value"])["asr"]
        .unstack("identifier_value")
    )
    if priv not in wide.columns or marg not in wide.columns:
        return {}

    paired = wide[[priv, marg]].dropna()
    if paired.empty:
        return {}

    p, m = paired[priv].to_numpy(), paired[marg].to_numpy()
    asr_p, asr_m = float(p.mean()), float(m.mean())
    gap = asr_p - asr_m

    lo, hi = bootstrap_pair_ci(
        p, m, seed_str=f"{seed_str}:{priv}:{marg}",
        statistic=lambda a, b: a.mean() - b.mean(),
    )

    return {
        "privileged":   priv,
        "marginalized": marg,
        "asr_priv":     round(asr_p, 2),
        "asr_marg":     round(asr_m, 2),
        "asr_gap":      round(gap, 2),
        "asr_gap_ci_lower": lo,
        "asr_gap_ci_upper": hi,
        "n_profiles":   int(len(paired)),
    }
