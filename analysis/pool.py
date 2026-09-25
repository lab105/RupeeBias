"""
pool.py — Shared bounded thread pool for all analysis worker threads.

All figure and table scripts import POOL from here instead of creating their
own ThreadPoolExecutor instances.  A single shared pool means the total number
of concurrent analysis threads is capped at POOL_SIZE regardless of how many
scripts run in parallel from analysis/run.py.

POOL_SIZE = cpu_count - 2
  • Leaves 2 cores free for the main thread, matplotlib rendering, and the OS.
  • On a 10-core machine → 8 workers max, far below the 80-thread spike
    caused by nested per-script executors.

Usage in figure/table scripts
------------------------------
    from analysis.pool import POOL
    from concurrent.futures import as_completed

    futures = {POOL.submit(fn, arg1, arg2): key for key in items}
    for fut in as_completed(futures):
        result = fut.result()
"""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor

# ── Global thread budget ───────────────────────────────────────────────────
POOL_SIZE: int = max(2, (os.cpu_count() or 4) - 2)

# Single process-wide executor shared by every figure/table module.
# ThreadPoolExecutor is thread-safe; submitting from multiple threads is fine.
POOL: ThreadPoolExecutor = ThreadPoolExecutor(
    max_workers=POOL_SIZE,
    thread_name_prefix="analysis",
)
