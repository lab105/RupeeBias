"""
Friedman Rank Sum leaderboard — one table per language (EN and Hinglish).

For each (model, axis, task):
  Build a (profile_id × identifier_value) matrix (averaging over QVs).
  Run Friedman test → Kendall's W and p-value.

Per-axis W  = mean W over the five task-named outputs.
Per-axis sig: Fisher's method combining p-values across those tasks,
              BH FDR corrected (60 tests = 10 models × 6 axes).
Mean W sig : Fisher's method combining across all 6 axes per model,
              BH FDR corrected (10 tests).

Profile:
  Noise           : Mean W < 0.05
  Inconsistent    : 0.05 ≤ Mean W < 0.13
  Mostly consistent: Mean W ≥ 0.13

Performance
-----------
- All (model, task, axis) Friedman tests run in parallel via ThreadPoolExecutor.
- Polars group_by + pivot replaces pandas groupby + unstack for the matrix step.
- load_parsed() hits the pre-warmed cache (no I/O at compute time).
"""

from __future__ import annotations

import sys
from concurrent.futures import as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd
import polars as pl
from scipy import stats
from statsmodels.stats.multitest import multipletests

from analysis.config import AXES
from analysis.io import load_parsed
from analysis.pool import POOL

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
    "claude-haiku-4.5":  "Claude Haiku 4.5",
    "claude-opus-4.7":   "Claude Opus 4.7",
    "deepseek-v3.2":     "DeepSeek V3.2",
    "gemini-3-flash":    "Gemini 3 Flash",
    "glm-5.1":           "GLM 5.1",
    "gpt-5.4":           "GPT 5.4",
    "gpt-5.4-mini":      "GPT 5.4-mini",
    "kimi-k2.5":         "Kimi K2.5",
    "sarvam-105b":       "Sarvam 105B",
}

OUT_DIR = ROOT / "paper_analysis" / "tables"
OUT_DIR.mkdir(parents=True, exist_ok=True)

TASKS = [
    "salary_estimation",
    "salary_increment_estimation",
    "counter_offer_recommendation",
    "service_pricing_vendor",
    "service_pricing_client",
]

# ---------------------------------------------------------------------------
# Phase 1: pre-aggregate all (model, task) slices → numpy matrices per axis
# Only polars work here; kept at limited parallelism to avoid thread-pool
# contention inside polars' own Rust scheduler.
# ---------------------------------------------------------------------------

# (model, task, axis) → (arrays, n, k) or None
_MatrixStore = dict[tuple[str, str, str], tuple[list, int, int] | None]


def _precompute_matrices(
    data_pl: dict[tuple[str, str], pl.DataFrame],
    axes: list[str],
) -> _MatrixStore:
    """
    For each (model, task): one polars group_by over ALL axes at once,
    then pivot per axis and store as numpy arrays.
    Returns a flat dict keyed by (model, task, axis).
    """

    def _one_slice(model: str, task: str) -> tuple[str, str, dict]:
        df = data_pl.get((model, task))
        if df is None:
            return model, task, {}

        # Single group_by pass covers all axes simultaneously
        grouped = (
            df.filter(pl.col("value").is_not_null())
            .group_by(["axis", "profile_id", "identifier_value"])
            .agg(pl.col("value").mean())
        )

        per_axis: dict[str, tuple[list, int, int] | None] = {}
        for axis in axes:
            sub = grouped.filter(pl.col("axis") == axis).drop("axis")
            if sub.is_empty():
                per_axis[axis] = None
                continue
            try:
                matrix = sub.pivot(
                    index="profile_id",
                    on="identifier_value",
                    values="value",
                ).drop_nulls()
            except Exception:
                per_axis[axis] = None
                continue

            id_cols = [c for c in matrix.columns if c != "profile_id"]
            n, k = matrix.shape[0], len(id_cols)
            if n < 2 or k < 2:
                per_axis[axis] = None
            else:
                per_axis[axis] = ([matrix[c].to_numpy() for c in id_cols], n, k)

        return model, task, per_axis

    store: _MatrixStore = {}
    futures = {
        POOL.submit(_one_slice, m, t): (m, t)
        for m in MODELS for t in TASKS
    }
    for future in as_completed(futures):
        m, t, per_axis = future.result()
        for axis, val in per_axis.items():
            store[(m, t, axis)] = val

    return store


