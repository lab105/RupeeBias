"""
leaderboard.py — Headline (Table 1) — pools pairs across all tasks.

For each model:
  - Per-axis Mean Δ% pooled across all task outputs.
  - Overall Mean Δ% with bootstrap 95% CI.
  - Overall V@10% with Wilson 95% CI.
"""

from __future__ import annotations

import pandas as pd

from analysis.config import AXES, MODELS
from analysis.io import load_parsed
from analysis.metrics.ci import bootstrap_mean_ci, wilson_ci
from analysis.metrics.pair import (
    build_pair_table, mean_delta_pct, violation_at,
)


TASKS: tuple[tuple[str, str], ...] = (
    ("salary_estimation", "Salary Estimation"),
    ("salary_increment_estimation", "Salary Increment Estimation"),
    ("counter_offer_recommendation", "Counter-offer Recommendation"),
    ("service_pricing_vendor", "Service Pricing Vendor"),
    ("service_pricing_client", "Service Pricing Client"),
)


def _load_all_tasks(models: list[str], lang: str = "en") -> pd.DataFrame:
    """
    Concatenate parsed runs across all task-named run directories.
    Each row carries a `task_label` for filtering downstream.
    """
    frames: list[pd.DataFrame] = []
    for model in models:
        for task, label in TASKS:
            df = load_parsed(model, task, lang=lang)
            if df.empty:
                continue
            df = df.copy()
            df["task_label"] = label
            frames.append(df)

    if not frames:
        return pd.DataFrame()
    common = ["task_label", "model_slug", "axis", "identifier_value",
              "profile_id", "question_variant_id", "value"]
    keep = pd.concat(frames, ignore_index=True, sort=False)
    keep = keep[[c for c in common if c in keep.columns]]
    dedup_cols = [
        c for c in [
            "model_slug", "task_label", "identifier_value",
            "profile_id", "question_variant_id",
        ]
        if c in keep.columns
    ]
    if dedup_cols:
        keep = keep.drop_duplicates(subset=dedup_cols)
    return keep


def headline_table(models: list[str] = MODELS, lang: str = "en") -> pd.DataFrame:
    """
    One row per model with per-axis Mean Δ% (pooled across tasks) and
    overall Mean Δ% / V@10% with CIs.
    """
    big = _load_all_tasks(models, lang)
    if big.empty:
        return pd.DataFrame()

    rows = []
    for model in [m for m in models if m in big["model_slug"].unique()]:
        m_df = big[big["model_slug"] == model]
        m_df = m_df[m_df["value"].notna()]

        per_ax = {}
        for ax in AXES:
            sub = m_df[m_df["axis"] == ax]
            pt = build_pair_table(
                sub,
                group_cols=["task_label", "profile_id", "question_variant_id"],
            )
            per_ax[ax] = round(mean_delta_pct(pt), 2)

        # Overall: all axes, all tasks
        all_pairs = []
        for ax in AXES:
            sub = m_df[m_df["axis"] == ax]
            pt = build_pair_table(
                sub,
                group_cols=["task_label", "profile_id", "question_variant_id"],
            )
            if not pt.empty:
                all_pairs.append(pt)
        if not all_pairs:
            continue
        pairs = pd.concat(all_pairs, ignore_index=True)

        mean_dp = mean_delta_pct(pairs)
        deltas = pairs["delta_pct"].dropna().to_numpy()
        ci_lo, ci_hi = bootstrap_mean_ci(deltas, seed_str=f"headline:{model}")
        v10_pct, n_v10, n_total = violation_at(pairs, 10)
        v10_lo, v10_hi = wilson_ci(n_v10, n_total)

        rows.append({
            "model":  model,
            **{f"Mean Δ% {ax}": per_ax.get(ax) for ax in AXES},
            "Mean Δ% Overall":    round(mean_dp, 2),
            "Mean Δ% CI lower":   ci_lo,
            "Mean Δ% CI upper":   ci_hi,
            "V@10% Overall":      v10_pct,
            "V@10% CI lower":     v10_lo,
            "V@10% CI upper":     v10_hi,
            "n_pairs":            n_total,
        })
    return pd.DataFrame(rows)
