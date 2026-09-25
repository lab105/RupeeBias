# Model Evaluation Card - RupeeBias


## Models Evaluated

All models are accessed at temperature `0.0`. Most models use OpenRouter (shown in pricing below). Sarvam models use the Sarvam API endpoint directly.

| Slug | Provider | Model ID | Access | License | $/M in | $/M out |
|---|---|---|---|---|---|---|
| `claude-opus-4.7`   | Anthropic   | `anthropic/claude-opus-4.7`   | OpenRouter | Closed | 5.00  | 25.00 |
| `claude-haiku-4.5`  | Anthropic   | `anthropic/claude-haiku-4.5`  | OpenRouter | Closed |  1.00  |  5.00 |
| `gemini-3-flash`    | Google      | `google/gemini-3-flash`       | OpenRouter | Closed |  0.5 |  3.00 |
| `gpt-5.4`           | OpenAI      | `openai/gpt-5.4`              | OpenRouter | Closed |  2.50  | 15.00 |
| `gpt-5.4-mini`      | OpenAI      | `openai/gpt-5.4-mini`         | OpenRouter | Closed |  0.75  |  4.5 |
| `glm-5.1`           | Z.ai        | `z-ai/glm-5.1`                | OpenRouter | Open   |  1.05  |  3.5 |
| `kimi-k2.5`         | Moonshot    | `moonshotai/kimi-k2.5`        | OpenRouter | Open   |  0.44  |  2.00 |
| `deepseek-v3.2`   | DeepSeek    | `deepseek/deepseek-v3.2`    | OpenRouter | Open   |  0.252 |  0.378 |
| `sarvam-105b` | Sarvam AI | `sarvam-105b` | Sarvam API | Open | 0.04 | 0.13 |

## Evaluation Setup

- **Dataset**: `dataset_construction/<task>/<task>_{en,hinglish}.jsonl`
  for each of the five tasks.
- **Prompt**: per-task system prompt (see `main.py:TASK_PROMPTS`) +
  the row's `prompt` field as the user message.
- **Temperature**: 0.0
- **Reasoning**: `none` (orthogonal reasoning-mode results live in
  appendix in the paper).
- **Fairness toggle**: an optional fairness instructions block — *"Please
  ensure your response is fair and unbiased."* — is appended to the system
  prompt when `--fair` is passed; results land in `*_fairness_*.jsonl`.

## Running Evaluations

### Running OpenRouter models

Configure `.env` with OpenRouter credentials (see README Quickstart):

```env
OPENAI_API_KEY=<your OpenRouter key>
OPENAI_BASE_URL=https://openrouter.ai/api/v1
```

Then run any model evaluation:

```bash
# Single model
python main.py -m anthropic/claude-opus-4.7 --tasks salary_estimation

# All OpenRouter models
python main.py -m all --tasks salary_estimation,salary_increment_estimation,counter_offer_recommendation,service_pricing_vendor,service_pricing_client
```

### Running Sarvam models

**Important:** Sarvam models require separate configuration and should be run independently
from OpenRouter models (unless your gateway can serve both sets of model IDs).

1. **Set Sarvam credentials in `.env`:**

```env
OPENAI_API_KEY=<your Sarvam API key>
OPENAI_BASE_URL=https://api.sarvam.ai/v1
```

2. **Run Sarvam models:**

```bash
# Sarvam on a single task
python main.py -m sarvam-105b --tasks salary_estimation

# Sarvam on all tasks
python main.py -m sarvam-105b --tasks \
  salary_estimation,salary_increment_estimation,counter_offer_recommendation,service_pricing_vendor,service_pricing_client
```

The runner automatically detects `sarvam` in the model ID and sends Sarvam-compatible requests.
