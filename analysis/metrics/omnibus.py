"""
omnibus.py — Omnibus tests across all variants within an axis.

  - mean_center_per_model : remove per-model baseline before pooling.
  - kruskal_wallis        : KW H, p, df, ε² (effect size).
  - friedman              : Friedman χ², p, df, Kendall's W (effect size).
                            Friedman is the primary omnibus per spec; KW is
                            kept for the appendix.

Friedman strategy (per the user's brief):
  Build a (profile_id × identifier_value) matrix where each cell is the
  mean recommendation across all models (after per-model mean-centering)
  for that variant at that profile, averaged over QV and language. Run
  Friedman across columns (variants) with profiles as blocks.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats


# ---------------------------------------------------------------------------
# Mean-centering
# ---------------------------------------------------------------------------


def mean_center_per_model(
        df: pd.DataFrame,
        value_col: str = "value",
        model_col: str = "model_slug",
) -> pd.DataFrame:
    """
    Subtract each model's per-model mean from `value_col` and store in
    `value_centered`. Returns a copy.
    """
    out = df.copy()
    if model_col not in out.columns:
        out["value_centered"] = out[value_col]
        return out
    means = out.groupby(model_col)[value_col].transform("mean")
    out["value_centered"] = out[value_col] - means
    return out


def _eps_squared(H: float, k: int, N: int) -> float:
    if N <= k or N == 0:
        return float("nan")
    return (H - k + 1) / (N - k)


def _magnitude(eps2: float) -> str:
    if np.isnan(eps2):
        return "n/a"
    if eps2 < 0.01:
        return "negligible"
    if eps2 < 0.06:
        return "small"
    if eps2 < 0.14:
        return "moderate"
    return "large"


# ---------------------------------------------------------------------------
# Kruskal-Wallis
# ---------------------------------------------------------------------------


def kruskal_wallis(
        df: pd.DataFrame,
        value_col: str = "value",
        group_col: str = "identifier_value",
) -> dict:
    """KW omnibus across all variants on `value_col`."""
    groups = [
        g[value_col].dropna().to_numpy()
        for _, g in df.groupby(group_col, sort=False)
        if g[value_col].notna().any()
    ]
    if len(groups) < 2:
        return {"H": float("nan"), "p": float("nan"), "df": float("nan"),
                "eps2": float("nan"), "k": len(groups), "N": 0,
                "magnitude": "n/a"}
    H, p = stats.kruskal(*groups)
    k = len(groups)
    N = sum(len(g) for g in groups)
    eps2 = _eps_squared(H, k, N)
    return {
        "H":         round(float(H), 3),
        "p":         round(float(p), 6),
        "df":        k - 1,
        "eps2":      round(eps2, 4),
        "k":         k,
        "N":         N,
        "magnitude": _magnitude(eps2),
    }


# ---------------------------------------------------------------------------
# Friedman (primary omnibus)
# ---------------------------------------------------------------------------


def _build_friedman_matrix(
        df: pd.DataFrame,
        value_col: str = "value_centered",
        block_col: str = "profile_id",
        treatment_col: str = "identifier_value",
        model_col: Optional[str] = "model_slug",
) -> pd.DataFrame:
    """
    Build a (block × treatment) matrix. Cell value = mean across the model
    column (and any other columns that aren't block/treatment), averaging
    over QVs/languages.

    Per the brief, take the mean of model outputs for each variant × profile
    cell after per-model mean-centering — exactly one value per cell.
    """
    if value_col not in df.columns:
        return pd.DataFrame()
    if block_col not in df.columns or treatment_col not in df.columns:
        return pd.DataFrame()
    matrix = (
        df.groupby([block_col, treatment_col])[value_col]
        .mean()
        .unstack(treatment_col)
    )
    # Drop blocks with any NaN — Friedman requires complete blocks.
    return matrix.dropna(axis=0, how="any")


def friedman(
        df: pd.DataFrame,
        value_col: str = "value",
        block_col: str = "profile_id",
        treatment_col: str = "identifier_value",
        model_col: Optional[str] = "model_slug",
) -> dict:
    """
    Friedman omnibus across all variants. `df` should already be
    mean-centered per model (use mean_center_per_model + value_col='value_centered').
    """
    matrix = _build_friedman_matrix(df, value_col, block_col, treatment_col, model_col)
    if matrix.shape[0] < 2 or matrix.shape[1] < 2:
        return {"chi2": float("nan"), "p": float("nan"), "df": float("nan"),
                "W": float("nan"), "k": matrix.shape[1] if matrix.size else 0,
                "n_blocks": matrix.shape[0] if matrix.size else 0,
                "magnitude": "n/a"}

    chi2, p = stats.friedmanchisquare(*[matrix[c].to_numpy() for c in matrix.columns])
    n = matrix.shape[0]      # blocks
    k = matrix.shape[1]      # treatments
    # Kendall's W relates to chi² as W = chi² / (n × (k − 1))
    W = float(chi2 / (n * (k - 1))) if n * (k - 1) > 0 else float("nan")
    # ε²-equivalent magnitude band, repurposing the same thresholds for W.
    return {
        "chi2":      round(float(chi2), 3),
        "p":         round(float(p), 6),
        "df":        k - 1,
        "W":         round(W, 4),
        "k":         k,
        "n_blocks":  n,
        "magnitude": _magnitude(W),
    }
