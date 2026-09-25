"""
revalidate.py — Re-run validation on saved runs files and mark hard failures
as ERROR rows so they can be retried.

Two modes:

  Single-file mode (path supplied):
      python scripts/revalidate.py runs/gpt-5.4/salary_estimation/salary_estimation_en_gpt-5.4_0.0.jsonl

  Bulk mode (only --task supplied — no path):
      python scripts/revalidate.py --task salary_estimation
      python scripts/revalidate.py --task salary_estimation --yes
      Visits every model dir under runs/ — i.e. runs/*/<task>/*.jsonl.
      Test/smoke/_revalidated files are skipped. When both a base file and
      its `_retried` sibling exist, the retried one is processed.

Per file, prints each TERMINATE-severity failure (response + reason), asks
for confirmation, then writes <stem>_revalidated<ext> with the response
column of failed rows replaced by:

    ERROR: Validation failed [<check_type>]: <reason>

The retry tool picks these up because retry_file matches
`response.startswith("ERROR:")`:

    python main.py --retry-file runs/.../foo_revalidated.jsonl

Skipped automatically:
  - rows already marked ERROR (they're retry targets already)
  - FLAG-severity issues (refusals, whitespace, amount above ceiling)
"""

import argparse
import sys
from pathlib import Path

# Allow running as `python scripts/revalidate.py …` from repo root.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner.io import load, save
from runner.row import coerce_row_columns_to_object
from scripts.validation import (
    UNREALISTIC_RANGES,
    ValidationContext,
    ValidationSeverity,
    validate_response_during_eval,
)


RUNS_DIR = Path(__file__).resolve().parents[1] / "runs"

# Valid task identifiers come from the validator's own range table —
# single source of truth.
VALID_TASKS = sorted(UNREALISTIC_RANGES.keys())

# File-name fragments that mean "skip this file in bulk mode".
_BULK_SKIP_FRAGMENTS = ("smoke_test", "test_profile", "_test_", "_revalidated")


def _short(text: str, n: int = 200) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= n else flat[:n].rstrip() + " …"


def discover_files(task: str) -> list[Path]:
    """
    Bulk-mode file discovery. Walks runs/*/<task>/ for every model and
    returns one Path per logical run, preferring the `_retried` sibling
    when present.

    Excludes smoke/test/already-revalidated files via _BULK_SKIP_FRAGMENTS.
    """
    task = task.lower()
    candidates: list[Path] = []
    if not RUNS_DIR.exists():
        return []

    for model_dir in sorted(RUNS_DIR.iterdir()):
        if not model_dir.is_dir():
            continue
        task_dir = model_dir / task
        if not task_dir.exists():
            continue
        for p in sorted(task_dir.glob("*.jsonl")):
            if any(frag in p.name for frag in _BULK_SKIP_FRAGMENTS):
                continue
            candidates.append(p)

    # Prefer `_retried` sibling when both exist (drop the non-retried base).
    retried_stems = {p.name.removesuffix("_retried.jsonl")
                     for p in candidates if p.name.endswith("_retried.jsonl")}
    chosen = [
        p for p in candidates
        if p.name.endswith("_retried.jsonl")
           or p.name.removesuffix(".jsonl") not in retried_stems
    ]
    return chosen


