"""
Main-paper result tables for the task-aware analysis pipeline.

Outputs:
  - table_01_dataset_composition.csv
  - table_02_main_results.csv
  - table_03_axiswise_mean_delta_en.csv
  - table_04_axiswise_mean_delta_hinglish.csv
"""

from __future__ import annotations

from concurrent.futures import as_completed
from pathlib import Path

import numpy as np
import pandas as pd

from analysis.config import AXES, MODELS, ROOT, TABLES_DIR
from analysis.pool import POOL
from analysis.io import load_parsed
from analysis.metrics.ci import bootstrap_mean_ci
from analysis.metrics.pair import build_pair_table, mean_delta_pct, violation_at

TASKS: list[tuple[str, str]] = [
    ("salary_estimation", "Salary estimation"),
    ("salary_increment_estimation", "Salary increment estimation"),
    ("counter_offer_recommendation", "Counter-offer recommendation"),
    ("service_pricing_vendor", "Service pricing recommendation (vendor side)"),
    ("service_pricing_client", "Service pricing recommendation (client side)"),
]

LANGS = ("en", "hinglish")

MODEL_DISPLAY = {
    "claude-haiku-4.5": "Claude Haiku 4.5",
    "claude-opus-4.7": "Claude Opus 4.7",
    "deepseek-v3.2": "DeepSeek V3.2",
    "gemini-3-flash": "Gemini 3 Flash",
    "glm-5.1": "GLM 5.1",
    "gpt-5.4": "GPT 5.4",
    "gpt-5.4-mini": "GPT 5.4-mini",
    "kimi-k2.5": "Kimi K2.5",
    "sarvam-105b": "Sarvam 105B",
}


def _dataset_path(task: str, lang: str) -> Path:
    return ROOT / "dataset_construction" / task / f"{task}_{lang}.jsonl"


def _read_dataset(task: str, lang: str) -> pd.DataFrame:
    path = _dataset_path(task, lang)
    if not path.exists():
        return pd.DataFrame()
    return pd.read_json(path, lines=True, convert_dates=False)


def build_dataset_statistics() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    all_frames: list[pd.DataFrame] = []

    for task, label in TASKS:
        frames = [_read_dataset(task, lang) for lang in LANGS]
        frames = [df for df in frames if not df.empty]
        df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
        if df.empty:
            rows.append({
                "Use case": label,
                "Identifiers": 0,
                "Base profiles": 0,
                "Question variants": 0,
                "Languages": 0,
                "Total prompts": 0,
            })
            continue

        all_frames.append(df.assign(_task=task))
        rows.append({
            "Use case": label,
            "Identifiers": int(df["identifier_value"].nunique()),
            "Base profiles": int(df["profile_id"].nunique()),
            "Question variants": int(df["question_variant_id"].nunique()),
            "Languages": int(df["language"].nunique()),
            "Total prompts": int(len(df)),
        })

    if all_frames:
        all_df = pd.concat(all_frames, ignore_index=True)
        base_profiles = all_df[["_task", "profile_id"]].drop_duplicates().shape[0]
        q_variants = all_df[["_task", "question_variant_id"]].drop_duplicates().shape[0]
        rows.append({
            "Use case": "Total",
            "Identifiers": int(all_df["identifier_value"].nunique()),
            "Base profiles": int(base_profiles),
            "Question variants": int(q_variants),
            "Languages": int(all_df["language"].nunique()),
            "Total prompts": int(len(all_df)),
        })

    return pd.DataFrame(rows)


def _parsed_frames(model: str, lang: str | None = None) -> list[pd.DataFrame]:
    frames: list[pd.DataFrame] = []
    langs = LANGS if lang is None else (lang,)
    for task, _ in TASKS:
        for one_lang in langs:
            df = load_parsed(model, task, lang=one_lang)
            if not df.empty:
                frames.append(df)
    return frames


def _pairs_for_model(model: str, lang: str | None = None) -> pd.DataFrame:
    frames = _parsed_frames(model, lang)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    group_cols = [c for c in ("task", "lang", "axis", "profile_id", "question_variant_id") if c in df.columns]
    return build_pair_table(df, group_cols=group_cols)


def _mean_delta_for_model(model: str, lang: str | None = None) -> float:
    return mean_delta_pct(_pairs_for_model(model, lang))


def _violation_for_model(model: str, lang: str) -> float:
    pct, _, _ = violation_at(_pairs_for_model(model, lang), tau=10.0)
    return pct


