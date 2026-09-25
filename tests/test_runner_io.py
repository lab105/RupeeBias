"""Tests for runner.io — file I/O and path helpers."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import pytest

from runner.io import load, output_path, retry_path, save


def _write_jsonl(path: Path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n")


class TestOutputPath:

    def test_auto_name_no_dir(self, tmp_path):
        src = tmp_path / "salary_estimation_en.jsonl"
        out = output_path(src, "openai/gpt-5.4", 0.0, output_dir=None)
        assert out == tmp_path / "salary_estimation_en_gpt-5.4_0.0.jsonl"

    def test_auto_name_with_dir(self, tmp_path):
        src = Path("data/salary_estimation_en.jsonl")
        out_dir = tmp_path / "runs"
        out = output_path(src, "openai/gpt-5.4", 0.0, output_dir=out_dir)
        assert out == out_dir / "salary_estimation_en_gpt-5.4_0.0.jsonl"

    def test_explicit_filename(self, tmp_path):
        src = Path("data/salary_estimation_en.jsonl")
        out = output_path(
            src, "any/model", 0.0, output_dir=tmp_path,
            output_filename="salary_estimation_en_any_model_0.0.jsonl",
        )
        assert out == tmp_path / "salary_estimation_en_any_model_0.0.jsonl"

    def test_model_slug_uses_last_segment(self, tmp_path):
        src = tmp_path / "x.jsonl"
        out = output_path(src, "a/b/c/deeply-nested-model", 0.5, output_dir=None)
        assert "deeply-nested-model" in out.name
        assert "/" not in out.name
        assert "a" not in out.stem.split("_")

    def test_colon_replaced_in_slug(self, tmp_path):
        src = tmp_path / "x.jsonl"
        out = output_path(src, "provider/model:v1", 0.0, output_dir=None)
        assert ":" not in out.name
        assert "model-v1" in out.name


class TestRetryPath:

    def test_appends_retried_suffix(self):
        p = Path("runs/x/salary_estimation/salary_estimation_en_gpt-5.4_0.0.jsonl")
        assert retry_path(p) == Path("runs/x/salary_estimation/salary_estimation_en_gpt-5.4_0.0_retried.jsonl")

    def test_preserves_extension(self):
        for ext in (".csv", ".jsonl", ".parquet"):
            p = Path(f"out{ext}")
            assert retry_path(p).suffix == ext


class TestLoadSave:

    def test_round_trip_jsonl(self, tmp_path):
        df = pd.DataFrame({"id": [1, 2], "prompt": ["a", "b"]})
        path = tmp_path / "x.jsonl"
        save(df, path)
        loaded = load(path, prompt_column="prompt")
        assert loaded.equals(df)

    def test_load_missing_prompt_column_raises(self, tmp_path):
        df = pd.DataFrame({"id": [1], "x": ["a"]})
        path = tmp_path / "x.jsonl"
        save(df, path)
        with pytest.raises(ValueError, match="not found"):
            load(path, prompt_column="prompt")

    def test_unsupported_format_raises(self, tmp_path):
        path = tmp_path / "x.weird"
        path.write_text("nothing")
        with pytest.raises(ValueError, match="Unsupported"):
            load(path, prompt_column="prompt")
