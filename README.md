# RupeeBias: Auditing Demographic Bias in Indian Economic Guidance from Large Language Models

Individuals turn to large language models for guidance across economic tasks — salary negotiation, service pricing, loan comparison — and biased outputs may shape what users believe they are worth or ask for. RupeeBias is a benchmark of 39,150 matched counterfactual prompts covering six India-specific demographic axes (caste, religion, regional identity, gender, disability, urban–rural location) across five economic tasks in both English and Hinglish. Evaluating nine LLMs, we find that for otherwise identical prompts differing only in demographic identifier, model outputs differ by 20.2% on average.

This repository contains:

- **The dataset construction pipeline** — generators that produce 39,150
  matched counterfactual prompts across five tasks and two languages
  (see [`DATASET_CARD.md`](DATASET_CARD.md)).
- **The evaluation runner** — an asynchronous LLM batch runner with
  built-in resume, retry, and validation tooling.
- **An evaluation card** for the nine LLMs benchmarked in the paper
  (see [`MODEL_CARD.md`](MODEL_CARD.md)).


## The Five Tasks

| Task ID                          | Decision                                   | Outcome format       |
|----------------------------------|--------------------------------------------|----------------------|
| `salary_estimation`              | Salary expectation for a fresher placement | `### <NUMBER> INR`   |
| `salary_increment_estimation`    | Annual increment for an existing employee  | `### <NUMBER> %`     |
| `counter_offer_recommendation`   | Counter-offer given a received offer       | `### <NUMBER> INR`   |
| `service_pricing_vendor`         | Freelance project price — vendor side      | `### <NUMBER> INR`   |
| `service_pricing_client`         | Freelance project price — client side      | `### <NUMBER> INR`   |

---

## Requirements

### Hardware Requirements

Minimum recommended hardware:

| Resource | Minimum |
|---|---:|
| CPU | 1 core |
| RAM | 1 GB |
| Disk space | 2 GB free disk space for cloning the repository and storing generated files |
| Network | Internet access required for API-based model evaluation |

### Software Requirements

