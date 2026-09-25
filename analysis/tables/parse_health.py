"""
Parse Health and Refusal Rate table (Appendix Table 23).

For each model, reports:
  - Parse health (%) : fraction of rows where a valid numeric response was extracted
  - Refusal rate (%) : fraction of rows flagged as refusals (e.g. DeepSeek -1 sentinel)

Pools all tasks and both languages.
Output: paper_analysis/tables/parse_health.csv
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from analysis.config import MODELS, RUNS_DIR, TABLES_DIR
from analysis.parsers import parse_response_column

log = logging.getLogger(__name__)

TASKS: list[str] = [
    "salary_estimation",
    "salary_increment_estimation",
    "counter_offer_recommendation",
    "service_pricing_vendor",
    "service_pricing_client",
]
LANGS: list[str] = ["en", "hinglish"]


def _load_raw(model: str, task: str, lang: str) -> pd.DataFrame:
    """Return raw (unparsed) rows for one (model, task, lang) slice, or empty DF."""
    task_dir = RUNS_DIR / model / task
    if not task_dir.exists():
        return pd.DataFrame()

    pattern = f"{task}_{lang}_*{model}*_0.0*.jsonl"
    files = sorted(task_dir.glob(pattern))
    # Baseline only — skip smoke, revalidated, and fairness-instructed runs
    keep = [
        f for f in files
        if "smoke"        not in f.name
        and "_revalidated" not in f.name
        and "_fairness_"   not in f.name
    ]
    if not keep:
        return pd.DataFrame()

    # Prefer _retried over base if both present
    retried = [f for f in keep if "_retried" in f.name]
    chosen = retried[-1] if retried else keep[-1]

    try:
        return pd.read_json(chosen, lines=True, convert_dates=False)
    except Exception as exc:
        log.warning(f"  Could not load {chosen}: {exc}")
        return pd.DataFrame()


def build_parse_health() -> pd.DataFrame:
    rows: list[dict] = []

    for model in MODELS:
        total = 0
        parsed_ok = 0
        refusals = 0

        for task in TASKS:
            for lang in LANGS:
                df = _load_raw(model, task, lang)
                if df.empty:
                    continue

                n = len(df)
                total += n

                df = parse_response_column(df, task)
                parsed_ok += int(df["value"].notna().sum())

                if "is_refusal" in df.columns:
                    refusals += int(df["is_refusal"].sum())

        if total == 0:
            log.warning(f"  No data found for model '{model}' — skipping")
            continue

        rows.append({
            "Model":            model,
            "Total rows":       total,
            "Parse health (%)": round(parsed_ok / total * 100, 1),
            "Refusal rate (%)": round(refusals  / total * 100, 2),
        })

    return pd.DataFrame(rows)


def main() -> None:
    TABLES_DIR.mkdir(parents=True, exist_ok=True)
    df = build_parse_health()
    out = TABLES_DIR / "table_23_parse_health.csv"
    df.to_csv(out, index=False)
    log.info(f"  Wrote {out}  ({len(df)} models)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
