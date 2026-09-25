"""
Lollipop charts for the Friedman Rank Sum leaderboard.

One graph per language (EN and Hinglish).
  Y-axis  : models ordered by Mean W ascending (most consistent at top)
  X-axis  : Kendall's W (Mean W across all axes)
  One dot per model — filled = BH FDR significant, open = not significant
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

ROOT   = Path(__file__).resolve().parent.parent.parent
TABLES = ROOT / "paper_analysis" / "tables"
OUT    = ROOT / "paper_analysis" / "figures"

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

MODEL_COLORS = {
    "claude-opus-4.7":  "#2171b5",
    "claude-haiku-4.5": "#e7298a",
    "gpt-5.4":          "#d6604d",
    "gpt-5.4-mini":     "#e08214",
    "gemini-3-flash":   "#a6761d",
    "kimi-k2.5":        "#4dac26",
    "deepseek-v3.2":  "#7570b3",
    "glm-5.1":          "#1b7837",
    "sarvam-105b":      "#6a3d9a",
}


def plot_lang(lang: str, lang_label: str, ax: plt.Axes) -> None:
    _raw_names = {"en": "table_05_friedman_leaderboard_en_raw.csv",
                  "hinglish": "table_06_friedman_leaderboard_hinglish_raw.csv"}
    path = TABLES / _raw_names[lang]
    df = pd.read_csv(path)

    # Order by Mean W ascending so highest W is at the top
    df = df.sort_values("Mean_W", ascending=True).reset_index(drop=True)

    ax.set_facecolor("#fafafa")

    for i, row in df.iterrows():
        w   = row["Mean_W"]
        sig = bool(row["sig_MeanW"])
        col = MODEL_COLORS.get(row["model"], "#888888")

        # Stem from x=0 to dot
        ax.plot([0, w], [i, i], color=col, linewidth=1.2, alpha=0.5, zorder=2)

        # Dot: filled if significant, open if not
        if sig:
            ax.scatter(w, i, s=70, color=col, zorder=4, linewidths=0)
        else:
            ax.scatter(w, i, s=70, facecolors="none", edgecolors=col,
                       linewidths=1.8, zorder=4)

    # Y-axis ticks
    model_names = [MODEL_DISPLAY.get(m, m) for m in df["model"]]
    ax.set_yticks(range(len(df)))
    ax.set_yticklabels(model_names, fontsize=9.5)
    ax.set_ylim(-0.6, len(df) - 0.4)

    # X-axis
    ax.set_xlabel("Mean Kendall's W", fontsize=10)
    ax.set_xlim(left=0)

    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", color="#e8e8e8", linewidth=0.5, zorder=0)


def plot_grouped_bar() -> None:
    en = pd.read_csv(TABLES / "table_05_friedman_leaderboard_en_raw.csv")
    hi = pd.read_csv(TABLES / "table_06_friedman_leaderboard_hinglish_raw.csv")
    en = en[["model", "Mean_W", "sig_MeanW"]].rename(
        columns={"Mean_W": "W_en", "sig_MeanW": "sig_en"})
    hi = hi[["model", "Mean_W", "sig_MeanW"]].rename(
        columns={"Mean_W": "W_hi", "sig_MeanW": "sig_hi"})
    df = en.merge(hi, on="model")
    df["W_mean"] = (df["W_en"] + df["W_hi"]) / 2
    df = df.sort_values("W_mean", ascending=True).reset_index(drop=True)

    n = len(df)
    bar_h = 0.42
    y = np.arange(n)

    EN_COL = "#2171b5"
    HI_COL = "#d6604d"

    fig, ax = plt.subplots(figsize=(7, 3.8), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("#fafafa")

    for i, row in df.iterrows():
        for offset, w, sig, color, label in [
            (+bar_h / 2, row["W_en"], row["sig_en"], EN_COL, "English"),
            (-bar_h / 2, row["W_hi"], row["sig_hi"], HI_COL, "Hinglish"),
        ]:
            hatch = None if sig else "////"
            ax.barh(y[i] + offset, w, height=bar_h,
                    color=color, hatch=hatch, edgecolor="white" if sig else color,
                    linewidth=0.5, alpha=0.88, zorder=3,
                    label=label if i == 0 else "_")
            ax.text(w + 0.003, y[i] + offset, f"{w:.3f}",
                    va="center", ha="left", fontsize=9.5, color="#333333")

    ax.set_yticks(y)
    ax.set_yticklabels([MODEL_DISPLAY.get(m, m) for m in df["model"]], fontsize=11)
    ax.set_xlabel("Mean Kendall's W", fontsize=12)
    ax.tick_params(axis="x", labelsize=10.5)

    x_max = df[["W_en", "W_hi"]].max().max()
    ax.set_xlim(0, x_max * 1.18)

    ax.set_ylim(-0.55, n - 0.45)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.grid(axis="x", color="#e0e0e0", linewidth=0.5, zorder=0)
    ax.tick_params(axis="y", length=0)

    from matplotlib.patches import Patch
    legend_handles = [
        Patch(facecolor=EN_COL, label="English"),
        Patch(facecolor=HI_COL, label="Hinglish"),
    ]
    ax.legend(handles=legend_handles, fontsize=11, frameon=True,
              edgecolor="#cccccc", loc="lower right")

    plt.tight_layout(pad=0.4)
    out_path = OUT / "figure_03a_kendalls_w_by_model.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    print(f"Saved → {out_path}")
    plt.close(fig)


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    plot_grouped_bar()


if __name__ == "__main__":
    main()
