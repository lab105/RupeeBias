"""
Language Moderation table.

For each (model, axis):
  - Pool all tasks, both languages.
  - Compute mean value per identifier_value for EN and Hinglish separately.
  - Spearman rho between EN vs Hinglish identifier rankings.
  - Delta Mean Dp% = MeanD%(Hinglish) - MeanD%(EN), pooled across tasks.
  - Significance: dagger p<0.05, double-dagger p<0.01.

Cell format: rho_sig / +/-DeltaMeanDpct
Last row: Axis mean (rho only).
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

from analysis.io import load_parsed
from analysis.metrics.pair import build_pair_table, mean_delta_pct
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
    "claude-haiku-4.5": "Haiku 4.5",
    "claude-opus-4.7":  "Opus 4.7",
    "deepseek-v3.2":  "DeepSeek",
    "gemini-3-flash":   "Gemini",
    "glm-5.1":          "GLM 5.1",
    "gpt-5.4":          "GPT 5.4",
    "gpt-5.4-mini":     "GPT-mini",
    "kimi-k2.5":        "Kimi",
    "sarvam-105b":      "Sarvam",
}

AXES = ["Religion", "Caste", "Region", "Gender", "Disability", "Urban/Rural"]

TASKS = [
    "salary_estimation",
    "salary_increment_estimation",
    "counter_offer_recommendation",
    "service_pricing_vendor",
    "service_pricing_client",
]


def load_all_tasks(model: str, lang: str) -> pd.DataFrame:
    frames = []
    for task in TASKS:
        df = load_parsed(model, task, lang=lang)
        if not df.empty:
            frames.append(df)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def sig_marker(p: float) -> str:
    if p < 0.01:
        return "‡"   # ‡
    if p < 0.05:
        return "†"   # †
    return ""


def _compute_model_lang_mod(model: str) -> tuple[str, dict, dict]:
    """Worker: compute rho_store and delta_store entries for one model."""
    print(f"  {model}...")
    df_en = load_all_tasks(model, "en")
    df_hi = load_all_tasks(model, "hinglish")
    rho_m: dict = {}
    delta_m: dict = {}
    for ax in AXES:
        sub_en = df_en[df_en["axis"] == ax] if not df_en.empty else pd.DataFrame()
        sub_hi = df_hi[df_hi["axis"] == ax] if not df_hi.empty else pd.DataFrame()
        if sub_en.empty or sub_hi.empty:
            continue
        en_means = sub_en.groupby("identifier_value")["value"].mean()
        hi_means = sub_hi.groupby("identifier_value")["value"].mean()
        common = sorted(set(en_means.index) & set(hi_means.index))
        if len(common) < 3:
            continue
        rho, p = stats.spearmanr(
            en_means[common].rank().values,
            hi_means[common].rank().values,
        )
        rho_m[ax] = (float(rho), float(p))
        group_cols = [c for c in ("task", "profile_id", "question_variant_id") if c in sub_en.columns]
        en_mdp = mean_delta_pct(build_pair_table(sub_en, group_cols=group_cols))
        hi_mdp = mean_delta_pct(build_pair_table(sub_hi, group_cols=group_cols))
        if not (np.isnan(en_mdp) or np.isnan(hi_mdp)):
            delta_m[ax] = float(hi_mdp - en_mdp)
    return model, rho_m, delta_m


def build_table() -> pd.DataFrame:
    # Accumulate per (model, axis): rho and delta_mdp
    rho_store:   dict[str, dict[str, float]] = {}
    delta_store: dict[str, dict[str, float]] = {}

    futures = {POOL.submit(_compute_model_lang_mod, model): model for model in MODELS}
    for fut in as_completed(futures):
        model, rho_m, delta_m = fut.result()
        rho_store[model]   = rho_m
        delta_store[model] = delta_m

    # Build display table
    records = []
    for model in MODELS:
        row = {"Model": MODEL_DISPLAY[model]}
        for ax in AXES:
            rho_p = rho_store[model].get(ax)
            delta = delta_store[model].get(ax, np.nan)
            if rho_p is None:
                row[ax] = "—"
            else:
                rho, p = rho_p
                sign = "+" if rho >= 0 else ""
                marker = sig_marker(p)
                d_sign = "+" if not np.isnan(delta) and delta >= 0 else ""
                d_str = f"{d_sign}{delta:.1f}%" if not np.isnan(delta) else "—"
                row[ax] = f"{sign}{rho:.2f}{marker} / {d_str}"
        records.append(row)

    df_table = pd.DataFrame(records)

    # Axis mean row (mean rho only)
    ax_row = {"Model": "Axis mean"}
    for ax in AXES:
        rhos = [rho_store[m][ax][0] for m in MODELS if ax in rho_store[m]]
        ax_row[ax] = f"+{np.mean(rhos):.2f}" if rhos else "—"
    return pd.concat([df_table, pd.DataFrame([ax_row])], ignore_index=True)


def main():
    print("Computing language moderation table...")
    df = build_table()
    print("\n" + df.to_string(index=False))
    out_dir = ROOT / "paper_analysis" / "tables"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "table_07_language_moderation.csv"
    df.to_csv(out, index=False)
    print(f"\nSaved → {out}")


if __name__ == "__main__":
    main()
