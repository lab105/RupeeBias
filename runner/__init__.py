"""
runner — End-to-end async batch runner for LLM evaluations.

Public API
----------
    from runner import run, RunConfig, retry_file

    # Run from main.py — pass params + prompts, runner does the rest
    await run(RunConfig(
        data="dataset_construction/salary_estimation/salary_estimation_en.jsonl",
        models=["openai/gpt-5.4"],
        task="salary_estimation",
        output_dir="runs",
    ))

    # Retry ERROR rows from a previous output, in place
    retry_file("runs/gpt-5.4/salary_estimation/salary_estimation_en_gpt-5.4_0.0.jsonl")

Module layout
-------------
    runner/
        config.py            RunConfig dataclass
        row.py               _Row result dataclass
        io.py                File load/save, output path helpers
        client.py            ChatClient: single API call + HTTP retry
        validation_hook.py   Bridges runner ↔ scripts.validation
        resume.py            Input-vs-output diff
        confirmation.py      Pre-run interactive confirmation
        retry.py             In-place ERROR row retry
        orchestrator.py      Runner: fan-out, drain-on-terminate, save
"""

from runner.config import RunConfig, BypassChecks
from runner.orchestrator import run
from runner.retry import retry_file

__all__ = ["run", "RunConfig", "BypassChecks", "retry_file"]
