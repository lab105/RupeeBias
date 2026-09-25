"""
io.py — Locate and load model run files.

Files live at `runs/{model}/{task}/{task}[_implicit]_{lang}[_fairness]_<slug>_0.0[_retried].jsonl`.
Tasks are descriptive snake_case identifiers (no RQ keyword anywhere):

    salary_estimation
    salary_increment_estimation
    counter_offer_recommendation
    service_pricing_vendor
    service_pricing_client

Variant flags:
  - lang     : "en" | "hinglish"
  - fairness : True for fairness-instructed runs
  - implicit : True for implicit-identifier runs (salary_estimation only)

Performance notes
-----------------
- load_run()    uses polars `read_ndjson` (3-5× faster than pd.read_json for JSONL)
- load_parsed() uses a thread-safe "compute-once / wait" cache backed by
  threading.Event: the first thread to request a key computes it; every other
  thread that requests the same key while it is being computed blocks on an
  Event rather than doing duplicate work.  With 15 parallel scripts × 90
  combos this reduces JSONL reads + parses from ~1,350 down to exactly 90.
- warm_cache() pre-fills the entire cache (all models × tasks × langs) using
  a ThreadPoolExecutor before any figure/table script runs, so scripts never
  wait on I/O — they always hit a populated cache.
- Deduplication and null-filtering are done in polars (Rust) before converting
  to pandas.
"""

from __future__ import annotations

import logging
import threading
from concurrent.futures import as_completed
from pathlib import Path
from typing import Optional

import pandas as pd
import polars as pl

from analysis.config import MODELS, RUNS_DIR
from analysis.pool import POOL

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_EXCLUDE_FRAGMENTS = ("smoke_test", "_revalidated")
_MARKUP_TASKS      = {"counter_offer_recommendation"}

_ALL_TASKS: tuple[str, ...] = (
    "salary_estimation",
    "salary_increment_estimation",
    "counter_offer_recommendation",
    "service_pricing_vendor",
    "service_pricing_client",
)
_ALL_LANGS: tuple[str, ...] = ("en", "hinglish")

# ---------------------------------------------------------------------------
# Thread-safe "compute-once / wait" cache
#
# _PARSED_CACHE : key → pd.DataFrame   (populated results)
# _PENDING      : key → threading.Event (signals when in-flight compute finishes)
# _REGISTRY_LOCK: guards _PENDING mutations only (not the cache reads)
# ---------------------------------------------------------------------------

_PARSED_CACHE:   dict[tuple, pd.DataFrame]     = {}
_PENDING:        dict[tuple, threading.Event]  = {}
_REGISTRY_LOCK   = threading.Lock()


def clear_cache() -> None:
    """Evict all cached parsed DataFrames (useful in tests)."""
    with _REGISTRY_LOCK:
        _PARSED_CACHE.clear()
        _PENDING.clear()


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def _build_pattern(task: str, lang: str, fairness: bool, implicit: bool) -> str:
    """Construct filename glob pattern (without extension)."""
    parts = [task.lower()]
    if implicit:
        parts.append("implicit")
    parts.append(lang.lower())
    if fairness:
        parts.append("fairness")
    # Model slug is wildcard; temperature is fixed at 0.0.
    return "_".join(parts) + "_*_0.0"


def find_run_file(
        model: str,
        task: str,
        *,
        lang: str = "en",
        fairness: bool = False,
        implicit: bool = False,
) -> Optional[Path]:
    """
    Return the canonical run file for these conditions, preferring `_retried`.
    Returns None if no matching file exists.
    """
    task_dir = RUNS_DIR / model / task.lower()
    if not task_dir.exists():
        return None

    pattern = _build_pattern(task, lang, fairness, implicit)

    # Build exclusion list — drop any variant token NOT in the request.
    exclusions = list(_EXCLUDE_FRAGMENTS)
    if not fairness:
        exclusions.append("fairness")
    if not implicit:
        exclusions.append("implicit")

    def _filter(paths):
        return [p for p in paths if not any(f in p.name for f in exclusions)]

    retried = sorted(_filter(task_dir.glob(pattern + "_retried.jsonl")))
    if retried:
        return retried[0]
    canonical = sorted(_filter(task_dir.glob(pattern + ".jsonl")))
    return canonical[0] if canonical else None


def _row_count(path: Optional[Path]) -> int:
    if path is None or not path.exists():
        return 0
    try:
        with open(path, "rb") as f:
            return sum(1 for _ in f)
    except Exception:
        return 0


# ---------------------------------------------------------------------------
# Core I/O — polars-backed for speed
# ---------------------------------------------------------------------------

