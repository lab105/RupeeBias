"""
io.py — File loaders/savers and output path helpers.

All format-aware logic for reading inputs and writing outputs lives here.
Adding a new format = add one entry to _LOADERS and _SAVERS.
"""

import logging
import subprocess
from pathlib import Path
from typing import Optional

import pandas as pd

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Format dispatch tables
# ---------------------------------------------------------------------------

_LOADERS = {
    # convert_dates=False keeps ISO timestamps (e.g. created_at) as plain
    # strings. Otherwise pandas auto-promotes them to datetime64[ms], which
    # then breaks any downstream code that wants to overwrite with a fresh
    # ISO string (retry, revalidate).
    ".csv":     lambda p: pd.read_csv(p),
    ".json":    lambda p: pd.read_json(p, convert_dates=False),
    ".jsonl":   lambda p: pd.read_json(p, lines=True, convert_dates=False),
    ".parquet": lambda p: pd.read_parquet(p),
    ".pq":      lambda p: pd.read_parquet(p),
    ".xlsx":    lambda p: pd.read_excel(p),
    ".xls":     lambda p: pd.read_excel(p),
}

_SAVERS = {
    ".csv":     lambda df, p: df.to_csv(p, index=False),
    ".json":    lambda df, p: df.to_json(p, orient="records", indent=2),
    ".jsonl":   lambda df, p: df.to_json(p, orient="records", lines=True),
    ".parquet": lambda df, p: df.to_parquet(p, index=False),
    ".pq":      lambda df, p: df.to_parquet(p, index=False),
    ".xlsx":    lambda df, p: df.to_excel(p, index=False),
    ".xls":     lambda df, p: df.to_excel(p, index=False),
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def load(path: Path, prompt_column: str = "prompt") -> pd.DataFrame:
    """Read input file and verify the prompt column exists."""
    ext = path.suffix.lower()
    loader = _LOADERS.get(ext)
    if loader is None:
        raise ValueError(
            f"Unsupported file type: {ext} (supported: {sorted(_LOADERS)})"
        )
    df = loader(path)
    if prompt_column not in df.columns:
        raise ValueError(
            f"Column '{prompt_column}' not found in {path}. "
            f"Found: {list(df.columns)}"
        )
    return df


def save(df: pd.DataFrame, path: Path) -> None:
    """Write DataFrame to disk; format inferred from suffix (default: CSV)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ext = path.suffix.lower()
    saver = _SAVERS.get(ext, _SAVERS[".csv"])
    saver(df, path)
    log.info(f"Saved → {path}")


def output_path(
        src: Path,
        model: str,
        temp: float,
        output_dir: Optional[Path],
        output_filename: Optional[str] = None,
) -> Path:
    """
    Build output path. Precedence:
      1. output_dir + output_filename → use exactly that
      2. output_dir + auto name       → output_dir / <stem>_<model-slug>_<temp><ext>
      3. src.parent + auto name       → next to source file

    Model slug = last path segment, ':' replaced with '-'.
    """
    if output_dir and output_filename:
        return output_dir / output_filename

    slug = model.split("/")[-1].replace(":", "-")
    name = f"{src.stem}_{slug}_{temp}{src.suffix}"
    if output_dir:
        return output_dir / name
    return src.parent / name


def retry_path(original: Path) -> Path:
    """
    Output path for in-place retry: <stem>_retried<ext>.

    Idempotent — if `original` already ends in `_retried`, returns it
    unchanged so iterative retries overwrite the same file rather than
    chaining `_retried_retried_retried…` indefinitely.
    """
    if original.stem.endswith("_retried"):
        return original
    return original.parent / f"{original.stem}_retried{original.suffix}"


# ---------------------------------------------------------------------------
# Misc
# ---------------------------------------------------------------------------


def get_git_sha() -> str:
    """Best-effort git SHA. Returns 'unknown' if not in a repo."""
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            stderr=subprocess.DEVNULL,
            text=True,
        ).strip()
    except Exception:
        return "unknown"
