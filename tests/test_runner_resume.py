"""Tests for runner.resume — input vs output diff."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd

from runner.resume import diff_input_vs_output


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


class TestDiff:

    def test_no_output_returns_full_input(self, tmp_path):
        df = pd.DataFrame({"id": [1, 2, 3], "prompt": ["a", "b", "c"]})
        rem, report = diff_input_vs_output(df, output_path=None, input_path=tmp_path / "in")
        assert len(rem) == 3
        assert report.completed == 0
        assert report.remaining == 3

    def test_output_missing_returns_full(self, tmp_path):
        df = pd.DataFrame({"id": [1, 2], "prompt": ["a", "b"]})
        rem, report = diff_input_vs_output(
            df, output_path=tmp_path / "missing.jsonl", input_path=tmp_path / "in",
        )
        assert len(rem) == 2
        assert report.completed == 0

    def test_partial_completion(self, tmp_path):
        df = pd.DataFrame({"id": [1, 2, 3, 4], "prompt": ["a", "b", "c", "d"]})
        out = tmp_path / "out.jsonl"
        _write_jsonl(out, [{"id": 1, "response": "x"}, {"id": 2, "response": "y"}])

        rem, report = diff_input_vs_output(df, output_path=out, input_path=tmp_path / "in")
        assert len(rem) == 2
        assert sorted(rem["id"].tolist()) == [3, 4]
        assert report.completed == 2
        assert report.remaining == 2
        assert not report.is_complete

    def test_full_completion(self, tmp_path):
        df = pd.DataFrame({"id": [1, 2], "prompt": ["a", "b"]})
        out = tmp_path / "out.jsonl"
        _write_jsonl(out, [{"id": 1}, {"id": 2}])

        rem, report = diff_input_vs_output(df, output_path=out, input_path=tmp_path / "in")
        assert len(rem) == 0
        assert report.is_complete

    def test_no_id_column_returns_full(self, tmp_path):
        df = pd.DataFrame({"prompt": ["a", "b"]})
        rem, report = diff_input_vs_output(
            df, output_path=tmp_path / "out.jsonl", input_path=tmp_path / "in",
        )
        assert len(rem) == 2
        assert report.completed == 0
