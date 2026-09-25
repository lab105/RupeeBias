"""
QV Robustness table — one row per model.

For each (model, axis, task, lang):
  Build a (identifier_value × question_variant_id) matrix.
  Compute all pairwise Spearman ρ across QVs → take the minimum.

Cell value = mean of min ρ across all (task, lang) combinations that had data.
✓  if mean min ρ ≥ 0.85, else blank.
Axis mean row appended at the bottom.
"""

from __future__ import annotations

import sys
from concurrent.futures import as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from scipy import stats

from analysis.config import AXES
from analysis.io import load_parsed
from analysis.metrics.ci import bootstrap_mean_ci
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


TASKS = [
    "salary_estimation",
    "salary_increment_estimation",
    "counter_offer_recommendation",
    "service_pricing_vendor",
    "service_pricing_client",
]

THRESHOLD = 0.85

OUT_DIR = ROOT / "paper_analysis" / "tables"
OUT_DIR.mkdir(parents=True, exist_ok=True)


def min_rho_for_axis(df: pd.DataFrame, axis: str) -> float:
    """Min pairwise Spearman ρ across QVs for a given axis."""
    sub = df[df["axis"] == axis]
    if sub.empty:
        return np.nan

    wide = (
        sub.groupby(["identifier_value", "question_variant_id"])["value"]
        .mean()
        .unstack("question_variant_id")
        .dropna(how="any")
    )
    if wide.shape[1] < 2 or wide.shape[0] < 3:
        return np.nan

    qs = sorted(wide.columns)
    rhos = []
    for i, q1 in enumerate(qs):
        for q2 in qs[i + 1:]:
            v1 = wide[q1].values
            v2 = wide[q2].values
            # Skip constant columns — Spearman ρ is undefined (would be NaN anyway)
            if v1.std() == 0 or v2.std() == 0:
                continue
            rho, _ = stats.spearmanr(v1, v2)
            if not np.isnan(rho):
                rhos.append(float(rho))
    return float(min(rhos)) if rhos else np.nan


def _qv_worker(task: str, model: str, lang: str) -> tuple[str, str, dict[str, float]]:
    """Load once per (task, model), iterate axes sequentially, return axis→rho dict."""
    df = load_parsed(model, task, lang=lang)
    axis_rhos: dict[str, float] = {}
    if df.empty:
        return task, model, axis_rhos
    for ax in AXES:
        rho = min_rho_for_axis(df, ax)
        if not np.isnan(rho):
            axis_rhos[ax] = rho
    return task, model, axis_rhos


def build_table(lang: str) -> pd.DataFrame:
    cell: dict[str, dict[str, list[float]]] = {
        m: {ax: [] for ax in AXES} for m in MODELS
    }

    pairs = [(task, model) for task in TASKS for model in MODELS]
    futures = {POOL.submit(_qv_worker, task, model, lang): (task, model)
               for task, model in pairs}
    for fut in as_completed(futures):
        task, model, axis_rhos = fut.result()
        for ax, rho in axis_rhos.items():
            cell[model][ax].append(rho)

    def fmt(vals: list[float], seed: str) -> str:
        if not vals:
            return "—"
        arr = np.array(vals)
        mean_rho = float(arr.mean())
        lo, hi = bootstrap_mean_ci(arr, seed_str=seed)
        ci = f"[{lo:.2f}–{hi:.2f}]" if not np.isnan(lo) else ""
        marker = "✓" if mean_rho >= THRESHOLD else ""
        return " ".join(p for p in [f"{mean_rho:.3f}", ci, marker] if p)

    records = []
    for model in MODELS:
        row: dict = {"Model": MODEL_DISPLAY[model]}
        axis_means = []
        for ax in AXES:
            vals = cell[model][ax]
            if vals:
                axis_means.append(float(np.mean(vals)))
            row[ax] = fmt(vals, seed=f"qv:{model}:{ax}:{lang}")
        if axis_means:
            all_arr = np.array(axis_means)
            lo, hi = bootstrap_mean_ci(all_arr, seed_str=f"qv:mean:{model}:{lang}")
            ci = f"[{lo:.2f}–{hi:.2f}]" if not np.isnan(lo) else ""
            row["Mean min ρ"] = " ".join(p for p in [f"{float(all_arr.mean()):.3f}", ci] if p)
        else:
            row["Mean min ρ"] = "—"
        records.append(row)

    df_table = pd.DataFrame(records)

    # Axis mean row
    ax_row: dict = {"Model": "Axis mean"}
    all_means = []
    for ax in AXES:
        vals = [v for m in MODELS for v in cell[m][ax]]
        if vals:
            all_means.append(float(np.mean(vals)))
        ax_row[ax] = fmt(vals, seed=f"qv:axmean:{ax}:{lang}")
    if all_means:
        arr = np.array(all_means)
        lo, hi = bootstrap_mean_ci(arr, seed_str=f"qv:axmean:overall:{lang}")
        ci = f"[{lo:.2f}–{hi:.2f}]" if not np.isnan(lo) else ""
        ax_row["Mean min ρ"] = " ".join(p for p in [f"{float(arr.mean()):.3f}", ci] if p)
    else:
        ax_row["Mean min ρ"] = "—"
    return pd.concat([df_table, pd.DataFrame([ax_row])], ignore_index=True)


def main() -> None:
    for lang in ("en", "hinglish"):
        label = "English" if lang == "en" else "Hinglish"
        print(f"\n{'='*50}")
        print(f"  {label}")
        print(f"{'='*50}")
        df_table = build_table(lang)
        print(f"\n{df_table.to_string(index=False)}")
        _qv_names = {"en": "table_08_qv_robustness_en.csv",
                     "hinglish": "table_09_qv_robustness_hinglish.csv"}
        out_path = OUT_DIR / _qv_names[lang]
        df_table.to_csv(out_path, index=False)
        print(f"\nSaved → {out_path}")


if __name__ == "__main__":
    main()