# ---------------------------------------------------------------------------
# Phase 2: run Friedman tests — pure numpy/scipy, releases the GIL fully
# ---------------------------------------------------------------------------

def _run_friedman(
    store: _MatrixStore,
    axes: list[str],
) -> list[tuple[str, str, str, float, float]]:
    """
    Run scipy.stats.friedmanchisquare for every (model, task, axis) in full
    parallelism.  No polars here — numpy/scipy releases the GIL.
    """

    def _one(model: str, task: str, axis: str) -> tuple[str, str, str, float, float]:
        data = store.get((model, task, axis))
        if data is None:
            return model, task, axis, np.nan, np.nan
        arrays, n, k = data
        try:
            chi2, p = stats.friedmanchisquare(*arrays)
        except Exception:
            return model, task, axis, np.nan, np.nan
        W = float(chi2 / (n * (k - 1))) if n * (k - 1) > 0 else np.nan
        return model, task, axis, W, float(p)

    results: list[tuple[str, str, str, float, float]] = []
    futures = [
        POOL.submit(_one, m, t, ax)
        for m in MODELS for t in TASKS for ax in axes
    ]
    for future in as_completed(futures):
        results.append(future.result())

    return results


# ---------------------------------------------------------------------------
# Statistical helpers
# ---------------------------------------------------------------------------

def fisher_combine(p_values: list[float]) -> float:
    valid = [p for p in p_values if not np.isnan(p) and 0 < p <= 1]
    if len(valid) < 2:
        return valid[0] if len(valid) == 1 else np.nan
    chi2_stat = -2.0 * sum(np.log(p) for p in valid)
    return float(stats.chi2.sf(chi2_stat, df=2 * len(valid)))


def bh_correct(p_series: pd.Series) -> pd.Series:
    arr = p_series.fillna(1.0).values
    _, p_adj, _, _ = multipletests(arr, method="fdr_bh")
    result = pd.Series(p_adj, index=p_series.index)
    result[p_series.isna()] = np.nan
    return result


def assign_profile(mean_w: float) -> str:
    if np.isnan(mean_w):
        return "N/A"
    if mean_w < 0.05:
        return "Noise"
    if mean_w < 0.13:
        return "Inconsistent"
    return "Mostly consistent"


# ---------------------------------------------------------------------------
# Main leaderboard builder — parallelised
# ---------------------------------------------------------------------------

