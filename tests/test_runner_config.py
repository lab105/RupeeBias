"""Tests for runner.config — RunConfig + BypassChecks parsing."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from runner.config import BYPASS_CHECKS, BypassChecks, RunConfig


class TestBypassChecksParse:

    def test_none_returns_empty(self):
        b = BypassChecks.parse(None)
        assert not b
        assert "refusal" not in b

    def test_empty_string_returns_empty(self):
        assert not BypassChecks.parse("")

    def test_single_check(self):
        b = BypassChecks.parse("refusal")
        assert "refusal" in b
        assert "consecutive" not in b

    def test_multiple_checks(self):
        b = BypassChecks.parse("refusal,consecutive,truncation")
        assert "refusal" in b
        assert "consecutive" in b
        assert "truncation" in b
        assert "amount_low" not in b

    def test_whitespace_tolerant(self):
        b = BypassChecks.parse(" refusal , consecutive ")
        assert "refusal" in b
        assert "consecutive" in b

    def test_all_keyword_enables_everything(self):
        b = BypassChecks.parse("all")
        for check in BYPASS_CHECKS:
            assert check in b

    def test_unknown_check_raises(self):
        with pytest.raises(ValueError) as exc:
            BypassChecks.parse("bogus_check")
        assert "bogus_check" in str(exc.value)

    def test_str_repr_sorted(self):
        b = BypassChecks.parse("truncation,refusal")
        assert str(b) == "refusal,truncation"

    def test_str_empty(self):
        assert str(BypassChecks.parse(None)) == "(none)"


class TestRunConfigDefaults:

    def test_minimal_construction(self):
        cfg = RunConfig(
            data="x.jsonl", models=["m1"], task="salary_estimation",
        )
        assert cfg.temperatures == [0.0]
        assert cfg.confirm is True
        assert cfg.resume is False
        assert cfg.smoke_test is None
        assert not cfg.no_terminate

    def test_task_lowercased(self):
        cfg = RunConfig(data="x", models=["m"], task="SALARY_ESTIMATION")
        assert cfg.task == "salary_estimation"

    def test_paths_coerced(self):
        cfg = RunConfig(
            data="x", models=["m"], task="salary_estimation",
            output_dir="runs/test", input_path="data/in.jsonl",
        )
        assert cfg.output_dir == Path("runs/test")
        assert cfg.input_path == Path("data/in.jsonl")