| Dependency | Requirement |
|---|---|
| Python | Python 3.12 |
| Package manager | [`uv`](https://docs.astral.sh/uv/) installed |
| API provider | OpenRouter or another OpenAI-compatible endpoint |
| API credentials | OpenRouter API key and API endpoint configured in `.env` (required only for re-running evaluations) |

The evaluation runner requires an OpenAI-compatible API endpoint. During development, we used OpenRouter:

```env
OPENAI_API_KEY=<your OpenRouter key>
OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

Sarvam runs use the same OpenAI-compatible client surface, but with Sarvam
credentials and base URL:

```env
# For Sarvam-only runs, set these instead of the OpenRouter values.
OPENAI_API_KEY=<your Sarvam API key>
OPENAI_BASE_URL=https://api.sarvam.ai/v1
```

Run Sarvam separately from OpenRouter-hosted models unless your gateway can
serve both sets of model IDs from one endpoint. The runner detects model IDs
containing `sarvam` and sends the Sarvam-compatible request body.

### Tested Environments

| Operating System | Status |
|---|---|
| macOS | Verified |
| Ubuntu 26.04 LTS | Verified |

---

## Installation

This project uses [uv](https://docs.astral.sh/uv/) for dependency management. If you don't have it, follow the [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

```bash
uv sync                              # creates .venv and installs dependencies
source .venv/bin/activate
```

---

## Reproducing Results

### Reproduce paper tables and figures (recommended)

**⚠️ Note:** Precomputed model outputs are included in `runs/` for all nine models across all five tasks.
You do **not** need to run the full model evaluation pipeline. Simply run:

```bash
python -m analysis.run              # full run — all tables + appendix figures (~10 min)
python -m analysis.run --main-only  # main results only — 2 tables + 4 figures
python -m analysis.run --workers 8  # increase parallelism (default: 4 workers)
```

All jobs run in parallel via `ThreadPoolExecutor`. Output is written to `paper_analysis/{tables,figures}/`.

**`--main-only` outputs (paper main section):**

| Paper item | Output file |
|---|---|
| Table 1 — Dataset composition | `tables/table_01_dataset_composition.csv` |
| Table 2 — Mean Δ% & V@10% leaderboard | `tables/table_02_main_results.csv` |
| Table 5/6 — Axis-wise Kendall's W (EN + Hinglish) | `tables/table_05_friedman_leaderboard_en.csv`, `tables/table_06_friedman_leaderboard_hinglish.csv` |
| Figure 2 — Radar: axis-wise Mean Δ% by model | `figures/figure_02_radar_axis_mean_delta.png` |
| Figure 3a — Kendall's W by model & language | `figures/figure_03a_kendalls_w_by_model.png` |
| Figure 3b — Quadrant: Mean Δ% vs Kendall's W | `figures/figure_03b_quadrant_bias_consistency.png` |
| Figure 4a/b — Identifier deviation (religion, gender) | `figures/figure_04a_identifier_deviation_religion.png`, `figures/figure_04b_identifier_deviation_gender.png` |
| Figure 9a/b — Identifier deviation (caste, region) | `figures/figure_09a_identifier_deviation_caste.png`, `figures/figure_09b_identifier_deviation_region.png` |
| Figure 10a/b — Identifier deviation (disability, urban/rural) | `figures/figure_10a_identifier_deviation_disability.png`, `figures/figure_10b_identifier_deviation_urban_rural.png` |

**Full run additional outputs (appendix):**

| Paper item | Output file |
|---|---|
| Table 3 — Axis-wise Mean Δ% (EN) | `tables/table_03_axiswise_mean_delta_en.csv` |
| Table 4 — Axis-wise Mean Δ% (Hinglish) | `tables/table_04_axiswise_mean_delta_hinglish.csv` |
| Table 7 — Language moderation (Spearman ρ) | `tables/table_07_language_moderation.csv` |
| Table 8 — QV robustness (EN) | `tables/table_08_qv_robustness_en.csv` |
| Table 9 — QV robustness (Hinglish) | `tables/table_09_qv_robustness_hinglish.csv` |
| Table 23 — Parse health & refusal rate | `tables/table_23_parse_health.csv` |
| Figure 5a/b — Use-case-wise Mean Δ% (EN + Hinglish) | `figures/figure_05a_mean_delta_by_usecase_en.png`, `figures/figure_05b_mean_delta_by_usecase_hinglish.png` |
| Figure 6a/b — Use-case-wise Kendall's W (EN + Hinglish) | `figures/figure_06a_friedman_by_usecase_en.png`, `figures/figure_06b_friedman_by_usecase_hinglish.png` |
| Figure 7 — CPG heatmap | `figures/figure_07_cpg_heatmap.png` |
| Figure 8 — MOG heatmap | `figures/figure_08_mog_heatmap.png` |
| Figure 11a/b — Merit sensitivity (EN + Hinglish) | `figures/figure_11a_merit_sensitivity_en.png`, `figures/figure_11b_merit_sensitivity_hinglish.png` |
| Figure 12a/b — Profile rank agreement (EN + Hinglish) | `figures/figure_12a_profile_rank_agreement_en.png`, `figures/figure_12b_profile_rank_agreement_hinglish.png` |
| Figure 13a/b — Fairness-instruction ablation (EN + Hinglish) | `figures/figure_13a_fairness_ablation_en.png`, `figures/figure_13b_fairness_ablation_hinglish.png` |

### Re-run the full evaluation pipeline (optional, advanced)

> **⚠️ Cost warning:** Running the full evaluation across all nine models and five tasks incurs ~$300 in API costs. Use the precomputed outputs above unless you have a specific reason to re-run.

If you want to regenerate outputs from scratch (e.g., with new models or prompts):

```bash
# Smoke test first — verify your setup before committing to a full run
python main.py -m openai/gpt-5.4 --tasks salary_estimation --smoke-test
```

Once satisfied:

```bash
# 1. Configure API credentials
cp .env.sample .env  # fill in your OpenRouter key

# 2. Generate all prompts
./scripts/generate_datasets.sh

# 3. Run all OpenRouter-configured models on all tasks
python main.py -m all --tasks \
  salary_estimation,salary_increment_estimation,counter_offer_recommendation,service_pricing_vendor,service_pricing_client

# 4. Optional: run Sarvam separately (see Requirements for Sarvam credentials)
OPENAI_API_KEY=<your Sarvam API key> OPENAI_BASE_URL=https://api.sarvam.ai/v1 \
python main.py -m sarvam-105b --tasks \
  salary_estimation,salary_increment_estimation,counter_offer_recommendation,service_pricing_vendor,service_pricing_client

# 5. Revalidate outputs task-by-task
python scripts/revalidate.py --task salary_estimation --yes
python scripts/revalidate.py --task salary_increment_estimation --yes
python scripts/revalidate.py --task counter_offer_recommendation --yes
python scripts/revalidate.py --task service_pricing_vendor --yes
python scripts/revalidate.py --task service_pricing_client --yes

# 6. Retry validation failures task-by-task
python main.py --retry --tasks salary_estimation,salary_increment_estimation,counter_offer_recommendation,service_pricing_vendor,service_pricing_client --skip-confirmation
```

Output lands at `runs/<model_slug>/<task>/<stem>_<model_slug>_<temp>.jsonl` for full runs,
or `smoke-test-runs/<model_slug>/<task>/...` for smoke tests.

The pre-run confirmation prints the exact file, model, task, and system
prompt being used so you can sanity-check before any tokens are spent.

---

## Leaderboard Results

_Reproduced by `python -m analysis.run --main-only`; output at `paper_analysis/tables/table_02_main_results.csv`._

We evaluate nine LLMs on RupeeBias using two primary disparity metrics: Mean Relative Pair Gap (Mean Δ%) and Violation@10%. Mean Δ% measures the average symmetric percentage difference between
 outputs for matched counterfactual prompts differing only in demographic identifier. Violation@10% reports the percentage of matched counterfactual pairs where the relative output gap exceeds 10%.

 | Model | Overall Mean Δ% | English Mean Δ% | Hinglish Mean Δ% | English V@10% | Hinglish V@10% |
 |---|---:|---:|---:|---:|---:|
 | Gemini 3 Flash | 8.11 [8.06, 8.17] | 8.31 [8.22, 8.39] | 7.92 [7.85, 8.00] | 25.23 [25.02, 25.44] | 24.14 [23.94, 24.35] |
 | Claude Haiku 4.5 | 11.78 [11.59, 11.96] | 14.29 [14.02, 14.55] | 9.25 [9.01, 9.49] | 19.32 [19.12, 19.53] | 18.88 [18.67, 19.08] |
 | Claude Opus 4.7 | 11.98 [11.89, 12.06] | 12.53 [12.40, 12.65] | 11.30 [11.21, 11.41] | 31.96 [31.75, 32.17] | 36.04 [35.80, 36.28] |
 | Kimi K2.5 | 13.52 [13.41, 13.65] | 11.72 [11.58, 11.87] | 15.24 [15.04, 15.42] | 27.11 [26.90, 27.32] | 29.22 [29.01, 29.43] |
 | GLM 5.1 | 18.46 [18.25, 18.67] | 16.48 [16.05, 16.87] | 20.42 [20.25, 20.59] | 43.17 [42.94, 43.41] | 45.60 [45.37, 45.84] |
 | GPT 5.4 | 18.97 [18.86, 19.07] | 18.94 [18.78, 19.09] | 19.00 [18.86, 19.14] | 52.31 [52.08, 52.54] | 53.66 [53.43, 53.89] |
 | GPT 5.4-mini | 28.48 [28.33, 28.62] | 29.98 [29.74, 30.20] | 26.89 [26.70, 27.08] | 64.29 [64.08, 64.51] | 63.33 [63.10, 63.56] |
 | DeepSeek V3.2 | 32.68 [32.50, 32.86] | 26.71 [26.46, 26.96] | 38.66 [38.38, 38.93] | 49.04 [48.80, 49.29] | 59.73 [59.49, 59.97] |
 | Sarvam 105B | 37.93 [37.81, 38.06] | 39.84 [39.66, 40.04] | 35.95 [35.77, 36.13] | 77.46 [77.27, 77.65] | 74.69 [74.48, 74.89] |

**Notes**
 - Models are sorted by Overall Mean Δ%, computed across both English and Hinglish prompts.
 - Lower Mean Δ% indicates smaller average demographic output gaps.
 - Lower V@10% indicates fewer matched counterfactual pairs with a gap above 10%.
 - Gemini 3 Flash has the lowest Overall Mean Δ%.
 - Claude Haiku 4.5 has the lowest Violation@10% in both English and Hinglish.

---

## Repository Layout

```text
.
├── main.py                       # thin CLI: parses args → builds RunConfig → runner.run()
├── runner/                       # async batch-runner package
│   ├── client.py                 # AsyncOpenAI wrapper + HTTP retry
│   ├── orchestrator.py           # fan-out, drain-on-terminate, save partial
│   ├── retry.py                  # in-place ERROR retry loop with inline validation
│   ├── resume.py                 # input ↔ output diff
│   ├── confirmation.py           # pre-run prompt
│   ├── validation_hook.py        # bypass-aware terminate decisions
│   └── config.py / row.py / io.py
├── scripts/
│   ├── validation.py             # per-task format checkers
│   ├── revalidate.py             # standalone re-validator (single + bulk)
│   ├── confirmation.py           # cost / time pre-run helpers
│   ├── generate_datasets.sh      # wrapper that runs every dataset_construction/*.py
│   └── run_evaluations.sh
├── analysis/
│   ├── config.py                 # paths, model list, color schemes, canonical pairs
│   ├── io.py                     # task-aware run loading + shared load_parsed()
│   ├── metrics/                  # pair gaps, canonical gaps, omnibus tests, CIs
│   ├── figures/                  # paper figure generators
│   ├── tables/                   # paper table generators
│   └── run.py                    # builds paper_analysis/{tables,figures}
├── dataset_construction/         # prompt generators + generated JSONL
│   ├── salary_estimation/
│   ├── salary_increment_estimation/
│   ├── counter_offer_recommendation/
│   ├── service_pricing_vendor/
│   ├── service_pricing_client/
│   └── generate_<task>_{en,hinglish}.py
├── runs/                         # precomputed model outputs (9 models × 5 tasks)
│   ├── claude-opus-4.7/
│   ├── claude-haiku-4.5/
│   ├── gpt-5.4/
│   ├── gpt-5.4-mini/
│   ├── gemini-3-flash/
│   ├── kimi-k2.5/
│   ├── deepseek-v3.2/
│   ├── glm-5.1/
│   └── sarvam-105b/
├── paper_analysis/               # generated analysis tables and figures
│   ├── tables/
│   └── figures/
├── tests/                        # pytest suite
├── DATASET_CARD.md               # dataset documentation
├── MODEL_CARD.md                 # evaluation card for the 9 LLMs
└── README.md                     # this file
```

---

## Evaluation Workflow

The evaluation pipeline is a four-stage cycle:

```text
generate  →  run  →  revalidate  →  retry  →  (loop revalidate / retry until clean)
```

### 1. Run

`main.py` orchestrates the runner. Useful flags:

| Flag | Effect |
|---|---|
| `-m / --models` | comma-separated model IDs or `all` |
| `--tasks` | comma-separated task identifiers |
| `-t / --temperature` | sampling temperature (default `0.0`) |
| `--rate-limit` | concurrent in-flight requests (default `60`) |
| `--max-tokens` | response length cap |
| `--reasoning-effort` | `none` / `minimal` / `low` / `medium` / `high` / `xhigh` |
| `--resume` | diff input ↔ output, run only missing rows |
| `--smoke-test [N]` | sample N rows (default 5); auto-uses `smoke-test-runs/` |
| `--fair` | append a fairness instruction block; tags output `*_fairness_*` |
| `--no-terminate LIST` | disable specific termination paths |
| `--skip-confirmation` | skip the per-run confirmation prompt |
| `-o / --output-dir` | output directory (default: `runs`, or `smoke-test-runs` for `--smoke-test`) |

### 2. Revalidate (mark format / range failures as ERROR)

`scripts/revalidate.py` re-runs the format validator on saved outputs and
rewrites any row whose response is a hard failure (truncation, format
error, amount below floor) as `ERROR: Validation failed [...]`.

```bash
# Single file
python scripts/revalidate.py runs/gpt-5.4/salary_estimation/salary_estimation_en_gpt-5.4_0.0.jsonl

# Bulk: every file under runs/*/<task>/
python scripts/revalidate.py --task salary_estimation
python scripts/revalidate.py --task salary_estimation --yes        # skip confirmation
```

Bulk mode prefers `_retried` siblings when both exist, and skips
smoke / test / already-revalidated files.

### 3. Retry (rerun the ERROR rows)

Single file:

```bash
python main.py --retry-file runs/gpt-5.4/salary_estimation/salary_estimation_en_gpt-5.4_0.0_revalidated.jsonl
```

Bulk:

```bash
python main.py --retry --tasks salary_estimation                          # walks runs/*/salary_estimation/
python main.py --retry --tasks salary_estimation,counter_offer_recommendation --skip-confirmation
```

The retry tool **validates each retried response inline** (including
`finish_reason="length"` truncation) and, if the retry still fails,
optionally loops up to `max_rounds` times. Validation severity is
written into the output's `validation_status` / `validation_severity` /
`validation_reason` columns.

### 4. Resume (continue an interrupted run)

```bash
python main.py -m openai/gpt-5.4 --tasks salary_estimation --resume
```

Diffs the input file's `id`s against the prior output, runs only the
missing rows, then merges with the prior output and saves back to the
same path.

### 5. Validation

Every response is validated by [`scripts/validation.py`](scripts/validation.py).
Three severities:

| Severity | Action |
|---|---|
| `valid` | row kept |
| `flag` | warning logged; row kept |
| `terminate` | runner stops dispatching new requests; in-flight requests drain; remaining rows marked `ERROR: Batch Terminated due to {reason}`; everything saved |

`terminate` triggers (per row):

- **Truncation** — API returned null content, `finish_reason="length"`, or the response ends with `...`.
- **Format error** — missing `###`, wrong unit, range format, etc.
- **Amount below floor** —
  `salary_estimation` / `counter_offer_recommendation`: `< ₹1L`.
  `service_pricing_vendor` / `service_pricing_client`: `< ₹1K`.
  `salary_increment_estimation`: `< 0%`.

`flag` triggers — refusals, whitespace deltas, negative values, amounts
above ceiling — are tracked for analysis but do not stop the batch.

Batch-level termination thresholds (refusal rate > 10 %, consecutive
failures > 10 — timeouts count) can each be disabled individually via
`--no-terminate <list>`.

---

## Tests

```bash
uv run pytest tests/
```

Coverage includes:

- runner config + bypass-list parsing
- per-row pair construction and metric helpers
- per-task validation severity rules
- orchestrator drain-on-terminate behaviour
- in-place retry with validation
- input ↔ output diff for resume
