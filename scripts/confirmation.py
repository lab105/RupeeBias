"""
confirmation.py — Cost / time helpers for the runner's pre-run prompt.

Imported by `runner/confirmation.py`. The on-screen prompt itself lives there;
this module just provides MODEL_PRICING + the two estimator helpers.
"""

import logging

log = logging.getLogger(__name__)


# Pricing table: (input_tokens_per_req, output_tokens_per_req,
#                 input_price_per_M_USD, output_price_per_M_USD).
# Derived from each provider's published OpenRouter pricing at evaluation
# time and the empirical token usage observed in our smoke runs. Used only
# for the pre-run cost estimate; not normative.
MODEL_PRICING = {
    "google/gemini-3-flash":     (180,  6, 0.5, 3),
    "openai/gpt-5.4":            (180, 10, 2.50,  15.00),
    "openai/gpt-5.4-mini":       (180, 10, 0.75,  4.5),
    "moonshotai/kimi-k2.5":      (180, 10, 0.44,  2.00),
    "deepseek/deepseek-v3.2":    (180, 15, 0.252 , 0.378),
    "anthropic/claude-haiku-4.5":(220, 13, 1.00,  5.00),
    "anthropic/claude-opus-4.7": (310, 13, 5.00, 25.00),
    "z-ai/glm-5.1":              (180,  6, 1.05,  3.5),
    "sarvam-105b":               (180, 2500, 0.04, 0.13 )
}


def _calculate_cost(model: str, dataset_size: int) -> float:
    """Estimated total USD cost for one model × dataset run."""
    if model not in MODEL_PRICING or dataset_size <= 0:
        return 0.0
    in_tok, out_tok, in_price, out_price = MODEL_PRICING[model]
    total_in_M  = dataset_size * in_tok  / 1_000_000
    total_out_M = dataset_size * out_tok / 1_000_000
    return total_in_M * in_price + total_out_M * out_price


def _estimate_time(dataset_size: int) -> str:
    """Rough wall-clock estimate at ~1 s/prompt (post-rate-limit average)."""
    if dataset_size <= 0:
        return "—"
    total_seconds = dataset_size  # 1 s/prompt is a coarse approximation
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    return f"{int(hours)}h {int(minutes)}m" if hours else f"{int(minutes)}m"
