"""
Maximum Observed Gap (MOG) tables — one per task, one column per model.

For each (model, task, axis): pool both languages, compute mean value per identifier,
find the highest (most privileged) and lowest (least privileged) identifier,
report gap = (max_mean − min_mean) / midpoint × 100.

Cell format: gap% / top_identifier / bottom_identifier

Also saves _ci.csv files with bootstrap 95% CI on the gap%.
"""

from __future__ import annotations

import sys
from concurrent.futures import as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

from analysis.io import load_parsed
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

AXES = ["Religion", "Caste", "Region", "Gender", "Disability", "Urban/Rural"]
LANGS = ["en", "hinglish"]

OUT_DIR = ROOT / "paper_analysis" / "tables"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TASKS = [
    ("salary_estimation",            "figure_08_mog_salary_estimation.csv"),
    ("salary_increment_estimation",  "figure_08_mog_salary_increment_estimation.csv"),
    ("counter_offer_recommendation", "figure_08_mog_counter_offer_recommendation.csv"),
    ("service_pricing_vendor",       "figure_08_mog_service_pricing_vendor.csv"),
    ("service_pricing_client",       "figure_08_mog_service_pricing_client.csv"),
]

N_BOOT = 500
RNG    = np.random.default_rng(42)


def _mog_from_means(ident_means: "pd.Series") -> float:
    """Symmetric gap% from empirical highest vs lowest: (hi − lo) / midpoint × 100."""
    vmax = float(ident_means.max())
    vmin = float(ident_means.min())
    mid  = (vmax + vmin) / 2
    if mid == 0:
        return np.nan
    return (vmax - vmin) / mid * 100


def bootstrap_ci(sub: pd.DataFrame, n_boot: int = N_BOOT) -> tuple[float, float]:
    """95% bootstrap CI on MOG by resampling rows with replacement (vectorized)."""
    idents = sub["identifier_value"].values
    values = sub["value"].values
    n = len(values)

    # Encode identifiers as integer codes for fast bincount aggregation
    unique_ids, id_codes = np.unique(idents, return_inverse=True)
    n_ids = len(unique_ids)

    if n_ids < 2:
        return np.nan, np.nan

    rng = np.random.default_rng(42)
    boot_mogs = []
    for _ in range(n_boot):
        idx = rng.choice(n, size=n, replace=True)
        sampled_codes  = id_codes[idx]
        sampled_values = values[idx]
        counts = np.bincount(sampled_codes, minlength=n_ids).astype(float)
        if np.any(counts == 0):
            continue
        sums   = np.bincount(sampled_codes, weights=sampled_values, minlength=n_ids)
        means  = sums / counts
        vmax, vmin = means.max(), means.min()
        mid = (vmax + vmin) / 2
        if mid == 0:
            continue
        boot_mogs.append((vmax - vmin) / mid * 100)

    if len(boot_mogs) < 10:
        return np.nan, np.nan
    arr = np.array(boot_mogs)
    return float(np.percentile(arr, 2.5)), float(np.percentile(arr, 97.5))


def cell_mog_from_frames(df_en: pd.DataFrame, df_hi: pd.DataFrame, axis: str
                         ) -> tuple[float, str, str, float, float]:
    """Gap%, top id, bottom id, CI_lo, CI_hi — both languages pooled (pre-loaded DFs)."""
    frames = [df for df in (df_en, df_hi) if not df.empty]
    if not frames:
        return np.nan, "", "", np.nan, np.nan

    df_all = pd.concat(frames, ignore_index=True)
    sub = df_all[df_all["axis"] == axis]
    if sub.empty:
        return np.nan, "", "", np.nan, np.nan

    ident_means = sub.groupby("identifier_value")["value"].mean()
    if len(ident_means) < 2:
        return np.nan, "", "", np.nan, np.nan

    top  = str(ident_means.idxmax())
    bot  = str(ident_means.idxmin())
    gap  = _mog_from_means(ident_means)
    if np.isnan(gap):
        return np.nan, top, bot, np.nan, np.nan

    lo, hi = bootstrap_ci(sub)
    return gap, top, bot, lo, hi


# Keep original signature for any external callers
def cell_mog(model: str, task: str, axis: str
             ) -> tuple[float, str, str, float, float]:
    """Gap%, top id, bottom id, CI_lo, CI_hi — both languages pooled."""
    df_en = load_parsed(model, task, lang="en")
    df_hi = load_parsed(model, task, lang="hinglish")
    return cell_mog_from_frames(df_en, df_hi, axis)


def _axis_model_worker(axis: str, model: str, task: str
                       ) -> tuple[str, str, float, str, str, float, float]:
    """Worker: pre-load DFs outside caller, but axis-level is fast enough to inline."""
    df_en = load_parsed(model, task, lang="en")
    df_hi = load_parsed(model, task, lang="hinglish")
    gap, top, bot, lo, hi = cell_mog_from_frames(df_en, df_hi, axis)
    return axis, model, gap, top, bot, lo, hi


def build_table(task: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (gap_df, ci_df). Pre-loads DFs once per (model,task); fans out (axis,model)."""
    # Pre-load both lang DFs once per model
    model_dfs: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for model in MODELS:
        model_dfs[model] = (
            load_parsed(model, task, lang="en"),
            load_parsed(model, task, lang="hinglish"),
        )

    def _worker(axis: str, model: str) -> tuple[str, str, float, str, str, float, float]:
        df_en, df_hi = model_dfs[model]
        gap, top, bot, lo, hi = cell_mog_from_frames(df_en, df_hi, axis)
        return axis, model, gap, top, bot, lo, hi

    pairs = [(axis, model) for axis in AXES for model in MODELS]
    cell_results: dict[tuple[str, str], tuple[float, str, str, float, float]] = {}
    futures = {POOL.submit(_worker, axis, model): (axis, model)
               for axis, model in pairs}
    for fut in as_completed(futures):
        axis, model, gap, top, bot, lo, hi = fut.result()
        cell_results[(axis, model)] = (gap, top, bot, lo, hi)

    gap_rows = []
    ci_rows  = []
    for axis in AXES:
        gap_row: dict = {"Axis": axis}
        ci_row:  dict = {"Axis": axis}
        for model in MODELS:
            gap, top, bot, lo, hi = cell_results[(axis, model)]
            col = MODEL_DISPLAY[model]
            if np.isnan(gap):
                gap_row[col] = "—"
                ci_row[col]  = "—"
            else:
                gap_row[col] = f"{gap:.1f}% / {top} / {bot}"
                if not np.isnan(lo):
                    ci_row[col] = f"{lo:.1f} / {hi:.1f}"
                else:
                    ci_row[col] = "—"
        gap_rows.append(gap_row)
        ci_rows.append(ci_row)
    return pd.DataFrame(gap_rows), pd.DataFrame(ci_rows)


def main() -> None:
    for task, fname in TASKS:
        print(f"\n{'='*60}")
        print(f"  {task}")
        print(f"{'='*60}")

        gap_df, ci_df = build_table(task)
        print(gap_df.to_string(index=False))

        out_gap = OUT_DIR / fname
        gap_df.to_csv(out_gap, index=False)
        print(f"\nSaved → {out_gap}")

        ci_fname = fname.replace(".csv", "_ci.csv")
        out_ci   = OUT_DIR / ci_fname
        ci_df.to_csv(out_ci, index=False)
        print(f"Saved → {out_ci}")


if __name__ == "__main__":
    main()