def build_main_mean_relative_pair_gap() -> pd.DataFrame:
    def _model_row(model: str) -> dict[str, object]:
        # Build pair tables once per language — reuse for both mean_delta and violation
        pt_en = _pairs_for_model(model, "en")
        pt_hi = _pairs_for_model(model, "hinglish")

        en_mean  = mean_delta_pct(pt_en)
        hi_mean  = mean_delta_pct(pt_hi)

        # Overall = mean across both languages (avoids re-loading 10 frames)
        all_deltas = pd.concat(
            [pt_en[["delta_pct"]], pt_hi[["delta_pct"]]], ignore_index=True
        ) if not pt_en.empty or not pt_hi.empty else pd.DataFrame()
        overall = float(all_deltas["delta_pct"].dropna().mean()) if not all_deltas.empty else float("nan")

        en_viol,  _, _ = violation_at(pt_en, tau=10.0)
        hi_viol,  _, _ = violation_at(pt_hi, tau=10.0)

        return {
            "Model":                   MODEL_DISPLAY.get(model, model),
            "model_slug":              model,
            "Overall Mean Delta%":     overall,
            "English Mean Delta%":     en_mean,
            "Hinglish Mean Delta%":    hi_mean,
            "English Violation@10%":   en_viol,
            "Hinglish Violation@10%":  hi_viol,
        }

    # Parallelize across models — all load_parsed() calls hit the cache
    futures = [POOL.submit(_model_row, m) for m in MODELS]
    rows = [f.result() for f in futures]

    out = pd.DataFrame(rows)
    out = out.sort_values("Overall Mean Delta%", ascending=True, na_position="last").reset_index(drop=True)
    for col in [c for c in out.columns if c != "Model" and c != "model_slug"]:
        out[col] = out[col].round(2)
    return out


def _axis_pair_values(model: str, axis: str, lang: str) -> np.ndarray:
    frames: list[pd.DataFrame] = []
    for task, _ in TASKS:
        df = load_parsed(model, task, lang=lang)
        if df.empty:
            continue
        sub = df[df["axis"] == axis]
        if not sub.empty:
            sub = sub.copy()
            sub["task"] = task
            frames.append(sub)

    if not frames:
        return np.array([])

    df = pd.concat(frames, ignore_index=True)
    group_cols = [c for c in ("task", "profile_id", "question_variant_id") if c in df.columns]
    pt = build_pair_table(df, group_cols=group_cols)
    if pt.empty:
        return np.array([])
    return pt["delta_pct"].dropna().to_numpy(dtype=float)


def _fmt_axis_cell(mean: float, lo: float, hi: float, *, bold: bool) -> str:
    if np.isnan(mean):
        return "—"
    cell = f"{mean:.2f} [{lo:.2f}, {hi:.2f}]" if not np.isnan(lo) else f"{mean:.2f}"
    return f"**{cell}**" if bold else cell


def build_axiswise_mean_delta(lang: str) -> pd.DataFrame:
    # Parallelize the 54 (model × axis) bootstrap CI computations
    def _cell(model: str, axis: str) -> tuple[str, str, float, float, float]:
        values = _axis_pair_values(model, axis, lang)
        if len(values) == 0:
            return model, axis, np.nan, np.nan, np.nan
        mean = float(values.mean())
        lo, hi = bootstrap_mean_ci(values, seed_str=f"axis-md:{model}:{axis}:{lang}")
        return model, axis, mean, float(lo), float(hi)

    numeric: dict[str, dict[str, tuple[float, float, float]]] = {
        m: {} for m in MODELS
    }
    futures = [
        POOL.submit(_cell, m, ax)
        for m in MODELS for ax in AXES
    ]
    for future in as_completed(futures):
        model, axis, mean, lo, hi = future.result()
        numeric[model][axis] = (mean, lo, hi)

    best_idx: dict[str, str] = {}
    for axis in AXES:
        valid = {m: numeric[m][axis][0] for m in MODELS
                 if axis in numeric[m] and not np.isnan(numeric[m][axis][0])}
        if valid:
            best_idx[axis] = min(valid, key=valid.get)

    rows: list[dict[str, str]] = []
    for model in MODELS:
        row: dict[str, str] = {"Model": MODEL_DISPLAY.get(model, model)}
        means: list[float] = []
        for axis in AXES:
            mean, lo, hi = numeric[model].get(axis, (np.nan, np.nan, np.nan))
            if not np.isnan(mean):
                means.append(mean)
            row[axis] = _fmt_axis_cell(mean, lo, hi, bold=best_idx.get(axis) == model)
        row["Mean Delta%"] = f"{np.mean(means):.2f}" if means else "—"
        rows.append(row)

    return pd.DataFrame(rows)


def main() -> None:
    TABLES_DIR.mkdir(parents=True, exist_ok=True)

    dataset_stats = build_dataset_statistics()
    dataset_stats.to_csv(TABLES_DIR / "table_01_dataset_composition.csv", index=False)

    main_gap = build_main_mean_relative_pair_gap()
    main_gap.to_csv(TABLES_DIR / "table_02_main_results.csv", index=False)

    lang_out = {"en": "table_03_axiswise_mean_delta_en.csv", "hinglish": "table_04_axiswise_mean_delta_hinglish.csv"}
    # Run both language tables concurrently
    futures = {POOL.submit(build_axiswise_mean_delta, lang): lang for lang in LANGS}
    for future in as_completed(futures):
        lang = futures[future]
        future.result().to_csv(TABLES_DIR / lang_out[lang], index=False)


if __name__ == "__main__":
    main()
