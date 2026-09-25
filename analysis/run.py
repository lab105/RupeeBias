"""Build the RupeeBias paper tables and figures into paper_analysis/.

Usage
-----
  # Full run (all tables + all figures, parallel)
  python -m analysis.run

  # Main results only — the two tables and four figures shown in the README
  python -m analysis.run --main-only

  # Control parallelism (default: 4 workers)
  python -m analysis.run --workers 8
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable

from tqdm import tqdm

from analysis.config import FIGURES_DIR, MODELS, OUT_DIR, TABLES_DIR, RUNS_DIR
from analysis.io import warm_cache
from analysis.figures import (
    cpg_heatmaps,
    fairness_figures,
    friedman_by_usecase,
    kendalls_w,
    identifier_favoritism_by_model,
    mean_delta_by_task,
    merit_sensitivity,
    mog_heatmap,
    profile_rank_agreement,
    quadrant_plot,
    radar_both_langs,
)
from analysis.tables import (
    cpg_per_model,
    friedman_leaderboard_per_lang,
    language_moderation_table,
    main_results,
    mog_per_model,
    parse_health,
    qv_robustness_per_model,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _section(title: str) -> None:
    log.info("")
    log.info(f"{'─' * 60}")
    log.info(f"  {title}")
    log.info(f"{'─' * 60}")


def _run_parallel(
    tasks: list[tuple[str, Callable]],
    workers: int,
) -> None:
    """Run a list of (label, fn) pairs in a ThreadPoolExecutor.

    Each fn() is called with no arguments. A tqdm progress bar tracks
    completion. Results (including exceptions) are collected and re-raised
    after all futures finish so that one failure doesn't silently skip the rest.
    """
    errors: list[tuple[str, BaseException]] = []

    with ThreadPoolExecutor(max_workers=workers) as pool:
        future_to_label = {pool.submit(_timed_call, label, fn): label
                           for label, fn in tasks}

        with tqdm(total=len(tasks), ncols=80, unit="job", leave=True) as bar:
            for future in as_completed(future_to_label):
                label = future_to_label[future]
                exc = future.exception()
                if exc:
                    log.error(f"  ✗ {label} FAILED: {exc}")
                    errors.append((label, exc))
                    bar.set_postfix_str(f"✗ {label[:30]}")
                else:
                    bar.set_postfix_str(f"✓ {label[:30]}")
                bar.update(1)

    if errors:
        names = ", ".join(lbl for lbl, _ in errors)
        raise RuntimeError(f"Analysis failed for: {names}") from errors[0][1]


def _timed_call(label: str, fn: Callable) -> None:
    log.info(f"  → {label} ...")
    t0 = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - t0
    log.info(f"  ✓ {label} done ({elapsed:.1f}s)")


# ---------------------------------------------------------------------------
# Task lists
# ---------------------------------------------------------------------------

# Tables must complete before figures that read their CSV output.
# Each inner list is a parallel batch; batches within a stage run sequentially.

MAIN_STAGES: list[list[tuple[str, Callable]]] = [
    # Stage 1: tables — quadrant_plot reads friedman_leaderboard CSVs
    # Outputs: table_01_dataset_composition.csv, table_02_main_results.csv
    #          table_05_friedman_leaderboard_{en,hinglish}{,_raw}.csv
    [
        ("Table 01/02 — dataset composition + main leaderboard",            main_results.main),
        ("Table 05/06 — axis-wise Kendall's W leaderboard (EN + Hinglish)", friedman_leaderboard_per_lang.main),
    ],
    # Stage 2: figures (safe to run in parallel once tables are written)
    # Outputs: figure_02_radar_axis_mean_delta.png
    #          figure_03a_kendalls_w_by_model.png
    #          figure_03b_quadrant_bias_consistency.png
    #          figure_04a/b_identifier_deviation_{religion,gender}.png
    #          figure_09a/b_identifier_deviation_{caste,region}.png
    #          figure_10a/b_identifier_deviation_{disability,urban_rural}.png
    [
        ("Figure 02 — radar: axis-wise Mean Δ% by model & use case",        radar_both_langs.main),
        ("Figure 03a — Kendall's W by model & language",                     kendalls_w.main),
        ("Figure 03b — quadrant: Mean Δ% vs Kendall's W",                   quadrant_plot.main),
        ("Figure 04/09/10 — identifier deviation (all 6 axes)",              identifier_favoritism_by_model.main),
    ],
]

APPENDIX_STAGES: list[list[tuple[str, Callable]]] = [
    # Stage 1: appendix tables (independent of each other)
    # Outputs: table_03_axiswise_mean_delta_en.csv, table_04_axiswise_mean_delta_hinglish.csv
    #          table_07_language_moderation.csv
    #          table_08_qv_robustness_en.csv, table_09_qv_robustness_hinglish.csv
    #          table_23_parse_health.csv
    #          figure_07_cpg_{task}.csv, figure_08_mog_{task}.csv
    [
        ("Table 03/04 — axis-wise Mean Δ% EN + Hinglish",                   main_results.main),  # already output by main stage; no-op rerun
        ("Table 07 — language moderation (Spearman ρ + Δ Mean Δ%)",         language_moderation_table.main),
        ("Table 08/09 — QV robustness EN + Hinglish",                       qv_robustness_per_model.main),
        ("Table 23 — parse health & refusal rate",                           parse_health.main),
        ("CPG per-model tables (all tasks)",                                 cpg_per_model.main),
        ("MOG per-model tables (all tasks)",                                 mog_per_model.main),
    ],
    # Stage 2: appendix figures
    # Outputs: figure_05a/b_mean_delta_by_usecase_{en,hinglish}.png
    #          figure_06a/b_friedman_by_usecase_{en,hinglish}.png
    #          figure_07_cpg_heatmap.png, figure_08_mog_heatmap.png
    #          figure_11a/b_merit_sensitivity_{en,hinglish}.png
    #          figure_12a/b_profile_rank_agreement_{en,hinglish}.png
    #          figure_13a/b_fairness_ablation_{en,hinglish}.png
    [
        ("Figure 05 — use-case-wise Mean Δ% (EN + Hinglish)",               mean_delta_by_task.main),
        ("Figure 06 — use-case-wise Kendall's W (EN + Hinglish)",           friedman_by_usecase.main),
        ("Figure 07 — CPG heatmap (all tasks × models)",                    cpg_heatmaps.main),
        ("Figure 08 — MOG heatmap (all tasks × models)",                    mog_heatmap.main),
        ("Figure 11 — merit sensitivity EN + Hinglish",                     merit_sensitivity.main),
        ("Figure 12 — profile rank agreement EN + Hinglish",                profile_rank_agreement.main),
        ("Figure 13 — fairness-instruction ablation EN + Hinglish",         fairness_figures.main),
    ],
]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Build RupeeBias paper tables and figures.",
        formatter_class=argparse.RawTextHelpFormatter,
    )
    parser.add_argument(
        "--main-only",
        action="store_true",
        help=(
            "Generate only the tables and figures shown in the README:\n"
            "  Tables: main leaderboard, Friedman leaderboard per language\n"
            "  Figures: radar, Friedman lollipop, quadrant, identifier favoritism\n"
            "Skips all appendix items."
        ),
    )
    parser.add_argument(
        "--workers", type=int, default=4, metavar="N",
        help="Number of parallel ThreadPoolExecutor workers (default: 4).",
    )
    args = parser.parse_args()

    # Validate runs directory
    if not RUNS_DIR.exists():
        log.error(f"Error: runs directory not found at {RUNS_DIR}")
        log.error("Please ensure the precomputed model outputs are present.")
        log.error("See README 'Reproducing Results' section for details.")
        sys.exit(1)

    if not any(RUNS_DIR.iterdir()):
        log.error(f"Error: runs directory is empty at {RUNS_DIR}")
        log.error("No model outputs found. Expected precomputed outputs in runs/<model>/<task>/")
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    mode = "main results only" if args.main_only else "full (main + appendix)"
    log.info(f"RupeeBias analysis  |  mode: {mode}  |  workers: {args.workers}")
    log.info(f"Input:  {RUNS_DIR}")
    log.info(f"Output: {OUT_DIR}")

    t0 = time.perf_counter()

    # ── Pre-warm the load_parsed cache ───────────────────────────────────────
    # Loads + parses every (model × task × lang) combination once, in parallel,
    # before any figure/table script runs.  All subsequent load_parsed() calls
    # inside scripts return instantly from cache (no I/O, no parsing).
    _section("Pre-warming data cache")
    warm_cache(models=MODELS, workers=args.workers)

    _section("Main results (tables → figures)")
    for stage in MAIN_STAGES:
        _run_parallel(stage, workers=args.workers)

    if not args.main_only:
        _section("Appendix (tables → figures)")
        for stage in APPENDIX_STAGES:
            _run_parallel(stage, workers=args.workers)

    elapsed = time.perf_counter() - t0
    log.info("")
    log.info(f"{'Main results' if args.main_only else 'Full run'} done in {elapsed:.1f}s  →  {OUT_DIR}")


if __name__ == "__main__":
    main()
