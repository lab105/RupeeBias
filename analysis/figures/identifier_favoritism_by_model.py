"""
Identifier Favoritism by Model — horizontal grouped bar chart.

For each model (Y-axis), one horizontal bar per identifier showing its mean %
deviation from the within-slice (model × task × lang) grand mean.

Positive = favoured (right), Negative = disfavoured (left).
Averaged across all use-cases and both languages.
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
import matplotlib.ticker as ticker

from analysis.io import load_parsed
from analysis.pool import POOL

OUT = ROOT / "paper_analysis" / "figures"

MODELS = [
    "claude-haiku-4.5", "claude-opus-4.7", "deepseek-v3.2", "gemini-3-flash",
    "glm-5.1", "gpt-5.4", "gpt-5.4-mini", "kimi-k2.5", "sarvam-105b",
]

# Display labels — two-line where needed to avoid wide axis
MODEL_DISPLAY = {
    "claude-haiku-4.5": "Claude\nHaiku 4.5",
    "claude-opus-4.7":  "Claude\nOpus 4.7",
    "deepseek-v3.2":    "DeepSeek\nV3.2",
    "gemini-3-flash":   "Gemini 3\nFlash",
    "glm-5.1":          "GLM 5.1",
    "gpt-5.4":          "GPT 5.4",
    "gpt-5.4-mini":     "GPT\n5.4-mini",
    "kimi-k2.5":        "Kimi K2.5",
    "sarvam-105b":      "Sarvam\n105B",
}

TASKS = [
    "salary_estimation",
    "salary_increment_estimation",
    "counter_offer_recommendation",
    "service_pricing_vendor",
    "service_pricing_client",
]

# Selected identifiers per axis — matches paper figures
AXIS_IDENTIFIERS = {
    "Religion":   ["Hindu", "Muslim", "Christian", "Sikh", "Buddhist", "Jain"],
    "Gender":     ["Male", "Female", "Non-binary", "Trans Man", "Trans Woman"],
    "Caste":      ["Brahmin", "Kshatriya", "OBC", "Dalit", "Adivasi"],
    "Region":     ["Gujarati", "Punjabi", "Bengali", "Tamil", "Santhali"],
    "Disability": ["No disability", "Visual impairment", "Hearing impairment",
                   "Intellectual disability", "Mental illness"],
    "Urban/Rural": ["Tier 1 city", "Tier 2 city", "Tier 3 city", "Small town", "Village"],
}

# Consistent colour palette (index = identifier order)
_PALETTE = ["#4878CF", "#d6604d", "#59A14F", "#F28E2B", "#8B6ECE",
            "#EDC948", "#B07AA1", "#76B7B2", "#FF9DA7", "#9C755F"]

PALETTES: dict[str, list[str]] = {}   # override per-axis if needed


def _colors(axis: str, n: int) -> list[str]:
    base = PALETTES.get(axis, _PALETTE)
    return (base * ((n // len(base)) + 1))[:n]


# ---------------------------------------------------------------------------
# Data computation
# ---------------------------------------------------------------------------

def _deviation_worker(lang: str, model: str, task: str, axis: str) -> list[dict]:
    """Load one (lang, model, task), filter to axis, compute per-identifier deviations."""
    df = load_parsed(model, task, lang=lang)
    if df.empty:
        return []
    sub = df[df["axis"] == axis]
    if sub.empty:
        return []
    means = sub.groupby("identifier_value")["value"].mean()
    grand = means.mean()
    if abs(grand) < 1e-6:
        return []
    return [
        {"model": model, "identifier": ident, "pct_dev": (m - grand) / abs(grand) * 100}
        for ident, m in means.items()
    ]


def compute_deviations(axis: str) -> pd.DataFrame:
    """Per (model, identifier) mean % deviation from within-slice grand mean."""
    triples = [(lang, model, task)
               for lang in ("en", "hinglish")
               for model in MODELS
               for task in TASKS]
    records: list[dict] = []
    futures = {POOL.submit(_deviation_worker, lang, model, task, axis): (lang, model, task)
               for lang, model, task in triples}
    for fut in as_completed(futures):
        records.extend(fut.result())
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Plotting — horizontal layout matching paper style
# ---------------------------------------------------------------------------

def plot_by_model(axis: str, fname: str, legend_loc: str = "lower right") -> None:
    """
    Horizontal grouped bar chart.
    Models on Y-axis (Sarvam at top, Haiku at bottom).
    Bars extend left (negative) or right (positive) from centre line.
    Dashed horizontal rules separate model groups.
    """
    OUT.mkdir(parents=True, exist_ok=True)

    df = compute_deviations(axis)
    if df.empty:
        print(f"No data for axis '{axis}'")
        return

    identifiers = AXIS_IDENTIFIERS.get(axis, sorted(df["identifier"].unique()))
    identifiers = [i for i in identifiers if i in df["identifier"].unique()]
    n_ids   = len(identifiers)
    colors  = _colors(axis, n_ids)

    # Models bottom-to-top (index 0 = bottom of plot = Haiku)
    models_btt = list(MODELS)          # haiku … sarvam
    n_models   = len(models_btt)

    bar_h   = 0.10                     # height of a single bar
    spacing = n_ids * bar_h + 0.30     # vertical space per model group
    y_ctr   = np.arange(n_models) * spacing   # centre of each model group

    fig, ax = plt.subplots(figsize=(6.5, 7), dpi=150)
    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    for i, (ident, color) in enumerate(zip(identifiers, colors)):
        sub  = df[df["identifier"] == ident]
        vals = []
        for model in models_btt:
            model_vals = sub[sub["model"] == model]["pct_dev"].values
            vals.append(float(model_vals.mean()) if len(model_vals) > 0 else np.nan)

        # Identifier 0 → topmost bar in group; identifier n-1 → bottommost
        offset = (n_ids / 2 - 0.5 - i) * bar_h
        ax.barh(y_ctr + offset, vals,
                height=bar_h * 0.88,
                color=color, alpha=0.88,
                label=ident, zorder=3)

    # ── Zero reference line ───────────────────────────────────────────────
    ax.axvline(0, color="#333333", linewidth=1.0, zorder=4)

    # ── Dashed separators between model groups ────────────────────────────
    for i in range(1, n_models):
        sep = (y_ctr[i - 1] + y_ctr[i]) / 2
        ax.axhline(sep, color="#888888", linewidth=0.8,
                   linestyle="--", zorder=1)

    # ── Y-axis: model labels ──────────────────────────────────────────────
    ax.set_yticks(y_ctr)
    ax.set_yticklabels(
        [MODEL_DISPLAY[m] for m in models_btt],
        fontsize=9, va="center",
    )
    ax.tick_params(axis="y", length=0, pad=6)

    # ── X-axis: ±30, signed ticks ─────────────────────────────────────────
    ax.set_xlim(-32, 32)
    ax.xaxis.set_major_locator(ticker.MultipleLocator(10))
    ax.xaxis.set_major_formatter(
        ticker.FuncFormatter(
            lambda v, _: f"+{int(v)}" if v > 0 else str(int(v))
        )
    )
    ax.set_xlabel("Mean % deviation from axis mean", fontsize=10)
    ax.tick_params(axis="x", labelsize=9)

    # ── Grid & spines ─────────────────────────────────────────────────────
    ax.grid(axis="x", color="#e0e0e0", linewidth=0.5, zorder=0)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    # ── Legend ────────────────────────────────────────────────────────────
    ax.legend(fontsize=8, frameon=True, edgecolor="#cccccc",
              loc=legend_loc, framealpha=1.0)

    plt.tight_layout()
    out_path = OUT / fname
    fig.savefig(out_path, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {out_path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    plot_by_model("Religion",    "figure_04a_identifier_deviation_religion.png")
    plot_by_model("Gender",      "figure_04b_identifier_deviation_gender.png")
    plot_by_model("Caste",       "figure_09a_identifier_deviation_caste.png")
    plot_by_model("Region",      "figure_09b_identifier_deviation_region.png")
    plot_by_model("Disability",  "figure_10a_identifier_deviation_disability.png")
    plot_by_model("Urban/Rural", "figure_10b_identifier_deviation_urban_rural.png", legend_loc="center right")


if __name__ == "__main__":
    main()
