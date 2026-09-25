"""
Merit Sensitivity — how much do recommendations vary across base profiles?

Same structure as mean_delta_by_task.py but flipped:
  Instead of pairing identifiers within a (profile, QV) slot,
  pair profiles within an (identifier, QV) slot.

High value = model is responsive to profile/merit differences.
Low value  = model ignores profile variation.

One chart for English, one for Hinglish. With 95% bootstrap CI. No title.
"""

from __future__ import annotations

import sys
import itertools
from concurrent.futures import as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analysis.io import load_parsed
from analysis.metrics.ci import bootstrap_mean_ci
from analysis.pool import POOL

OUT = ROOT / "paper_analysis" / "figures"

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
    "claude-haiku-4.5": "Claude\nHaiku 4.5",
    "claude-opus-4.7":  "Claude\nOpus 4.7",
    "deepseek-v3.2":  "DeepSeek\nV3.2",
    "gemini-3-flash":   "Gemini 3\nFlash",
    "glm-5.1":          "GLM 5.1",
    "gpt-5.4":          "GPT 5.4",
    "gpt-5.4-mini":     "GPT\n5.4-mini",
    "kimi-k2.5":        "Kimi K2.5",
    "sarvam-105b":      "Sarvam\n105B",
}

AXES = ["Religion", "Caste", "Region", "Gender", "Disability", "Urban/Rural"]

USE_CASES = [
    ("salary_estimation",            "Salary Estimation"),
    ("salary_increment_estimation",  "Salary Increment Estimation"),
    ("counter_offer_recommendation", "Counter-offer Recommendation"),
    ("service_pricing_vendor",       "Service Pricing (Vendor-Side)"),
    ("service_pricing_client",       "Service Pricing (Client-Side)"),
]

UC_COLORS = {
    "Salary Estimation":               "#4878CF",
    "Salary Increment Estimation":     "#F28E2B",
    "Service Pricing (Vendor-Side)":   "#59A14F",
    "Service Pricing (Client-Side)":   "#EDC948",
    "Counter-offer Recommendation":    "#8B6ECE",
}


def compute_merit_sensitivity(model: str, task: str, lang: str) -> tuple[float, float, float]:
    """
    For each (identifier_value, question_variant_id) slot, pair all profiles
    pairwise and compute relative gap. Returns (mean, ci_lo, ci_hi).
    """
    df = load_parsed(model, task, lang=lang)
    if df.empty:
        return np.nan, np.nan, np.nan

    all_deltas = []
    group_cols = [c for c in ["identifier_value", "question_variant_id"]
                  if c in df.columns]
    if not group_cols:
        return np.nan, np.nan, np.nan

    for ax in AXES:
        sub = df[df["axis"] == ax]
        if sub.empty:
            continue
        for _, grp in sub.groupby(group_cols):
            profile_vals = grp.set_index("profile_id")["value"].to_dict()
            for a, b in itertools.combinations(sorted(profile_vals), 2):
                va, vb = float(profile_vals[a]), float(profile_vals[b])
                denom = abs((va + vb) / 2)
                if denom < 1e-6:   # skip near-zero denominator
                    continue
                d = abs(va - vb) / denom * 100
                if np.isfinite(d):
                    all_deltas.append(d)

    if not all_deltas:
        return np.nan, np.nan, np.nan

    arr  = np.array(all_deltas)
    mean = float(arr.mean())
    lo, hi = bootstrap_mean_ci(arr, seed_str=f"merit:{model}:{task}:{lang}")
    return mean, lo, hi


def build_data(lang: str) -> pd.DataFrame:
    pairs = [(model, task, label) for model in MODELS for task, label in USE_CASES]
    results: dict[tuple[str, str], tuple[float, float, float]] = {}

    def _worker(model: str, task: str, label: str) -> tuple[str, str, float, float, float]:
        mean, lo, hi = compute_merit_sensitivity(model, task, lang)
        return model, label, mean, lo, hi

    futures = {POOL.submit(_worker, model, task, label): (model, label)
               for model, task, label in pairs}
    for fut in as_completed(futures):
        model, label, mean, lo, hi = fut.result()
        results[(model, label)] = (mean, lo, hi)

    records = []
    for model in MODELS:
        row = {"model": model}
        for task, label in USE_CASES:
            mean, lo, hi = results[(model, label)]
            row[label]            = mean
            row[f"{label}_ci_lo"] = lo
            row[f"{label}_ci_hi"] = hi
        records.append(row)
    return pd.DataFrame(records)


def plot_bar(df: pd.DataFrame, fname: str) -> None:
    uc_labels = [label for _, label in USE_CASES]
    n_models  = len(MODELS)
    n_ucs     = len(uc_labels)
    bar_width = 0.15
    x         = np.arange(n_models)

    fig, ax = plt.subplots(figsize=(13, 5), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#fafafa")

    for i, uc_label in enumerate(uc_labels):
        vals   = df[uc_label].values
        ci_lo  = df[f"{uc_label}_ci_lo"].values
        ci_hi  = df[f"{uc_label}_ci_hi"].values
        offset = (i - n_ucs / 2 + 0.5) * bar_width
        color  = UC_COLORS[uc_label]

        ax.bar(x + offset, vals, width=bar_width,
               color=color, alpha=0.90, zorder=3,
               label=uc_label)

        err_lo = np.where(np.isfinite(ci_lo), vals - ci_lo, 0)
        err_hi = np.where(np.isfinite(ci_hi), ci_hi - vals, 0)
        ax.errorbar(x + offset, vals,
                    yerr=[err_lo, err_hi],
                    fmt="none", color="#333333",
                    linewidth=0.8, capsize=2, capthick=0.8,
                    zorder=5)

    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_DISPLAY[m] for m in MODELS],
                       fontsize=9, ha="center")
    ax.set_ylabel("Merit Sensitivity (Mean Δ% across profiles)", fontsize=10)
    ax.set_ylim(bottom=0)
    ax.legend(title="Task", fontsize=8.5, title_fontsize=9,
              frameon=True, edgecolor="#cccccc", loc="upper right")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="y", color="#e0e0e0", linewidth=0.5, zorder=0)
    ax.tick_params(axis="x", length=0)

    plt.tight_layout()
    out_path = OUT / fname
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out_path}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for lang, fname in [("en",       "figure_11a_merit_sensitivity_en.png"),
                         ("hinglish", "figure_11b_merit_sensitivity_hinglish.png")]:
        print(f"\nComputing {lang}…")
        df = build_data(lang)
        plot_bar(df, fname)


if __name__ == "__main__":
    main()
