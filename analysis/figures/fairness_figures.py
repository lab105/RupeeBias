"""
Fairness bar charts — one for English, one for Hinglish.
Diverging horizontal bars: blue = fairness reduced bias, red = fairness increased bias.
"""

from __future__ import annotations

import sys
from concurrent.futures import as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Patch

from analysis.config import AXES
from analysis.pool import POOL
from analysis.io import load_parsed
from analysis.metrics.pair import build_pair_table, mean_delta_pct

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

TASK = "salary_estimation"


def _compute_model_fairness(model: str, lang: str) -> dict | None:
    df_std  = load_parsed(model, TASK, lang=lang, fairness=False)
    df_fair = load_parsed(model, TASK, lang=lang, fairness=True)
    if df_std.empty or df_fair.empty:
        return None
    std_deltas, fair_deltas = [], []
    for ax in AXES:
        s = mean_delta_pct(build_pair_table(df_std[df_std["axis"] == ax]))
        f = mean_delta_pct(build_pair_table(df_fair[df_fair["axis"] == ax]))
        if not np.isnan(s): std_deltas.append(s)
        if not np.isnan(f): fair_deltas.append(f)
    if not std_deltas or not fair_deltas:
        return None
    std   = float(np.mean(std_deltas))
    fair  = float(np.mean(fair_deltas))
    delta = fair - std
    red   = (std - fair) / std * 100 if std != 0 else np.nan
    return {"model": model, "display": MODEL_DISPLAY[model],
            "std": std, "fair": fair, "delta": delta, "reduction_pct": red}


def compute_lang(lang: str) -> pd.DataFrame:
    records = []
    futures = {POOL.submit(_compute_model_fairness, model, lang): model
               for model in MODELS}
    for fut in as_completed(futures):
        result = fut.result()
        if result is not None:
            records.append(result)
    df = pd.DataFrame(records)
    return df.sort_values("delta", ascending=False).reset_index(drop=True)


# ── Bar chart ─────────────────────────────────────────────────────────────────

def plot_bar(df: pd.DataFrame, lang_label: str, fname: str) -> None:
    deltas   = df["delta"].values      # negative = reduced (good), positive = increased (bad)
    models   = df["display"].values
    std_vals = df["std"].values
    fair_vals= df["fair"].values

    n = len(df)
    bar_colors = ["#d6604d" if d > 0 else "#4393c3" for d in deltas]

    fig, ax = plt.subplots(figsize=(7.5, 0.65 * n + 1.8), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#fafafa")

    ax.barh(range(n), deltas, color=bar_colors, height=0.55, zorder=3)
    ax.axvline(0, color="#333333", linewidth=1.0, zorder=4)

    x_max = max(abs(d) for d in deltas if not np.isnan(d))
    ax.set_xlim(-x_max * 1.55, x_max * 1.15)

    red_vals = df["reduction_pct"].values
    for i, (d, s, f, red) in enumerate(zip(deltas, std_vals, fair_vals, red_vals)):
        if np.isnan(d):
            continue
        pad  = x_max * 0.04
        ha   = "right" if d <= 0 else "left"
        x_d  = d - pad if d <= 0 else d + pad

        ax.text(x_d, i + 0.15, f"{d:+.1f}%",
                va="center", ha=ha, fontsize=8.5, color="#222222",
                fontweight="bold")
        red_str = f"{red:+.0f}%" if not np.isnan(red) else ""
        ax.text(x_d, i - 0.18, f"({s:.1f}→{f:.1f}, {red_str})",
                va="center", ha=ha, fontsize=7, color="#777777")

    ax.set_yticks(range(n))
    ax.set_yticklabels(models, fontsize=9.5)
    ax.set_ylim(-0.6, n - 0.4)
    ax.set_xlabel("Change in Mean Δ%  (← reduced bias       increased bias →)", fontsize=10)

    legend_elements = [
        Patch(facecolor="#4393c3", label="Instruction reduced bias"),
        Patch(facecolor="#d6604d", label="Instruction increased bias"),
    ]
    ax.legend(handles=legend_elements, fontsize=9, loc="lower left",
              frameon=True, edgecolor="#cccccc")

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", color="#e0e0e0", linewidth=0.5, zorder=0)

    plt.tight_layout()
    out_path = OUT / fname
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out_path}")


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    lang_configs = [
        ("en",       "",  "figure_13a_fairness_ablation_en.png"),
        ("hinglish", "", "figure_13b_fairness_ablation_hinglish.png"),
    ]

    results: dict[str, tuple[pd.DataFrame, str, str]] = {}

    def _compute_lang_cfg(lang: str, lang_label: str, fname: str
                          ) -> tuple[str, pd.DataFrame, str, str]:
        print(f"\nComputing {lang_label}…")
        df = compute_lang(lang)
        return lang, df, lang_label, fname

    futures = {POOL.submit(_compute_lang_cfg, lang, lang_label, fname): lang
               for lang, lang_label, fname in lang_configs}
    for fut in as_completed(futures):
        lang, df, lang_label, fname = fut.result()
        results[lang] = (df, lang_label, fname)

    for lang, lang_label, fname in lang_configs:
        df, lang_label, fname = results[lang]
        plot_bar(df, lang_label, fname)


if __name__ == "__main__":
    main()
