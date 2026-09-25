"""
Grouped bar chart — Mean Kendall's W by model and use case.
One chart for English, one for Hinglish.
Significant bars (BH-FDR corrected) = full opacity.
Non-significant bars = faded (alpha 0.25).
No title.
"""

from __future__ import annotations

import sys
from concurrent.futures import as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
from statsmodels.stats.multitest import multipletests
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from analysis.io import load_parsed
from analysis.metrics.omnibus import friedman
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
    "Salary Estimation":              "#4878CF",
    "Salary Increment Estimation":    "#F28E2B",
    "Service Pricing (Vendor-Side)":  "#59A14F",
    "Service Pricing (Client-Side)":  "#EDC948",
    "Counter-offer Recommendation":   "#8B6ECE",
}


def _friedman_worker(model: str, task: str, label: str, lang: str
                     ) -> tuple[str, str, float, list]:
    df = load_parsed(model, task, lang=lang)
    if df.empty:
        return model, label, np.nan, []
    ws, ps = [], []
    for ax in AXES:
        sub = df[df["axis"] == ax]
        if sub.empty:
            continue
        res = friedman(sub, value_col="value")
        if not np.isnan(res["W"]):
            ws.append(res["W"])
            ps.append(res["p"])
    return model, label, float(np.mean(ws)) if ws else np.nan, ps


def compute_friedman_per_usecase(lang: str) -> pd.DataFrame:
    """
    Returns DataFrame with columns:
      model, use_case, mean_W, p_values (list per axis), mean_p
    Then BH-FDR is applied globally across all (model × use_case × axis) cells.
    """
    pairs = [(model, task, label) for model in MODELS for task, label in USE_CASES]
    raw_results: list[tuple[str, str, float, list]] = []

    futures = {POOL.submit(_friedman_worker, model, task, label, lang): (model, label)
               for model, task, label in pairs}
    for fut in as_completed(futures):
        raw_results.append(fut.result())

    # Preserve original row order
    order = {(model, label): i for i, (model, _, label) in enumerate(
        (m, t, l) for m in MODELS for t, l in USE_CASES)}
    raw_results.sort(key=lambda x: order[(x[0], x[1])])

    records = [{"model": model, "use_case": label, "mean_W": mean_w, "p_vals": ps}
               for model, label, mean_w, ps in raw_results]

    df_out = pd.DataFrame(records)

    # BH-FDR correction across all (model × use_case × axis) p-values
    all_ps = [p for row in df_out["p_vals"] for p in row]
    if all_ps:
        reject, _, _, _ = multipletests(all_ps, method="fdr_bh")
        # Map back: for each (model, use_case), sig if ANY axis p is BH-rejected
        idx = 0
        sig_flags = []
        for _, row in df_out.iterrows():
            n = len(row["p_vals"])
            sig_flags.append(any(reject[idx: idx + n]))
            idx += n
        df_out["significant"] = sig_flags
    else:
        df_out["significant"] = False

    return df_out


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
        sub    = df[df["use_case"] == uc_label].set_index("model")
        vals   = np.array([sub.loc[m, "mean_W"] if m in sub.index else np.nan
                           for m in MODELS])
        sigs   = np.array([sub.loc[m, "significant"] if m in sub.index else False
                           for m in MODELS])
        offset = (i - n_ucs / 2 + 0.5) * bar_width
        color  = UC_COLORS[uc_label]

        for j, v in enumerate(vals):
            if np.isnan(v):
                continue
            hatch = None if sigs[j] else "////"
            ax.bar(x[j] + offset, v, width=bar_width,
                   color=color, alpha=0.90, hatch=hatch,
                   edgecolor="white" if sigs[j] else "#555555",
                   linewidth=0.4, zorder=3,
                   label=uc_label if j == 0 else "_nolegend_")

    ax.set_xticks(x)
    ax.set_xticklabels([MODEL_DISPLAY[m] for m in MODELS],
                       fontsize=9, ha="center")
    ax.set_ylabel("Mean Kendall's W", fontsize=10)
    ax.set_ylim(bottom=0)

    from matplotlib.patches import Patch
    legend_handles = [Patch(color=UC_COLORS[uc], alpha=0.90, label=uc)
                      for _, uc in USE_CASES]
    legend_handles += [
        Patch(facecolor="white", edgecolor="black", hatch=None,   linewidth=0.8, label="Significant (BH-FDR)"),
        Patch(facecolor="white", edgecolor="black", hatch="////", linewidth=0.8, label="Non-significant"),
    ]
    ax.legend(handles=legend_handles, title="Task", fontsize=8.5,
              title_fontsize=9, frameon=True, edgecolor="#cccccc",
              loc="upper right", ncol=2)

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
    for lang, fname in [("en",       "figure_06a_friedman_by_usecase_en.png"),
                         ("hinglish", "figure_06b_friedman_by_usecase_hinglish.png")]:
        print(f"\nComputing {lang}…")
        df = compute_friedman_per_usecase(lang)
        plot_bar(df, fname)


if __name__ == "__main__":
    main()
