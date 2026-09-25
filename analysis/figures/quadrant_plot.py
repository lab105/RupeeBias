"""
Quadrant scatter: X = Mean Delta% (bias magnitude), Y = Mean W (consistency).

Data sources:
  - Mean W   : paper_analysis/tables/friedman_leaderboard_{lang}_raw.csv
  - Mean Delta%  : recomputed from task-named run files
"""

from __future__ import annotations

import itertools
from concurrent.futures import as_completed
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.patches as mpatches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis.io import load_parsed
from analysis.metrics.pair import build_pair_table, mean_delta_pct
from analysis.pool import POOL

ROOT = Path(__file__).resolve().parent.parent.parent
TABLES = ROOT / "paper_analysis" / "tables"
OUT = ROOT / "paper_analysis" / "figures" / "figure_03b_quadrant_bias_consistency.png"

MODELS = [
    "claude-opus-4.7",
    "claude-haiku-4.5",
    "gpt-5.4",
    "gpt-5.4-mini",
    "gemini-3-flash",
    "kimi-k2.5",
    "deepseek-v3.2",
    "glm-5.1",
    "sarvam-105b",
]

MODEL_DISPLAY = {
    "claude-haiku-4.5": "Claude Haiku 4.5",
    "claude-opus-4.7":  "Claude Opus 4.7",
    "deepseek-v3.2":    "DeepSeek V3.2",
    "gemini-3-flash":   "Gemini 3 Flash",
    "glm-5.1":          "GLM 5.1",
    "gpt-5.4":          "GPT 5.4",
    "gpt-5.4-mini":     "GPT 5.4-mini",
    "kimi-k2.5":        "Kimi K2.5",
    "sarvam-105b":      "Sarvam 105B",
}

TASKS = [
    "salary_estimation",
    "salary_increment_estimation",
    "counter_offer_recommendation",
    "service_pricing_vendor",
    "service_pricing_client",
]

AXES_ORDER = ["Religion", "Caste", "Region", "Gender", "Disability", "Urban/Rural"]
CLOSED = ["claude-opus-4.7", "claude-haiku-4.5", "gpt-5.4", "gpt-5.4-mini", "gemini-3-flash"]
OPEN = ["kimi-k2.5", "deepseek-v3.2", "glm-5.1", "sarvam-105b"]
CLOSED_COLOR = "#2171b5"
OPEN_COLOR = "#2ca02c"


def model_color(model: str) -> str:
    return CLOSED_COLOR if model in CLOSED else OPEN_COLOR


def model_marker(model: str) -> str:
    return "o" if model in CLOSED else "^"


def task_axis_mean_delta(model: str, task: str, lang: str, axis: str) -> float:
    df = load_parsed(model, task, lang=lang)
    if df.empty:
        return np.nan
    pt = build_pair_table(df[df["axis"] == axis])
    return mean_delta_pct(pt)


def overall_mean_delta(model: str, lang: str) -> float:
    """Mean Delta% across all axes and tasks for one model+language."""
    vals = []
    for task in TASKS:
        df = load_parsed(model, task, lang=lang)
        if df.empty:
            continue
        for axis in AXES_ORDER:
            pt = build_pair_table(df[df["axis"] == axis])
            d = mean_delta_pct(pt)
            if not np.isnan(d):
                vals.append(d)
    return float(np.mean(vals)) if vals else np.nan


def load_mean_w(lang: str) -> dict[str, float]:
    _raw_names = {"en": "table_05_friedman_leaderboard_en_raw.csv",
                  "hinglish": "table_06_friedman_leaderboard_hinglish_raw.csv"}
    path = TABLES / _raw_names[lang]
    df = pd.read_csv(path).set_index("model")
    return df["Mean_W"].to_dict()


def _avg(*vals: float) -> float:
    valid = [x for x in vals if not np.isnan(x)]
    return float(np.mean(valid)) if valid else np.nan


def main() -> None:
    print("Loading Mean W...")
    w_en = load_mean_w("en")
    w_hi = load_mean_w("hinglish")

    print("Computing Mean Delta%...")
    delta_en, delta_hi = {}, {}

    def _compute_model(model: str) -> tuple[str, float, float]:
        print(f"  {model}...")
        d_en = overall_mean_delta(model, "en")
        d_hi = overall_mean_delta(model, "hinglish")
        return model, d_en, d_hi

    futures = {POOL.submit(_compute_model, m): m for m in MODELS}
    for fut in as_completed(futures):
        model, d_en, d_hi = fut.result()
        delta_en[model] = d_en
        delta_hi[model] = d_hi

    mean_w = {m: _avg(w_en.get(m, np.nan), w_hi.get(m, np.nan)) for m in MODELS}
    mean_delta = {m: _avg(delta_en.get(m, np.nan), delta_hi.get(m, np.nan)) for m in MODELS}

    import matplotlib.ticker as ticker
    from matplotlib.lines import Line2D

    fig, ax = plt.subplots(figsize=(6.5, 5), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Per-model label nudges to avoid overlap
    label_offsets = {
        "claude-opus-4.7":  (6,   5),
        "claude-haiku-4.5": (6,   5),
        "gpt-5.4":          (6,   5),
        "gpt-5.4-mini":     (6,   5),
        "gemini-3-flash":   (6,   5),
        "kimi-k2.5":        (6,   5),
        "deepseek-v3.2":    (6,  -10),
        "glm-5.1":          (6,   5),
        "sarvam-105b":      (6,   5),
    }

    for model in MODELS:
        x = mean_delta.get(model, np.nan)
        y = mean_w.get(model, np.nan)
        if np.isnan(x) or np.isnan(y):
            continue
        ax.scatter(
            x, y,
            s=130,
            marker=model_marker(model),
            color=model_color(model),
            edgecolor="white",
            linewidth=0.6,
            zorder=3,
        )
        dx, dy = label_offsets.get(model, (6, 5))
        ax.annotate(
            MODEL_DISPLAY[model],
            (x, y),
            xytext=(dx, dy),
            textcoords="offset points",
            fontsize=9,
            ha="left" if dx >= 0 else "right",
            va="center",
            color="#222222",
        )

    ax.set_xlabel("Mean Δ%", fontsize=11)
    ax.set_ylabel("Mean W", fontsize=11)
    ax.grid(color="#e0e0e0", linewidth=0.5, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # Y-axis: 0.05 increments; X-axis: 5-unit increments
    ax.yaxis.set_major_locator(ticker.MultipleLocator(0.05))
    ax.xaxis.set_major_locator(ticker.MultipleLocator(5))
    ax.set_xlim(left=0)
    ax.set_ylim(bottom=0)

    # Legend: actual marker shapes, title "Model type"
    legend_handles = [
        Line2D([0], [0], marker="o", color="w", markerfacecolor=CLOSED_COLOR,
               markersize=10, label="Proprietary"),
        Line2D([0], [0], marker="^", color="w", markerfacecolor=OPEN_COLOR,
               markersize=10, label="Open-weight"),
    ]
    ax.legend(handles=legend_handles, title="Model type", title_fontsize=10,
              fontsize=9, frameon=True, edgecolor="#cccccc",
              loc="upper right", framealpha=1.0)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved -> {OUT}")


if __name__ == "__main__":
    main()
