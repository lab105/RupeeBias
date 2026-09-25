"""
Profile Rank Agreement — do identifiers agree on which profiles are better?

For each (model, use case, axis, lang):
  - Compute mean recommendation per profile under each identifier
  - Build a (profile × identifier) matrix
  - Compute pairwise Spearman ρ between all identifier columns
  - Take the mean ρ across all pairs

High ρ → all identifiers agree on profile quality rankings (merit-consistent)
Low ρ  → demographic identity changes which profiles the model considers better

Displayed as grouped bar chart (one per language), same format as other figures.
"""

from __future__ import annotations

import sys
import itertools
from concurrent.futures import as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import warnings
import numpy as np
import pandas as pd
from scipy import stats
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


def axis_rank_agreement(df: pd.DataFrame, axis: str) -> tuple[float, list[float]]:
    """
    Mean pairwise Spearman ρ across identifiers for one axis.
    Returns (mean_rho, [all pairwise rhos]) — list used for bootstrapping.
    """
    sub = df[df["axis"] == axis]
    if sub.empty:
        return np.nan, []

    # Mean value per (identifier, profile) averaging across QVs
    matrix = (
        sub.groupby(["identifier_value", "profile_id"])["value"]
        .mean()
        .unstack("identifier_value")
        .dropna(how="any")   # need complete profiles across all identifiers
    )

    if matrix.shape[0] < 3 or matrix.shape[1] < 2:
        return np.nan, []

    identifiers = list(matrix.columns)
    rhos = []
    for id_a, id_b in itertools.combinations(identifiers, 2):
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            rho, _ = stats.spearmanr(matrix[id_a].values, matrix[id_b].values)
        if np.isfinite(rho):
            rhos.append(float(rho))

    if not rhos:
        return np.nan, []

    return float(np.mean(rhos)), rhos


def compute_rank_agreement(model: str, task: str, lang: str) -> tuple[float, float, float]:
    """Mean Spearman ρ across all axes, with bootstrap CI."""
    df = load_parsed(model, task, lang=lang)
    if df.empty:
        return np.nan, np.nan, np.nan

    all_rhos = []
    for ax in AXES:
        _, rhos = axis_rank_agreement(df, ax)
        all_rhos.extend(rhos)

    if not all_rhos:
        return np.nan, np.nan, np.nan

    arr  = np.array(all_rhos)
    mean = float(arr.mean())
    lo, hi = bootstrap_mean_ci(arr, seed_str=f"rank_agree:{model}:{task}:{lang}")
    return mean, lo, hi


def build_data(lang: str) -> pd.DataFrame:
    pairs = [(model, task, label) for model in MODELS for task, label in USE_CASES]

    results: dict[tuple[str, str], tuple[float, float, float]] = {}

    def _worker(model: str, task: str, label: str) -> tuple[str, str, float, float, float]:
        mean, lo, hi = compute_rank_agreement(model, task, lang)
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
        vals  = df[uc_label].values
        ci_lo = df[f"{uc_label}_ci_lo"].values
        ci_hi = df[f"{uc_label}_ci_hi"].values
        offset = (i - n_ucs / 2 + 0.5) * bar_width
        color  = UC_COLORS[uc_label]

        ax.bar(x + offset, vals, width=bar_width,
               color=color, alpha=0.90, zorder=3,
               label=uc_label)

        for j, (v, lo, hi) in enumerate(zip(vals, ci_lo, ci_hi)):
            if not np.isfinite(v):
                continue
            elo = float(v - lo) if np.isfinite(lo) else 0
            ehi = float(hi - v) if np.isfinite(hi) else 0
            ax.errorbar(x[j] + offset, v,
                        yerr=[[max(elo, 0)], [max(ehi, 0)]],
                        fmt="none", color="#333333",
                        linewidth=0.8, capsize=2, capthick=0.8,
                        zorder=5)

    # Reference line at ρ = 1 (perfect agreement)
    ax.axhline(1.0, color="#888888", linewidth=0.8, linestyle="--", zorder=1)

    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_DISPLAY[m] for m in MODELS],
                       fontsize=9, ha="center")
    ax.set_ylabel("Mean Spearman ρ (profile rank agreement)", fontsize=10)
    ax.set_ylim(0, 1.05)
    ax.legend(title="Task", fontsize=8.5, title_fontsize=9,
              frameon=True, edgecolor="#cccccc", loc="lower right")
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
    for lang, fname in [("en",       "figure_12a_profile_rank_agreement_en.png"),
                         ("hinglish", "figure_12b_profile_rank_agreement_hinglish.png")]:
        print(f"\nComputing {lang}…")
        df = build_data(lang)
        print(df[["model"] + [label for _, label in USE_CASES]].to_string())
        plot_bar(df, fname)


if __name__ == "__main__":
    main()