def load_run(
        model: str,
        task: str,
        *,
        lang: str = "en",
        fairness: bool = False,
        implicit: bool = False,
) -> Optional[pd.DataFrame]:
    """
    Load a single run file as a pandas DataFrame.

    Internally uses polars `read_ndjson` which is significantly faster than
    `pd.read_json(..., lines=True)` for large JSONL files.
    Adds `model_slug`, `lang`, and `task` columns for downstream aggregation.
    Returns None if the file does not exist.
    """
    path = find_run_file(model, task, lang=lang, fairness=fairness, implicit=implicit)
    if path is None:
        return None

    # polars read_ndjson: multi-threaded Rust parser, ~3-5× faster than pandas
    try:
        df_pl = pl.read_ndjson(path)
    except Exception:
        # Fallback to pandas if polars cannot parse the file (schema quirks)
        df_pd = pd.read_json(path, lines=True, convert_dates=False)
        df_pd.columns = [c.lower() for c in df_pd.columns]
        df_pd["model_slug"] = model
        df_pd["lang"] = lang
        if "task" not in df_pd.columns:
            df_pd["task"] = task
        return df_pd

    # Lowercase all column names
    df_pl = df_pl.rename({c: c.lower() for c in df_pl.columns})

    # Add metadata columns
    new_cols: list[pl.Expr] = []
    if "model_slug" not in df_pl.columns:
        new_cols.append(pl.lit(model).alias("model_slug"))
    if "lang" not in df_pl.columns:
        new_cols.append(pl.lit(lang).alias("lang"))
    if "task" not in df_pl.columns:
        new_cols.append(pl.lit(task).alias("task"))
    if new_cols:
        df_pl = df_pl.with_columns(new_cols)

    # Cast Date/Datetime columns to String to avoid pandas dtype conflicts.
    date_cols = [c for c, t in df_pl.schema.items() if t in (pl.Date, pl.Datetime)]
    if date_cols:
        df_pl = df_pl.with_columns(
            [pl.col(c).cast(pl.String) for c in date_cols]
        )

    return df_pl.to_pandas()


def load_concat(
        models: list[str],
        task: str,
        *,
        lang: str = "en",
        fairness: bool = False,
        implicit: bool = False,
) -> pd.DataFrame:
    """Concatenate runs from many models into one DataFrame."""
    frames = [
        df for m in models
        if (df := load_run(m, task, lang=lang, fairness=fairness, implicit=implicit)) is not None
    ]
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Coverage report
# ---------------------------------------------------------------------------

def coverage_report(
        models: list[str],
        tasks: tuple[str, ...] = (
            "salary_estimation",
            "salary_increment_estimation",
            "counter_offer_recommendation",
            "service_pricing_vendor",
            "service_pricing_client",
        ),
) -> pd.DataFrame:
    """Per (model × task × language), row count of the canonical run file (0 if absent)."""
    rows = []
    for m in models:
        row: dict = {"model": m}
        for task in tasks:
            for lang in ("en", "hinglish"):
                p = find_run_file(m, task, lang=lang)
                row[f"{task}_{lang}"] = _row_count(p)
        rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# Shared "load + parse" helper — cached, polars-accelerated
# ---------------------------------------------------------------------------

def load_parsed(
        model: str,
        task: str,
        *,
        lang: str = "en",
        fairness: bool = False,
        implicit: bool = False,
) -> pd.DataFrame:
    """
    Load, parse, and return only rows with a successfully extracted numeric value.

    Thread-safe "compute-once / wait" semantics:
    - If the result is already cached → return immediately (no lock needed).
    - If another thread is already computing the same key → block on its Event,
      then return the result it stored (no duplicate work).
    - If no thread has claimed the key yet → claim it, compute, signal the Event,
      store in cache.

    Pipeline:
      1. load_run()  — polars-backed NDJSON read.
      2. Drop DeepSeek reasoning-trace duplicates.
      3. parse_response_column() — task-specific regex via polars map_elements.
      4. counter_offer: replace value with markup_pct.
      5. Polars dedup on (identifier_value, profile_id, question_variant_id).
      6. Polars null-filter on `value`.
    """
    cache_key = (model, task, lang, fairness, implicit)

    # ── Fast path: already in cache ──────────────────────────────────────────
    result = _PARSED_CACHE.get(cache_key)
    if result is not None:
        return result

    # ── Slow path: claim the key or wait for another thread ──────────────────
    with _REGISTRY_LOCK:
        # Re-check under lock (another thread may have stored it between the
        # fast-path check and acquiring the lock)
        result = _PARSED_CACHE.get(cache_key)
        if result is not None:
            return result

        if cache_key in _PENDING:
            # Another thread is computing — grab its event and wait outside lock
            event = _PENDING[cache_key]
            we_compute = False
        else:
            # We're first — register an event so other threads know to wait
            event = threading.Event()
            _PENDING[cache_key] = event
            we_compute = True

    if not we_compute:
        # Wait for the computing thread to finish, then return its result
        event.wait()
        return _PARSED_CACHE.get(cache_key, pd.DataFrame())

    # ── We're the computing thread ────────────────────────────────────────────
    try:
        result = _compute_parsed(model, task, lang=lang, fairness=fairness, implicit=implicit)
        _PARSED_CACHE[cache_key] = result
        log.debug("cache MISS  %s / %s / %s", model, task, lang)
    finally:
        # Always signal waiters, even if compute raised
        with _REGISTRY_LOCK:
            _PENDING.pop(cache_key, None)
        event.set()

    return result


