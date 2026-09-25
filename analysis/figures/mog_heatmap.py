"""
Maximum Observed Gap (MOG) combined heatmap — all 5 tasks as subplots.
Rows = axes, columns = models.
Color = gap% (sequential: white → deep red = larger gap).
Cell text: gap% (bold) / 95% bootstrap CI / top_ident vs bot_ident.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.gridspec import GridSpec

from analysis.tables import mog_per_model

OUT    = ROOT / "paper_analysis" / "figures"

MODELS = [
    "claude-haiku-4.5", "claude-opus-4.7", "deepseek-v3.2", "gemini-3-flash",
    "glm-5.1", "gpt-5.4", "gpt-5.4-mini", "kimi-k2.5", "sarvam-105b",
]
MODEL_DISPLAY = {
    "claude-haiku-4.5": "Claude Haiku 4.5",
    "claude-opus-4.7":  "Claude Opus 4.7",
    "deepseek-v3.2":  "DeepSeek V3.2",
    "gemini-3-flash":   "Gemini 3 Flash",
    "glm-5.1":          "GLM 5.1",
    "gpt-5.4":          "GPT 5.4",
    "gpt-5.4-mini":     "GPT 5.4-mini",
    "kimi-k2.5":        "Kimi K2.5",
    "sarvam-105b":      "Sarvam 105B",
}
COL_LABELS = [MODEL_DISPLAY[m] for m in MODELS]

AXIS_LABELS = ["Religion", "Caste", "Region", "Gender", "Disability", "Urban/Rural"]

_ABBREVS = {
    "Speech and language disability": "Speech & lang. dis.",
    "Chronic neurological condition":  "Chronic neuro. cond.",
    "Specific learning disability":    "Specific learning dis.",
}

def abbrev(name: str) -> str:
    return _ABBREVS.get(name, name)

TASKS = [
    ("Salary\nEstimation",             "salary_estimation"),
    ("Salary Increment\nEstimation",   "salary_increment_estimation"),
    ("Counter-offer\nRecommendation",  "counter_offer_recommendation"),
    ("Service Pricing\n(Vendor-Side)", "service_pricing_vendor"),
    ("Service Pricing\n(Client-Side)", "service_pricing_client"),
]


def parse_cell(val: str) -> tuple[float, str, str]:
    """Parse 'gap% / top_ident / bot_ident' → (gap, top, bot)."""
    s = str(val).strip()
    if s == "—":
        return np.nan, "", ""
    try:
        parts = s.split(" / ", 2)
        gap = float(parts[0].replace("%", "").strip())
        top = parts[1].strip() if len(parts) > 1 else ""
        bot = parts[2].strip() if len(parts) > 2 else ""
        return gap, top, bot
    except Exception:
        return np.nan, "", ""


def parse_ci_cell(val: str) -> tuple[float, float]:
    """Parse 'lo / hi' → (lo, hi)."""
    s = str(val).strip()
    if s == "—":
        return np.nan, np.nan
    try:
        parts = s.split(" / ", 1)
        return float(parts[0]), float(parts[1])
    except Exception:
        return np.nan, np.nan


def load_matrix(df: pd.DataFrame):
    n = len(df)
    gap_mat = np.full((n, len(MODELS)), np.nan)
    top_mat = [[""] * len(MODELS) for _ in range(n)]
    bot_mat = [[""] * len(MODELS) for _ in range(n)]
    for r, row in df.iterrows():
        for c, model in enumerate(MODELS):
            col = MODEL_DISPLAY[model]
            if col in row:
                g, t, b = parse_cell(row[col])
                gap_mat[r, c] = g
                top_mat[r][c] = t
                bot_mat[r][c] = b
    return gap_mat, top_mat, bot_mat


def load_ci_matrix(df: pd.DataFrame, n_axes: int, n_models: int):
    """Load CI table → (lo_mat, hi_mat)."""
    lo_mat = np.full((n_axes, n_models), np.nan)
    hi_mat = np.full((n_axes, n_models), np.nan)
    for r, row in df.iterrows():
        for c, model in enumerate(MODELS):
            col = MODEL_DISPLAY[model]
            if col in row:
                lo, hi = parse_ci_cell(row[col])
                lo_mat[r, c] = lo
                hi_mat[r, c] = hi
    return lo_mat, hi_mat


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    all_gap, all_top, all_bot, all_lo, all_hi = [], [], [], [], []
    for _, task in TASKS:
        gap_df, ci_df = mog_per_model.build_table(task)
        g, t, b = load_matrix(gap_df)
        lo, hi  = load_ci_matrix(ci_df, len(AXIS_LABELS), len(COL_LABELS))
        all_gap.append(g); all_top.append(t); all_bot.append(b)
        all_lo.append(lo); all_hi.append(hi)

    # Shared colour scale: p90 of all finite gap values
    all_finite = np.concatenate([m[np.isfinite(m)] for m in all_gap])
    cap = float(np.percentile(all_finite, 90))
    cap = max(cap, 5.0)

    cmap     = plt.cm.YlOrRd
    n_tasks  = len(TASKS)
    n_axes   = len(AXIS_LABELS)
    n_models = len(COL_LABELS)

    fig = plt.figure(figsize=(22, 6.5 * n_tasks), dpi=150)
    fig.patch.set_facecolor("white")

    gs = GridSpec(n_tasks, 2, figure=fig,
                  width_ratios=[20, 0.5],
                  hspace=0.08, wspace=0.03)

    axes    = [fig.add_subplot(gs[i, 0]) for i in range(n_tasks)]
    cbar_ax = fig.add_subplot(gs[:, 1])

    for idx, (ax, gap_mat, top_mat, bot_mat, lo_mat, hi_mat, (task_label, _)) in enumerate(
            zip(axes, all_gap, all_top, all_bot, all_lo, all_hi, TASKS)):

        im = ax.imshow(np.clip(gap_mat, 0, cap),
                       cmap=cmap, vmin=0, vmax=cap, aspect="auto")

        for r in range(n_axes):
            for c in range(n_models):
                gap = gap_mat[r, c]
                top = top_mat[r][c]
                bot = bot_mat[r][c]
                lo  = lo_mat[r, c]
                hi  = hi_mat[r, c]

                if np.isnan(gap):
                    ax.text(c, r, "—", ha="center", va="center",
                            fontsize=9, color="#999")
                    continue

                norm = np.clip(gap, 0, cap) / cap
                bg   = cmap(norm)
                lum  = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
                tc   = "white" if lum < 0.40 else "#1a1a1a"

                # Row 1: gap%
                ax.text(c, r - 0.33, f"{gap:.1f}%",
                        ha="center", va="center", fontsize=9.5,
                        color=tc, fontweight="bold")
                # Row 2: bootstrap 95% CI
                if not np.isnan(lo):
                    ci_str = f"[{lo:.1f}–{hi:.1f}]"
                    ax.text(c, r - 0.08, ci_str,
                            ha="center", va="center", fontsize=8.0,
                            color=tc, alpha=0.95)
                # Row 3: identifier pair — two stacked lines, same size as gap%
                ax.text(c, r + 0.18, abbrev(top),
                        ha="center", va="center", fontsize=9.5,
                        color=tc, alpha=0.88, fontweight="bold")
                ax.text(c, r + 0.40, abbrev(bot),
                        ha="center", va="center", fontsize=9.5,
                        color=tc, alpha=0.88, fontweight="bold")

        ax.set_yticks(range(n_axes))
        ax.set_yticklabels(AXIS_LABELS, fontsize=10.5)

        ax.set_ylabel(task_label, fontsize=11, fontweight="bold",
                      rotation=90, labelpad=14, va="center", ha="center")

        ax.set_xticks(range(n_models))
        if idx == 0:
            ax.set_xticklabels(COL_LABELS, fontsize=11, rotation=35, ha="left")
            ax.xaxis.set_label_position("top")
            ax.xaxis.tick_top()
        else:
            ax.set_xticklabels([])
            ax.tick_params(axis="x", length=0)

        ax.tick_params(axis="y", length=0)

    # Colourbar
    sm = plt.cm.ScalarMappable(cmap=cmap, norm=plt.Normalize(vmin=0, vmax=cap))
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cbar_ax)
    cbar.ax.tick_params(labelsize=9)
    cbar.set_label("Gap%\n(max − min identifier)", fontsize=9, labelpad=6)

    out_path = OUT / "figure_08_mog_heatmap.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out_path}")


if __name__ == "__main__":
    main()
