"""
Radar chart grid: one radar per model, vertices = demographic axes,
one colored polygon per task. Aggregated across EN + Hinglish.
"""

from __future__ import annotations

from concurrent.futures import as_completed
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from analysis.io import load_parsed
from analysis.metrics.pair import build_pair_table, mean_delta_pct
from analysis.pool import POOL

ROOT = Path(__file__).resolve().parent.parent.parent
OUT = ROOT / "paper_analysis" / "figures" / "figure_02_radar_axis_mean_delta.png"

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
    ("salary_estimation", "Salary Estimation"),
    ("salary_increment_estimation", "Salary Increment Estimation"),
    ("counter_offer_recommendation", "Counter-offer Recommendation"),
    ("service_pricing_vendor", "Service Pricing (Vendor-Side)"),
    ("service_pricing_client", "Service Pricing (Client-Side)"),
]

TASK_COLORS = {
    "salary_estimation": "#2E74B5",
    "salary_increment_estimation": "#ED7D31",
    "counter_offer_recommendation": "#7030A0",
    "service_pricing_vendor": "#70AD47",
    "service_pricing_client": "#FFC000",
}

AXES_ORDER = ["Religion", "Caste", "Region", "Gender", "Disability", "Urban/Rural"]
LANGS = ("en", "hinglish")


def _task_axis_delta(df_en: pd.DataFrame, df_hi: pd.DataFrame, axis: str) -> float:
    frames = [df for df in (df_en, df_hi) if not df.empty]
    if not frames:
        return float("nan")
    df = pd.concat(frames, ignore_index=True)
    pt = build_pair_table(df[df["axis"] == axis], group_cols=["lang", "profile_id", "question_variant_id"])
    return mean_delta_pct(pt)


def _compute_model_task(model: str, task: str) -> tuple[str, str, dict[str, float]]:
    """Worker: load both lang DFs once, compute all axes. Returns (model, task, axis_dict)."""
    df_en = load_parsed(model, task, lang="en")
    df_hi = load_parsed(model, task, lang="hinglish")
    axis_dict = {axis: _task_axis_delta(df_en, df_hi, axis) for axis in AXES_ORDER}
    return model, task, axis_dict


def compute_task_matrix() -> dict[str, dict[str, dict[str, float]]]:
    """Returns {model: {task: {axis: mean_delta_pct}}}."""
    result: dict[str, dict[str, dict[str, float]]] = {model: {} for model in MODELS}
    pairs = [(model, task) for model in MODELS for task, _ in TASKS]
    futures = {POOL.submit(_compute_model_task, model, task): (model, task)
               for model, task in pairs}
    for fut in as_completed(futures):
        model, task, axis_dict = fut.result()
        result[model][task] = axis_dict
    return result


def draw_radar_line(ax, values, angles, color, lw=1.6, alpha_fill=0.08):
    vals = [v if not np.isnan(v) else 0.0 for v in values]
    a = list(angles) + [angles[0]]
    v = vals + [vals[0]]
    ax.plot(a, v, color=color, linewidth=lw, zorder=3)
    ax.fill(a, v, color=color, alpha=alpha_fill, zorder=2)


def draw_radar(ax, model: str, matrix: dict, angles, r_max: float):
    ax.set_theta_offset(np.pi / 2)
    for task, _ in TASKS:
        vals = [matrix[model][task].get(axis, np.nan) for axis in AXES_ORDER]
        if all(np.isnan(v) for v in vals):
            continue
        draw_radar_line(ax, vals, angles, color=TASK_COLORS[task], lw=2.0, alpha_fill=0.08)
        for ang, v in zip(angles, vals):
            if not np.isnan(v):
                ax.plot(ang, v, "o", color=TASK_COLORS[task], markersize=4.5, zorder=4)

    ax.set_ylim(0, r_max)
    r_ticks = np.linspace(0, r_max, 5)[1:]
    ax.set_yticks(r_ticks)
    ax.set_yticklabels([f"{int(v)}" for v in r_ticks], fontsize=9, color="#888888")
    ax.set_xticks(angles)
    ax.set_xticklabels(AXES_ORDER, fontsize=9.5)
    ax.tick_params(axis="x", pad=10)
    ax.grid(color="#dddddd", linewidth=0.6)
    ax.spines["polar"].set_color("#bbbbbb")


