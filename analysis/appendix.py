"""
appendix.py — Robustness checks: QV, language, implicit, fairness.

  - qv_robustness        : Spearman ρ + ICC across Q1/Q2/Q3 per axis.
  - language_moderation  : ρ EN vs Hinglish + Δ Mean Δ%.
  - implicit_vs_explicit : salary_estimation only — implicit-name comparison.
  - fairness_vs_baseline : salary_estimation only — fairness-instructed comparison.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy import stats

from analysis.config import AXES, MODELS
from analysis.io import load_parsed
from analysis.metrics.pair import build_pair_table, mean_delta_pct, violation_at

SALARY_TASK = "salary_estimation"


# ---------------------------------------------------------------------------
# A.1 — QV robustness
# ---------------------------------------------------------------------------


def _icc_2_1(matrix: np.ndarray) -> float:
    """ICC(2,1) — two-way random effects, single rater. matrix: rows=subjects, cols=raters."""
    matrix = np.asarray(matrix, dtype=float)
    n, k = matrix.shape
    if n < 2 or k < 2:
        return float("nan")
    grand = matrix.mean()
    row_means = matrix.mean(axis=1)
    col_means = matrix.mean(axis=0)
    SS_total = ((matrix - grand) ** 2).sum()
    SS_rows  = k * ((row_means - grand) ** 2).sum()
    SS_cols  = n * ((col_means - grand) ** 2).sum()
    SS_err   = SS_total - SS_rows - SS_cols
    MS_rows  = SS_rows  / (n - 1)
    MS_cols  = SS_cols  / (k - 1)
    MS_err   = SS_err   / ((n - 1) * (k - 1)) if (n - 1) * (k - 1) > 0 else float("nan")
    denom = MS_rows + (k - 1) * MS_err + k * (MS_cols - MS_err) / n
    if denom <= 0:
        return float("nan")
    return float((MS_rows - MS_err) / denom)


def _load_task(models: list[str], task: str, lang: str = "en") -> pd.DataFrame:
    frames = [load_parsed(model, task, lang=lang) for model in models]
    frames = [df for df in frames if not df.empty]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def qv_robustness(task: str, lang: str = "en",
                  models: list[str] = MODELS) -> pd.DataFrame:
    """Spearman ρ + ICC across Q1/Q2/Q3 per axis, plus Δ Mean Δ%."""
    df = _load_task(models, task, lang=lang)
    if df.empty:
        return pd.DataFrame()

    rows = []
    for ax in AXES:
        sub = df[df["axis"] == ax]
        if sub.empty:
            continue

        # Per-QV mean per variant
        wide = (
            sub.groupby(["question_variant_id", "identifier_value"])["value"]
            .mean()
            .unstack("question_variant_id")
        )
        if wide.shape[1] < 2:
            continue
        wide = wide.dropna(axis=0, how="any")
        if wide.empty:
            continue

        # Pairwise Spearman ρ
        qs = sorted(wide.columns)
        rhos = {}
        for i, q1 in enumerate(qs):
            for q2 in qs[i + 1:]:
                rho, _ = stats.spearmanr(wide[q1].rank().values, wide[q2].rank().values)
                rhos[f"ρ {q1}/{q2}"] = round(float(rho), 3)
        min_rho = min(rhos.values()) if rhos else float("nan")

        # ICC across QVs
        icc = round(_icc_2_1(wide.values), 3)

        # Mean Δ% per QV
        per_qv = {}
        for q in qs:
            sub_q = sub[sub["question_variant_id"] == q]
            pt = build_pair_table(sub_q, group_cols=["profile_id"])
            per_qv[q] = round(mean_delta_pct(pt), 2)
        delta_mdp = (max(per_qv.values()) - min(per_qv.values())) if per_qv else float("nan")

        interp = "stable" if min_rho >= 0.85 and icc >= 0.75 else "unstable"

        row = {"axis": ax, "k": wide.shape[0]}
        row.update({f"Mean Δ% {q}": per_qv.get(q) for q in qs})
        row.update({"Δ Mean Δ%": round(delta_mdp, 2), **rhos,
                    "min ρ": round(min_rho, 3), "ICC": icc,
                    "interpretation": interp})
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# A.2 — Language moderation
# ---------------------------------------------------------------------------


def language_moderation(task: str, models: list[str] = MODELS) -> pd.DataFrame:
    df_en = _load_task(models, task, lang="en")
    df_hi = _load_task(models, task, lang="hinglish")
    if df_en.empty or df_hi.empty:
        return pd.DataFrame()

    rows = []
    for ax in AXES:
        sub_en = df_en[df_en["axis"] == ax]
        sub_hi = df_hi[df_hi["axis"] == ax]
        if sub_en.empty or sub_hi.empty:
            continue

        en_means = sub_en.groupby("identifier_value")["value"].mean()
        hi_means = sub_hi.groupby("identifier_value")["value"].mean()
        common = sorted(set(en_means.index) & set(hi_means.index))
        if len(common) < 3:
            continue
        rho, _ = stats.spearmanr(en_means[common].rank().values,
                                  hi_means[common].rank().values)

        en_mdp = round(mean_delta_pct(build_pair_table(sub_en)), 2)
        hi_mdp = round(mean_delta_pct(build_pair_table(sub_hi)), 2)

        rows.append({
            "axis": ax,
            "Mean Δ% EN":      en_mdp,
            "Mean Δ% Hinglish": hi_mdp,
            "Δ Mean Δ%":       round(hi_mdp - en_mdp, 2),
            "ρ EN/Hinglish":   round(float(rho), 3),
            "interpretation":  "stable" if rho >= 0.85 else "unstable",
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Appendix B — Implicit identifier (salary_estimation only)
# ---------------------------------------------------------------------------


_SIGNAL_TO_AXIS = {
    "caste":     "Caste",
    "religion":  "Religion",
    "gender":    "Gender",
    "region":    "Region",
}


def _explode_implicit(df: pd.DataFrame) -> pd.DataFrame:
    """
    Implicit-name files store demographic identity in a `signals` dict instead
    of explicit `axis`/`identifier_value` columns. Expand one row → one row
    per (axis, identifier_value) so pair analysis works per axis.
    """
    if df is None or df.empty:
        return df
    if "axis" in df.columns and "identifier_value" in df.columns:
        return df  # explicit shape; nothing to do
    if "signals" not in df.columns:
        return pd.DataFrame()

    rows = []
    for _, row in df.iterrows():
        sigs = row.get("signals") or {}
        if not isinstance(sigs, dict):
            continue
        for sig_key, axis in _SIGNAL_TO_AXIS.items():
            iv = sigs.get(sig_key)
            if iv is None:
                continue
            new_row = row.to_dict()
            new_row["axis"] = axis
            new_row["identifier_value"] = iv
            rows.append(new_row)
    return pd.DataFrame(rows)


def _mean_dp_v10(df: pd.DataFrame) -> tuple[float, float]:
    df = _explode_implicit(df)
    if df is None or df.empty or "axis" not in df.columns:
        return float("nan"), float("nan")
    df = df[df["value"].notna()]
    pairs = []
    for ax in df["axis"].dropna().unique():
        pt = build_pair_table(df[df["axis"] == ax])
        if not pt.empty:
            pairs.append(pt)
    if not pairs:
        return float("nan"), float("nan")
    pt = pd.concat(pairs, ignore_index=True)
    mean_dp = mean_delta_pct(pt)
    v10, _, _ = violation_at(pt, 10)
    return round(mean_dp, 2), v10


def implicit_vs_explicit(models: list[str] = MODELS, lang: str = "en") -> pd.DataFrame:
    rows = []
    for m in models:
        df_e = load_parsed(m, SALARY_TASK, lang=lang, implicit=False)
        df_i = load_parsed(m, SALARY_TASK, lang=lang, implicit=True)
        if df_e.empty or df_i.empty:
            continue
        e_dp, e_v10 = _mean_dp_v10(df_e)
        i_dp, i_v10 = _mean_dp_v10(df_i)
        rows.append({
            "model":            m,
            "Mean Δ% Explicit": e_dp,
            "Mean Δ% Implicit": i_dp,
            "Δ Mean Δ%":        round((i_dp - e_dp), 2) if not np.isnan(i_dp) else float("nan"),
            "V@10% Explicit":   e_v10,
            "V@10% Implicit":   i_v10,
        })
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Appendix C — Fairness instruction (salary_estimation only)
# ---------------------------------------------------------------------------


def fairness_vs_baseline(models: list[str] = MODELS, lang: str = "en") -> pd.DataFrame:
    rows = []
    for m in models:
        df_b = load_parsed(m, SALARY_TASK, lang=lang, fairness=False)
        df_f = load_parsed(m, SALARY_TASK, lang=lang, fairness=True)
        if df_b.empty or df_f.empty:
            continue
        b_dp, b_v10 = _mean_dp_v10(df_b)
        f_dp, f_v10 = _mean_dp_v10(df_f)
        rows.append({
            "model":             m,
            "Mean Δ% Baseline":  b_dp,
            "Mean Δ% Fair":      f_dp,
            "Δ Mean Δ%":         round((f_dp - b_dp), 2) if not np.isnan(f_dp) else float("nan"),
            "V@10% Baseline":    b_v10,
            "V@10% Fair":        f_v10,
        })
    return pd.DataFrame(rows)
