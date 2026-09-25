"""
CPG combined heatmap — all 5 tasks as subplots, single shared colour scale.
Rows = canonical pairs, columns = models.
Color = CPG% (diverging: red = privileged higher, blue = privileged lower).
Cell text = CPG% / sign_consistency%.
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

from analysis.tables import cpg_per_model

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

PAIR_LABELS = [
    "Hindu vs Muslim",
    "Brahmin vs Dalit",
    "Gujarati vs Santhali",
    "Male vs Female",
    "No disability vs\nInt. disability",
    "Tier 1 city vs Village",
]

TASKS = [
    ("Salary\nEstimation",             "salary_estimation"),
    ("Salary Increment\nEstimation",   "salary_increment_estimation"),
    ("Counter-offer\nRecommendation",  "counter_offer_recommendation"),
    ("Service Pricing\n(Vendor-Side)", "service_pricing_vendor"),
    ("Service Pricing\n(Client-Side)", "service_pricing_client"),
]


def parse_cell(val: str) -> tuple[float, float]:
    if str(val).strip() == "—":
        return np.nan, np.nan
    try:
        parts = str(val).replace("%", "").split("/")
        return float(parts[0].strip()), float(parts[1].strip())
    except Exception:
        return np.nan, np.nan


def load_matrix(df: pd.DataFrame, df_ci: pd.DataFrame):
    n = len(df)
    cpg  = np.full((n, len(MODELS)), np.nan)
    sc   = np.full((n, len(MODELS)), np.nan)
    ci_lo = np.full((n, len(MODELS)), np.nan)
    ci_hi = np.full((n, len(MODELS)), np.nan)

    for r, row in df.iterrows():
        for c, model in enumerate(MODELS):
            col = MODEL_DISPLAY[model]
            if col in row:
                cpg[r, c], sc[r, c] = parse_cell(row[col])
            if col in df_ci.columns:
                ci_val = str(df_ci.iloc[r][col]).strip()
                if ci_val != "—":
                    try:
                        parts = ci_val.split(" / ")
                        ci_lo[r, c] = float(parts[0])
                        ci_hi[r, c] = float(parts[1])
                    except Exception:
                        pass
    return cpg, sc, ci_lo, ci_hi


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)

    # Load all data
    all_cpg, all_sc, all_ci_lo, all_ci_hi = [], [], [], []
    for _, task in TASKS:
        df, df_ci = cpg_per_model.build_table(task)
        cpg, sc, ci_lo, ci_hi = load_matrix(df, df_ci)
        all_cpg.append(cpg)
        all_sc.append(sc)
        all_ci_lo.append(ci_lo)
        all_ci_hi.append(ci_hi)

    # Shared colour scale: p90 of absolute values across all tasks
    all_finite = np.concatenate([m[np.isfinite(m)] for m in all_cpg])
    cap = float(np.percentile(np.abs(all_finite), 90))
    cap = max(cap, 5.0)

    cmap     = plt.cm.RdBu_r
    n_tasks  = len(TASKS)
    n_pairs  = len(PAIR_LABELS)
    n_models = len(COL_LABELS)

    fig = plt.figure(figsize=(16, 4.2 * n_tasks), dpi=150)
    fig.patch.set_facecolor("white")

    gs = GridSpec(n_tasks, 2, figure=fig,
                  width_ratios=[20, 0.5],
                  hspace=0.08, wspace=0.03)

    axes   = [fig.add_subplot(gs[i, 0]) for i in range(n_tasks)]
    cbar_ax = fig.add_subplot(gs[:, 1])

    for idx, (ax, cpg_mat, sc_mat, ci_lo_mat, ci_hi_mat, (task_label, _)) in enumerate(
            zip(axes, all_cpg, all_sc, all_ci_lo, all_ci_hi, TASKS)):

        im = ax.imshow(np.clip(cpg_mat, -cap, cap),
                       cmap=cmap, vmin=-cap, vmax=cap, aspect="auto")

        for r in range(n_pairs):
            for c in range(n_models):
                cpg = cpg_mat[r, c]
                sc  = sc_mat[r, c]
                if np.isnan(cpg):
                    ax.text(c, r, "—", ha="center", va="center",
                            fontsize=9, color="#999")
                    continue
                norm = (np.clip(cpg, -cap, cap) + cap) / (2 * cap)
                bg   = cmap(norm)
                lum  = 0.299 * bg[0] + 0.587 * bg[1] + 0.114 * bg[2]
                tc   = "white" if lum < 0.40 else "#1a1a1a"
                sign = "+" if cpg >= 0 else ""
                lo   = ci_lo_mat[r, c]
                hi   = ci_hi_mat[r, c]
                sig  = (not np.isnan(lo)) and (lo > 0 or hi < 0)
                star = "*" if sig else ""
                ax.text(c, r - 0.15, f"{sign}{cpg:.1f}%{star}",
                        ha="center", va="center", fontsize=9.5,
                        color=tc, fontweight="bold")
                ax.text(c, r + 0.22, f"{sc:.0f}%",
                        ha="center", va="center", fontsize=8.0,
                        color=tc, alpha=0.85)

        # Y-axis: pair labels
        ax.set_yticks(range(n_pairs))
        ax.set_yticklabels(PAIR_LABELS, fontsize=10.5)

        # Row label: standard ylabel, rotated, tight to tick labels
        ax.set_ylabel(task_label, fontsize=11, fontweight="bold",
                      rotation=90, labelpad=14, va="center", ha="center")

        # X-axis: model names on top row only
        ax.set_xticks(range(n_models))
        if idx == 0:
            ax.set_xticklabels(COL_LABELS, fontsize=11, rotation=35, ha="left")
            ax.xaxis.set_label_position("top")
            ax.xaxis.tick_top()
        else:
            ax.set_xticklabels([])
            ax.tick_params(axis="x", length=0)

        ax.tick_params(axis="y", length=0)

    # Single shared colourbar
    sm = plt.cm.ScalarMappable(
        cmap=cmap, norm=plt.Normalize(vmin=-cap, vmax=cap))
    sm.set_array([])
    cbar = fig.colorbar(sm, cax=cbar_ax)
    cbar.ax.tick_params(labelsize=9)
    cbar.set_label("CPG%\n(+ = privileged higher)", fontsize=9, labelpad=6)

    out_path = OUT / "figure_07_cpg_heatmap.png"
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out_path}")


if __name__ == "__main__":
    main()
