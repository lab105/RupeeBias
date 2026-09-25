"""
ci.py — Confidence-interval helpers.

  - _rng(seed_str)          : deterministic RNG keyed off a string. Resampling
                              ordering is robust to call-order changes.
  - wilson_ci               : closed-form CI for a proportion.
  - bootstrap_mean_ci       : generic bootstrap on a 1-D array.
  - bootstrap_pair_ci       : bootstrap on matched-pair (priv, marg) values.
  - bootstrap_paired_diff_ci: CI on a paired difference (used for ASR Gap, LRG Gap).
"""

from __future__ import annotations

from typing import Callable

import numpy as np
from scipy import stats

from analysis.config import ALPHA, N_BOOT


def _rng(seed_str: str) -> np.random.Generator:
    """Deterministic RNG keyed on a string."""
    seed = int(abs(hash(seed_str)) % (2**31))
    return np.random.default_rng(seed)


def wilson_ci(n_success: int, n_total: int, alpha: float = ALPHA) -> tuple[float, float]:
    """Wilson score interval, returned as percentages (0–100)."""
    if n_total == 0:
        return float("nan"), float("nan")
    z = stats.norm.ppf(1 - alpha / 2)
    p = n_success / n_total
    denom = 1 + z**2 / n_total
    centre = (p + z**2 / (2 * n_total)) / denom
    half = z * np.sqrt(p * (1 - p) / n_total + z**2 / (4 * n_total**2)) / denom
    return round((centre - half) * 100, 2), round((centre + half) * 100, 2)


def bootstrap_mean_ci(
        values: np.ndarray,
        seed_str: str,
        n_boot: int = N_BOOT,
        alpha: float = ALPHA,
) -> tuple[float, float]:
    """Percentile bootstrap CI on the mean of `values`."""
    arr = np.asarray(values)
    arr = arr[~np.isnan(arr)]
    if len(arr) < 2:
        return float("nan"), float("nan")
    rng = _rng(seed_str)
    idx = rng.integers(0, len(arr), size=(n_boot, len(arr)))
    means = arr[idx].mean(axis=1)
    lo, hi = np.percentile(means, [alpha / 2 * 100, (1 - alpha / 2) * 100])
    return round(float(lo), 2), round(float(hi), 2)


def bootstrap_pair_ci(
        priv_values: np.ndarray,
        marg_values: np.ndarray,
        seed_str: str,
        statistic: Callable[[np.ndarray, np.ndarray], float],
        n_boot: int = N_BOOT,
        alpha: float = ALPHA,
) -> tuple[float, float]:
    """
    Bootstrap CI on a paired statistic. Both arrays must be the same length;
    each index is one matched slot. Resamples slots with replacement.
    """
    p = np.asarray(priv_values, dtype=float)
    m = np.asarray(marg_values, dtype=float)
    mask = ~(np.isnan(p) | np.isnan(m))
    p, m = p[mask], m[mask]
    if len(p) < 2:
        return float("nan"), float("nan")
    rng = _rng(seed_str)
    boots = []
    for _ in range(n_boot):
        idx = rng.integers(0, len(p), size=len(p))
        try:
            boots.append(statistic(p[idx], m[idx]))
        except Exception:
            continue
    if len(boots) < n_boot // 2:
        return float("nan"), float("nan")
    lo, hi = np.percentile(boots, [alpha / 2 * 100, (1 - alpha / 2) * 100])
    return round(float(lo), 2), round(float(hi), 2)


def bootstrap_unmatched_ci(
        priv_values: np.ndarray,
        marg_values: np.ndarray,
        seed_str: str,
        statistic: Callable[[np.ndarray, np.ndarray], float],
        n_boot: int = N_BOOT,
        alpha: float = ALPHA,
) -> tuple[float, float]:
    """
    Bootstrap CI for a statistic on two independent (unmatched) samples.
    Resamples each group independently with replacement.
    """
    p = np.asarray(priv_values, dtype=float)
    m = np.asarray(marg_values, dtype=float)
    p, m = p[~np.isnan(p)], m[~np.isnan(m)]
    if len(p) < 2 or len(m) < 2:
        return float("nan"), float("nan")
    rng = _rng(seed_str)
    boots = []
    for _ in range(n_boot):
        p_boot = p[rng.integers(0, len(p), size=len(p))]
        m_boot = m[rng.integers(0, len(m), size=len(m))]
        try:
            boots.append(statistic(p_boot, m_boot))
        except Exception:
            continue
    if len(boots) < n_boot // 2:
        return float("nan"), float("nan")
    lo, hi = np.percentile(boots, [alpha / 2 * 100, (1 - alpha / 2) * 100])
    return round(float(lo), 2), round(float(hi), 2)


def bootstrap_diff_ci(
        a_values: np.ndarray,
        b_values: np.ndarray,
        seed_str: str,
        n_boot: int = N_BOOT,
        alpha: float = ALPHA,
) -> tuple[float, float]:
    """CI on (mean(a) - mean(b)) via paired bootstrap of indices."""
    return bootstrap_pair_ci(
        a_values, b_values, seed_str,
        statistic=lambda x, y: x.mean() - y.mean(),
        n_boot=n_boot, alpha=alpha,
    )
