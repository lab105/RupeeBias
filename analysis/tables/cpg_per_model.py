"""
Canonical Pair Gap (CPG) tables — one per task, one column per model.

Cell format: CPG% / sign_consistency%
  Positive CPG = privileged variant recommended higher value.

Tasks produced: salary_estimation, salary_increment_estimation,
counter_offer_recommendation, service_pricing_vendor, service_pricing_client.
Aggregated across both languages (EN + Hinglish).
"""

from __future__ import annotations

import sys
from concurrent.futures import as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from analysis.config import CANONICAL_PAIRS
from analysis.io import load_parsed
from analysis.metrics.canonical import (
    _matched_pair_values, cpg_stat, sign_consistency,
)
from analysis.metrics.ci import bootstrap_unmatched_ci
from analysis.pool import POOL

MODELS = [
    "claude-haiku-4.5",
    "claude-opus-4.7",
    "deepseek-v3.2",
    "gemini-3-flash",
    "glm-5.1",
    "gpt-5.4",
    "gpt-5.4-mini",
    "kimi-k2.5",
    "sarvam-105b",
]

MODEL_DISPLAY = {
    "claude-haiku-4.5":  "Claude Haiku 4.5",
    "claude-opus-4.7":   "Claude Opus 4.7",
    "deepseek-v3.2":   "DeepSeek V3.2",
    "gemini-3-flash":    "Gemini 3 Flash",
    "glm-5.1":           "GLM 5.1",
    "gpt-5.4":           "GPT 5.4",
    "gpt-5.4-mini":      "GPT 5.4-mini",
    "kimi-k2.5":         "Kimi K2.5",
    "sarvam-105b":       "Sarvam 105B",
}

AXES = list(CANONICAL_PAIRS.keys())
LANGS = ["en", "hinglish"]

OUT_DIR = ROOT / "paper_analysis" / "tables"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TASKS = [
    ("salary_estimation",            "figure_07_cpg_salary_estimation.csv"),
    ("salary_increment_estimation",  "figure_07_cpg_salary_increment_estimation.csv"),
    ("counter_offer_recommendation", "figure_07_cpg_counter_offer_recommendation.csv"),
    ("service_pricing_vendor",       "figure_07_cpg_service_pricing_vendor.csv"),
    ("service_pricing_client",       "figure_07_cpg_service_pricing_client.csv"),
]


def cell_stats_from_frames(df_en: pd.DataFrame, df_hi: pd.DataFrame, axis: str,
                           model: str, task: str
                           ) -> tuple[float, float, float, float]:
    """CPG%, sign_consistency%, ci_lower, ci_upper — both languages pooled (pre-loaded DFs)."""
    frames = [df for df in (df_en, df_hi) if not df.empty]
    if not frames:
        return np.nan, np.nan, np.nan, np.nan

    df_all = pd.concat(frames, ignore_index=True)
    sub = df_all[df_all["axis"] == axis]
    if sub.empty:
        return np.nan, np.nan, np.nan, np.nan

    priv, marg = CANONICAL_PAIRS[axis]
    clean = sub[sub["value"].notna()]
    p_all = clean[clean["identifier_value"] == priv]["value"].to_numpy()
    m_all = clean[clean["identifier_value"] == marg]["value"].to_numpy()
    if len(p_all) == 0 or len(m_all) == 0:
        return np.nan, np.nan, np.nan, np.nan

    cpg = cpg_stat(p_all, m_all)
    lo, hi = bootstrap_unmatched_ci(
        p_all, m_all,
        seed_str=f"cpg:{model}:{task}:{axis}",
        statistic=cpg_stat,
    )

    slot_cols = [c for c in ["profile_id", "question_variant_id", "lang"] if c in sub.columns]
    p, m = _matched_pair_values(sub, priv, marg, slot_cols=slot_cols)
    sc = sign_consistency(p, m) if len(p) > 0 else np.nan
    return cpg, sc, lo, hi


# Keep original signature for any external callers
def cell_stats(model: str, task: str, axis: str
               ) -> tuple[float, float, float, float]:
    """CPG%, sign_consistency%, ci_lower, ci_upper — both languages pooled."""
    df_en = load_parsed(model, task, lang="en")
    df_hi = load_parsed(model, task, lang="hinglish")
    return cell_stats_from_frames(df_en, df_hi, axis, model, task)


def build_table(task: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (main_df, ci_df). Pre-loads DFs once per (model,task); fans out (axis,model)."""
    # Pre-load both lang DFs once per model
    model_dfs: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for model in MODELS:
        model_dfs[model] = (
            load_parsed(model, task, lang="en"),
            load_parsed(model, task, lang="hinglish"),
        )

    def _worker(axis: str, model: str) -> tuple[str, str, float, float, float, float]:
        df_en, df_hi = model_dfs[model]
        cpg, sc, lo, hi = cell_stats_from_frames(df_en, df_hi, axis, model, task)
        return axis, model, cpg, sc, lo, hi

    pairs = [(axis, model) for axis in AXES for model in MODELS]
    cell_results: dict[tuple[str, str], tuple[float, float, float, float]] = {}
    futures = {POOL.submit(_worker, axis, model): (axis, model)
               for axis, model in pairs}
    for fut in as_completed(futures):
        axis, model, cpg, sc, lo, hi = fut.result()
        cell_results[(axis, model)] = (cpg, sc, lo, hi)

    main_rows, ci_rows = [], []
    for axis in AXES:
        priv, marg = CANONICAL_PAIRS[axis]
        main_row: dict = {"Canonical Pair": f"{priv} vs {marg}"}
        ci_row:   dict = {"Canonical Pair": f"{priv} vs {marg}"}
        for model in MODELS:
            cpg, sc, lo, hi = cell_results[(axis, model)]
            col = MODEL_DISPLAY[model]
            if np.isnan(cpg):
                main_row[col] = "—"
                ci_row[col]   = "—"
            else:
                sign = "+" if cpg >= 0 else ""
                main_row[col] = f"{sign}{cpg:.1f}% / {sc:.0f}%"
                ci_row[col]   = f"{lo:.2f} / {hi:.2f}" if not np.isnan(lo) else "—"
        main_rows.append(main_row)
        ci_rows.append(ci_row)
    return pd.DataFrame(main_rows), pd.DataFrame(ci_rows)


def main() -> None:
    for task, fname in TASKS:
        print(f"\n{'='*60}")
        print(f"  {task}")
        print(f"{'='*60}")
        df, ci_df = build_table(task)
        print(df.to_string(index=False))
        out_path = OUT_DIR / fname
        df.to_csv(out_path, index=False)
        ci_path = OUT_DIR / fname.replace(".csv", "_ci.csv")
        ci_df.to_csv(ci_path, index=False)
        print(f"\nSaved → {out_path}")
        print(f"Saved → {ci_path}")


if __name__ == "__main__":
    main()