def revalidate(path: Path, yes: bool = False, task_override: str | None = None) -> int:
    """
    Returns the number of rows marked.

    task_override: when set, every row is validated as if it were that task —
    bypasses per-row 'task' column lookup. Useful for files with a missing or
    incorrect task column, or when the same input was scored under a different
    expected schema.
    """
    if not path.exists():
        sys.exit(f"Error: {path} does not exist.")

    if task_override is not None:
        task_override = task_override.lower()
        if task_override not in VALID_TASKS:
            sys.exit(
                f"Error: invalid --task '{task_override}'. "
                f"Must be one of {VALID_TASKS}."
            )

    df = load(path, prompt_column="response")  # response column exists in run outputs

    if task_override is None and "task" not in df.columns:
        sys.exit(
            f"Error: {path} has no 'task' column. "
            f"Pass --task <name> to override (one of {VALID_TASKS})."
        )

    failures: list[tuple[int, str, str, str, str]] = []
    # (row_idx, id, task, response, ERROR_message)

    for i, row in df.iterrows():
        response = row.get("response", "")
        if isinstance(response, str) and response.startswith("ERROR:"):
            continue  # already a retry target

        task = (task_override
                if task_override is not None
                else str(row.get("task", "")).lower())
        if not task:
            continue

        ctx = ValidationContext(
            model=str(row.get("model", "?")),
            task=task,
            temperature=float(row.get("temperature", 0.0) or 0.0),
        )
        result, _ = validate_response_during_eval(
            response=response, task=task, context=ctx,
        )

        if result.severity != ValidationSeverity.TERMINATE:
            continue

        rid = row.get("id", "?")
        err_msg = f"ERROR: Validation failed [{result.check_type}]: {result.reason}"
        failures.append((i, str(rid), task, str(response), err_msg))

    if not failures:
        print(f"\nNo TERMINATE-severity validation failures in {path}.")
        return 0

    bar = "─" * 78
    print(f"\nFound {len(failures)} TERMINATE-severity failure(s) in {path}:\n")
    for _, rid, task, response, err in failures:
        print(bar)
        print(f"  id       : {rid}    task: {task}")
        print(f"  response : {_short(response)}")
        print(f"  → mark as: {err}")
    print(bar)
    print(f"\nTotal: {len(failures)} row(s) will be marked as ERROR.")

    if not yes:
        try:
            ans = input("Proceed and write _revalidated file? [y/N]: ").strip().lower()
        except EOFError:
            ans = "n"
        if ans not in ("y", "yes"):
            print("Cancelled.")
            return 0

    for idx, _, _, _, err in failures:
        df.at[idx, "response"] = err
        if "validation_status" in df.columns:
            df.at[idx, "validation_status"] = "invalid"
        if "validation_severity" in df.columns:
            df.at[idx, "validation_severity"] = "terminate"

    out = path.parent / f"{path.stem}_revalidated{path.suffix}"
    save(df, out)
    print(f"\nWrote {out}")
    print(f"Retry with: python main.py --retry-file {out}")
    return len(failures)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Revalidate runs file(s) and mark hard failures as ERROR rows.",
    )
    parser.add_argument(
        "path", nargs="?", default=None,
        help="Single file to revalidate. Omit to enter bulk mode (requires --task).",
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    parser.add_argument(
        "--task", default=None, choices=VALID_TASKS,
        help="(single-file mode) override per-row 'task' lookup. "
             "(bulk mode) revalidate every file under runs/*/<task>/.",
    )
    args = parser.parse_args()

    # ── Bulk mode ──
    if args.path is None:
        if args.task is None:
            parser.error("either a path or --task <name> is required")
        files = discover_files(args.task)
        if not files:
            print(f"No matching files in {RUNS_DIR}/*/{args.task}/")
            return

        print(f"Found {len(files)} file(s) under runs/*/{args.task}/:")
        for f in files:
            print(f"  • {f.relative_to(RUNS_DIR.parent)}")

        if not args.yes:
            try:
                ans = input(f"\nRevalidate all {len(files)}? [y/N]: ").strip().lower()
            except EOFError:
                ans = "n"
            if ans not in ("y", "yes"):
                print("Cancelled.")
                return

        # Per-file: each row's own 'task' column decides which validator runs.
        # We do NOT override with the bulk --task value — that flag selects
        # which directory to scan, not how to interpret each row.
        total = 0
        for f in files:
            print(f"\n══ {f} ══")
            total += revalidate(f, yes=True, task_override=None)
        print(f"\nBulk done. {total} row(s) marked across {len(files)} file(s).")
        return

    # ── Single-file mode ──
    revalidate(Path(args.path), yes=args.yes, task_override=args.task)


if __name__ == "__main__":
    main()