def sanitize_for_polars(df: pd.DataFrame) -> pd.DataFrame:
    """
    Cast ALL object-dtype columns to str (preserving NaN) before pl.from_pandas().

    Root cause: `created_at` is written as an epoch integer in some JSONL files
    and as an ISO-8601 string in others.  Sampling only a few rows misses the
    mixed-type column; casting the entire object dtype column to str is safe
    because polars can always represent it as Utf8.
    """
    df = df.copy()
    for col in df.select_dtypes(include="object").columns:
        mask = df[col].notna()
        df.loc[mask, col] = df.loc[mask, col].astype(str)
    return df


def _compute_parsed(
        model: str,
        task: str,
        *,
        lang: str = "en",
        fairness: bool = False,
        implicit: bool = False,
) -> pd.DataFrame:
    """Internal: load + parse one (model, task, lang) slice."""
    from analysis.parsers import parse_response_column
    from analysis.metrics.lrg import add_markup_column

    df = load_run(model, task, lang=lang, fairness=fairness, implicit=implicit)
    if df is None or df.empty:
        return pd.DataFrame()

    # Drop DeepSeek reasoning-trace rows
    if "deepseek" in model.lower() and "reasoning_content" in df.columns:
        df = df[df["reasoning_content"].isna() | (df["reasoning_content"] == "")]

    df = parse_response_column(df, task)

    if task in _MARKUP_TASKS:
        df = add_markup_column(df, value_col="counter_lpa", offered_col="offered_ctc_lpa")
        df["value"] = df["markup_pct"]

    dedup_cols = [c for c in ("identifier_value", "profile_id", "question_variant_id")
                  if c in df.columns]
    try:
        df_pl = pl.from_pandas(sanitize_for_polars(df))
        if dedup_cols:
            df_pl = df_pl.unique(subset=dedup_cols, keep="first", maintain_order=True)
        df_pl = df_pl.filter(pl.col("value").is_not_null())
        return df_pl.to_pandas().reset_index(drop=True)
    except Exception:
        if dedup_cols:
            df = df.drop_duplicates(subset=dedup_cols)
        return df[df["value"].notna()].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Cache pre-warming — call once before parallel scripts start
# ---------------------------------------------------------------------------

def warm_cache(
        models: list[str] | None = None,
        tasks: tuple[str, ...] = _ALL_TASKS,
        langs: tuple[str, ...] = _ALL_LANGS,
        fairness: bool = False,
        workers: int = 4,
) -> None:
    """
    Pre-fill the load_parsed cache for every (model, task, lang) combination.

    Call this once from analysis/run.py before the parallel figure/table stage.
    By the time scripts start executing, every cache key is already populated
    so all load_parsed() calls return instantly (no I/O, no parsing).

    workers: number of parallel threads for pre-loading (default 8 — I/O bound).
    """
    from tqdm import tqdm

    _models = models if models is not None else MODELS
    combos  = [(m, t, la) for m in _models for t in tasks for la in langs]

    log.info(f"Warming cache: {len(combos)} combinations "
             f"({len(_models)} models × {len(tasks)} tasks × {len(langs)} langs) …")

    def _load(m: str, t: str, la: str) -> str:
        load_parsed(m, t, lang=la, fairness=fairness)
        return f"{m}/{t}/{la}"

    futures = {POOL.submit(_load, m, t, la): (m, t, la) for m, t, la in combos}
    with tqdm(total=len(combos), ncols=80, unit="file", desc="Warming cache") as bar:
        for future in as_completed(futures):
            exc = future.exception()
            if exc:
                m, t, la = futures[future]
                log.warning(f"  warm_cache failed for {m}/{t}/{la}: {exc}")
            bar.update(1)

    hits = sum(1 for k in _PARSED_CACHE if not _PARSED_CACHE[k].empty)
    log.info(f"Cache warm: {hits}/{len(combos)} keys populated.")