def build_leaderboard(lang: str) -> pd.DataFrame:
    print(f"\n{'='*60}")
    print(f"  Language: {lang}")
    print(f"{'='*60}")

    # Columns needed — all clean types (str/float), no timestamps
    _KEEP = ["axis", "value", "identifier_value", "profile_id", "question_variant_id"]

    # ── Step 1: load from cache (no I/O) and convert to polars ───────────────
    print("  Loading data from cache …")
    data_pl: dict[tuple[str, str], pl.DataFrame] = {}
    for task in TASKS:
        for model in MODELS:
            df = load_parsed(model, task, lang=lang)
            if not df.empty:
                cols = [c for c in _KEEP if c in df.columns]
                try:
                    data_pl[(model, task)] = pl.from_pandas(df[cols])
                except Exception:
                    safe = df[cols].copy()
                    for c in safe.select_dtypes("object").columns:
                        safe[c] = safe[c].astype(str)
                    data_pl[(model, task)] = pl.from_pandas(safe)

    # ── Step 2 (Phase 1): group_by + pivot — limited polars parallelism ───────
    # One group_by per (model, task) over ALL axes at once — 45 polars calls,
    # not 270, and worker count is capped to avoid Rust thread-pool contention.
    print(f"  Phase 1 — pre-aggregating {len(data_pl)} slices (polars, 8 workers) …")
    store = _precompute_matrices(data_pl, AXES)

    # ── Step 3 (Phase 2): Friedman tests — full numpy/scipy parallelism ───────
    # scipy.stats.friedmanchisquare releases the GIL; all 270 run truly in
    # parallel without fighting polars' internal scheduler.
    print(f"  Phase 2 — running {len(MODELS) * len(TASKS) * len(AXES)} "
          f"Friedman tests (scipy, 32 workers) …")
    results = _run_friedman(store, AXES)

    # ── Step 3: aggregate (model, task, axis) → (model, axis) mean W
    # cell[model][axis] = list of (W, p) across tasks
    cell: dict[str, dict[str, list[tuple[float, float]]]] = {
        m: {ax: [] for ax in AXES} for m in MODELS
    }
    for model, task, ax, W, p in results:
        if not np.isnan(W):
            cell[model][ax].append((W, p))

    # ── Step 4: per-model summary row
    records: list[dict] = []
    for model in MODELS:
        row: dict = {"model": model}
        axis_combined_ps: list[float] = []
        axis_Ws: list[float] = []

        for ax in AXES:
            pairs = cell[model][ax]
            if not pairs:
                row[f"W_{ax}"] = np.nan
                row[f"p_{ax}"] = np.nan
                continue
            Ws = [w for w, _ in pairs]
            ps = [p for _, p in pairs]
            mean_w = float(np.mean(Ws))
            combined_p = fisher_combine(ps)
            row[f"W_{ax}"] = mean_w
            row[f"p_{ax}"] = combined_p
            axis_Ws.append(mean_w)
            if not np.isnan(combined_p):
                axis_combined_ps.append(combined_p)

        mean_W_all = float(np.mean(axis_Ws)) if axis_Ws else np.nan
        row["Mean_W"]  = mean_W_all
        row["p_MeanW"] = fisher_combine(axis_combined_ps)
        records.append(row)

    df_raw = pd.DataFrame(records)

    # BH FDR correction
    for ax in AXES:
        df_raw[f"sig_{ax}"] = bh_correct(df_raw[f"p_{ax}"]) < 0.05
    df_raw["sig_MeanW"] = bh_correct(df_raw["p_MeanW"]) < 0.05

    df_raw = df_raw.sort_values("Mean_W", ascending=False).reset_index(drop=True)
    df_raw["Rank"]    = df_raw.index + 1
    df_raw["Profile"] = df_raw["Mean_W"].apply(assign_profile)

    return df_raw


# ---------------------------------------------------------------------------
# Formatting
# ---------------------------------------------------------------------------

def format_cell(W: float, sig: bool) -> str:
    if np.isnan(W):
        return "—"
    return f"{W:.3f}" + ("†" if sig else "")


def render_table(df_raw: pd.DataFrame, lang: str) -> pd.DataFrame:
    min_idx: dict[str, object] = {}
    for ax in AXES:
        valid = df_raw[f"W_{ax}"].dropna()
        if not valid.empty:
            min_idx[ax] = valid.idxmin()
    mean_valid = df_raw["Mean_W"].dropna()
    if not mean_valid.empty:
        min_idx["Mean W"] = mean_valid.idxmin()

    rows = []
    for idx, r in df_raw.iterrows():
        row = {"Model": MODEL_DISPLAY.get(r["model"], r["model"])}
        for ax in AXES:
            cell = format_cell(r[f"W_{ax}"], bool(r[f"sig_{ax}"]))
            if min_idx.get(ax) == idx:
                cell = f"**{cell}**"
            row[ax] = cell
        mean_cell = format_cell(r["Mean_W"], bool(r["sig_MeanW"]))
        if min_idx.get("Mean W") == idx:
            mean_cell = f"**{mean_cell}**"
        row["Mean W"]  = mean_cell
        row["Rank"]    = int(r["Rank"])
        row["Profile"] = r["Profile"]
        rows.append(row)

    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    for lang in ("en", "hinglish"):
        df_raw = build_leaderboard(lang)
        table  = render_table(df_raw, lang)

        label = "English" if lang == "en" else "Hinglish"
        print(f"\n{label} Friedman Leaderboard:")
        print(table.to_string(index=False))

        _raw_names = {
            "en":      "table_05_friedman_leaderboard_en_raw.csv",
            "hinglish":"table_06_friedman_leaderboard_hinglish_raw.csv",
        }
        df_raw.to_csv(OUT_DIR / _raw_names[lang], index=False)

        _fmt_names = {
            "en":      "table_05_friedman_leaderboard_en.csv",
            "hinglish":"table_06_friedman_leaderboard_hinglish.csv",
        }
        fmt_path = OUT_DIR / _fmt_names[lang]
        table.to_csv(fmt_path, index=False)
        print(f"\n  → {fmt_path}")


if __name__ == "__main__":
    main()