def main() -> None:
    print("Computing mean Delta% matrix...")
    matrix = compute_task_matrix()

    n_spokes = len(AXES_ORDER)
    angles = np.linspace(0, 2 * np.pi, n_spokes, endpoint=False)

    deepseek = "deepseek-v3.2"
    other_models = [m for m in MODELS if m != deepseek]

    other_vals = []
    for model in other_models:
        for task, _ in TASKS:
            other_vals.extend(v for v in matrix[model][task].values() if not np.isnan(v))
    r_max_other = np.ceil(max(other_vals, default=50) / 10) * 10

    ds_vals = []
    for task, _ in TASKS:
        ds_vals.extend(v for v in matrix[deepseek][task].values() if not np.isnan(v))
    r_max_deep = np.ceil(max(ds_vals, default=50) / 10) * 10

    import matplotlib.gridspec as gridspec

    fig = plt.figure(figsize=(10 * 2.2, 2 * 4.2), dpi=150)
    fig.patch.set_facecolor("white")
    gs = gridspec.GridSpec(2, 10, figure=fig, hspace=0.5, wspace=0.15)

    top5 = other_models[:5]
    bottom3 = other_models[5:]

    axes_list = []
    for i, model in enumerate(top5):
        ax = fig.add_subplot(gs[0, i * 2: i * 2 + 2], polar=True)
        axes_list.append((model, ax, r_max_other, "#f8f8f8", False))

    for i, model in enumerate(bottom3):
        ax = fig.add_subplot(gs[1, i * 2: i * 2 + 2], polar=True)
        axes_list.append((model, ax, r_max_other, "#f8f8f8", False))

    ax_ds = fig.add_subplot(gs[1, 6:8], polar=True)
    axes_list.append((deepseek, ax_ds, r_max_deep, "#fff5e6", True))

    legend_ax = fig.add_subplot(gs[1, 8:10])
    legend_ax.axis("off")
    handles = [plt.Line2D([0], [0], color=TASK_COLORS[task], linewidth=3.0)
               for task, _ in TASKS]
    labels = [label for _, label in TASKS]
    task_legend = legend_ax.legend(
        handles, labels,
        fontsize=10.5,
        frameon=True,
        fancybox=True,
        edgecolor="#cccccc",
        facecolor="white",
        loc="upper left",
        ncol=1,
        title="Tasks",
        title_fontsize=11.5,
        labelspacing=0.8,
        handlelength=1.6,
        borderpad=0.7,
        handletextpad=0.5,
        bbox_to_anchor=(0.0, 0.45, 1.0, 0.55),
        bbox_transform=legend_ax.transAxes,
        mode="expand",
    )
    legend_ax.add_artist(task_legend)

    from matplotlib.patches import Patch
    scale_handles = [
        Patch(facecolor="#f0f0f0", edgecolor="#aaaaaa"),
        Patch(facecolor="#fff5e6", edgecolor="#cc7700"),
    ]
    scale_labels = [
        f"Other models\n0-{int(r_max_other)}, gap {int(r_max_other // 4)}",
        f"DeepSeek V3.2\n0-{int(r_max_deep)}, gap {int(r_max_deep // 4)}",
    ]
    legend_ax.legend(
        scale_handles, scale_labels,
        fontsize=10.5,
        frameon=True,
        fancybox=True,
        edgecolor="#cccccc",
        facecolor="white",
        loc="lower left",
        ncol=2,
        title="Scale",
        title_fontsize=11.5,
        labelspacing=0.8,
        handlelength=1.6,
        borderpad=0.7,
        handletextpad=0.5,
        handleheight=1.5,
        bbox_to_anchor=(0.0, 0.0, 1.0, 0.40),
        bbox_transform=legend_ax.transAxes,
        mode="expand",
    )

    for model, ax, r_max, bg, is_deep in axes_list:
        ax.set_facecolor(bg)
        if is_deep:
            ax.spines["polar"].set_color("#cc7700")
        draw_radar(ax, model, matrix, angles, r_max)
        title_color = "#7a3500" if is_deep else "black"
        ax.set_title(
            MODEL_DISPLAY.get(model, model),
            fontsize=11.5,
            fontweight="bold",
            pad=36,
            va="bottom",
            color=title_color,
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved -> {OUT}")


if __name__ == "__main__":
    main()
