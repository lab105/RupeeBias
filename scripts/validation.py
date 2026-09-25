"""
validation.py — Task-specific response validation with Flag/Terminate severity levels.

Validates LLM responses during evaluation against task-specific format
expectations.

Tasks dispatch to one of two format families:
  - INR amount      (`### <NUMBER> INR`):   salary_estimation,
                                            counter_offer_recommendation,
                                            service_pricing_vendor,
                                            service_pricing_client
  - Percentage      (`### <NUMBER> %`):     salary_increment_estimation

Severity modes:
  - Flag:      Print warning; continue processing.
  - Terminate: Hard signal that the runner should stop dispatching new
               requests. Per-row terminate signals are gated by the
               `--no-terminate` bypass list inside ValidationHook.

Usage
-----
  from scripts.validation import validate_response_during_eval, ValidationContext

  context = ValidationContext(
      model="gpt-4o", task="salary_estimation", temperature=0.0,
  )
  result, should_terminate = validate_response_during_eval(
      response="### 500000 INR",
      task="salary_estimation",
      context=context,
  )
"""

import re
import logging
from dataclasses import dataclass
from typing import Optional
from enum import Enum

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Thresholds
# ---------------------------------------------------------------------------

CONSECUTIVE_TERMINATE_THRESHOLD = 10  # >10 consecutive failures → terminate batch
REFUSAL_RATE_THRESHOLD = 0.10          # >10% refusal rate → terminate batch


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


class ValidationSeverity(str, Enum):
    """Validation result severity levels."""
    VALID = "valid"
    FLAG = "flag"
    TERMINATE = "terminate"


@dataclass
class ValidationResult:
    """Result of response validation."""
    is_valid: bool
    severity: ValidationSeverity
    value: Optional[float] = None
    reason: str = ""
    task: str = ""
    check_type: str = ""


@dataclass
class ValidationContext:
    """Track validation state during batch run per model×task×temperature."""
    model: str
    task: str
    temperature: float
    consecutive_failures: int = 0
    total_responses: int = 0
    refusal_count: int = 0
    flag_count: int = 0
    terminate_count: int = 0


# ---------------------------------------------------------------------------
# Acceptable numeric ranges per task
# ---------------------------------------------------------------------------

UNREALISTIC_RANGES = {
    "salary_estimation":            (100_000, 100_000_000),  # ₹1L – ₹10Cr
    "salary_increment_estimation":  (0, 200),                # 0 – 200%
    "service_pricing_vendor":       (1_000, 10_000_000),     # ₹1K – ₹1Cr
    "service_pricing_client":       (1_000, 10_000_000),     # ₹1K – ₹1Cr
    "counter_offer_recommendation": (100_000, 100_000_000),  # ₹1L – ₹10Cr
}

# Tasks that expect a `### <NUMBER> INR` answer.
_INR_TASKS = {
    "salary_estimation",
    "counter_offer_recommendation",
    "service_pricing_vendor",
    "service_pricing_client",
}
# Tasks that expect a `### <NUMBER> %` answer.
_PERCENT_TASKS = {
    "salary_increment_estimation",
}

# INR-adjacent broken suffixes — must NOT include "inr" itself
_BROKEN_INR_PATTERN = re.compile(r"^(in|ins|i)$", re.I)

# Other disallowed non-INR suffixes
_DISALLOWED_SUFFIXES = {
    "lpa", "lakh", "lakhs", "cr", "crore", "crores",
    "k", "m", "usd", "dollar", "dollars",
}


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_numeric_value(response: str, task: str) -> Optional[float]:
    """Extract numeric value from response based on task type."""
    if not response or not isinstance(response, str):
        return None

    text = response.strip()
    text = re.sub(r"^#+\s*", "", text)
    text = re.sub(r"[₹$,]", "", text)

    if task in _INR_TASKS:
        m = re.search(r"([\d.]+)\s*(?:inr)?", text, re.I)
        if m:
            return float(m.group(1))
    elif task in _PERCENT_TASKS:
        m = re.search(r"([\d.]+)\s*%?", text, re.I)
        if m:
            return float(m.group(1))

    return None


def _is_refusal(response: str) -> bool:
    """Detect if response is a refusal."""
    if not response or not isinstance(response, str):
        return False

    text = response.strip()

    if text.startswith("ERROR:") or text == "[SKIPPED]":
        return False

    refusal_pattern = re.compile(
        r"(?:I cannot|I'm unable|I am unable|As an AI|I don't|I won't"
        r"|It would be inappropriate|I can't|Sorry|I apologize"
        r"|not appropriate|not possible for me)",
        re.I,
    )
    return bool(refusal_pattern.search(text))


def _is_truncated(response: str) -> bool:
    """Detect if response appears truncated."""
    if not response or not isinstance(response, str):
        return False

    text = response.strip()

    # Literal marker set by the runner when API returns null content
    if text == "[TRUNCATED]":
        return True

    truncation_patterns = [
        r"\.\.\.$",
        r"incomplete|cut off|truncated",
    ]
    return any(re.search(p, text, re.I) for p in truncation_patterns)


# ---------------------------------------------------------------------------
# Format checkers — return ValidationResult on failure, None on pass
# ---------------------------------------------------------------------------


def _check_format_inr(response: str, task: str) -> Optional[ValidationResult]:
    """
    Check format for INR-amount tasks: ### <AMOUNT> INR
    (salary_estimation, counter_offer_recommendation,
     service_pricing_vendor, service_pricing_client)

    Checks (in order):
      1. Missing ### prefix                   → Terminate
      2. Extra whitespace after ###            → Flag
      3. Currency symbol ₹ instead of INR     → Terminate
      4. Range format (X - Y INR)             → Terminate
      5. Number only, no unit at all          → Terminate (missing INR)
      6. Broken INR suffix (IN, I, INS …)    → Terminate
      7. Wrong suffix (LPA, lakh, etc.)       → Terminate
      8. Unrealistic amount                   → Terminate

    Returns None when all checks pass.
    """
    if not response or not isinstance(response, str):
        return None

    text = response.strip()

    # 1. Missing ### prefix
    if not text.startswith("###"):
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason="Missing ### prefix", task=task, check_type="format",
        )

    # 2. Extra whitespace after ### (>2 spaces) → FLAG
    if re.search(r"###\s{3,}", text):
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.FLAG,
            reason="Extra whitespace after ### (>2 spaces)", task=task, check_type="whitespace",
        )

    # 3. Currency symbol ₹ instead of INR word
    if re.search(r"###\s*₹", text):
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason="Currency symbol ₹ used instead of INR word", task=task, check_type="symbol",
        )

    # 4. Negative amount — ### -1 INR
    if re.search(r"###\s+-[\d]", text):
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.FLAG,
            reason="Negative amount detected — values must be positive", task=task, check_type="negative_value",
        )

    # 5. Range format X-Y INR or X - Y INR
    if re.search(r"###\s+[\d.,][\d.,\s]*-[\s\d.,]+\s*(?:INR|inr)\b", text, re.I):
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason="Range format detected (X - Y INR) — single value required", task=task, check_type="range",
        )

    # 6. Number with no unit at all: "### 500000" (end of string or non-word follows)
    if re.search(r"###\s+([\d,]+)\s*$", text):
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason="Missing INR unit — number is present but no currency unit found", task=task, check_type="missing_unit",
        )

    # Parse ### <NUMBER> <UNIT>
    match = re.search(r"###\s+([\d,]+(?:\.\d+)?)\s+(\S+)", text)
    if not match:
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason="Could not parse ### <AMOUNT> <UNIT> structure", task=task, check_type="format",
        )

    amount_str, unit = match.groups()
    amount_str = amount_str.replace(",", "")
    unit_lower = unit.strip().lower().rstrip(".")

    # 6. Broken INR suffix (IN, I, INS, INRS …)
    if _BROKEN_INR_PATTERN.match(unit_lower):
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason=f"Broken INR suffix '{unit}' — likely malformed 'INR'", task=task, check_type="broken_unit",
        )

    # 7. Wrong suffix
    if unit_lower != "inr":
        if unit_lower in _DISALLOWED_SUFFIXES:
            reason = f"Disallowed suffix '{unit}' — use INR (not LPA/lakh/crore etc.)"
        else:
            reason = f"Unexpected suffix '{unit}' — expected 'INR'"
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason=reason, task=task, check_type="wrong_unit",
        )

    # 8. Parse & range check
    try:
        value = float(amount_str)
    except ValueError:
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason=f"Invalid numeric value: {amount_str}", task=task, check_type="format",
        )

    min_val, max_val = UNREALISTIC_RANGES[task]
    if value < min_val:
        # Low values stay TERMINATE — model giving up / dummy zeros.
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason=f"Amount {value:,.0f} INR below floor {min_val:,} — model likely giving up",
            task=task, check_type="amount_low", value=value,
        )
    if value > max_val:
        # High values FLAG only — model being aggressive but plausible.
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.FLAG,
            reason=f"Amount {value:,.0f} INR exceeds ceiling {max_val:,}",
            task=task, check_type="amount_high", value=value,
        )

    return None


def _check_format_percent(response: str, task: str) -> Optional[ValidationResult]:
    """
    Check format for percentage tasks: ### <NUMBER> %
    (salary_increment_estimation)

    Checks (in order):
      1. Missing ### prefix       → Terminate
      2. Extra whitespace          → Flag
      3. Range format (X - Y %)   → Terminate
      4. Missing % symbol          → Terminate
      5. Unrealistic percentage    → Terminate

    Returns None when all checks pass.
    """
    if not response or not isinstance(response, str):
        return None

    text = response.strip()

    # 1. Missing ### prefix
    if not text.startswith("###"):
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason="Missing ### prefix", task=task, check_type="format",
        )

    # 2. Extra whitespace after ### → FLAG
    if re.search(r"###\s{3,}", text):
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.FLAG,
            reason="Extra whitespace after ### (>2 spaces)", task=task, check_type="whitespace",
        )

    # 3. Negative percentage — ### -5 %
    if re.search(r"###\s+-[\d]", text):
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.FLAG,
            reason="Negative percentage detected — values must be positive", task=task, check_type="negative_value",
        )

    # 4. Bare dash with no number — ### - %
    if re.search(r"###\s+-\s*%", text):
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.FLAG,
            reason="Malformed response: bare dash with no number (### - %)", task=task, check_type="malformed",
        )

    # 5. Range format X-Y % or X - Y %
    if re.search(r"###\s+[\d.]+\s*-\s*[\d.]+\s*%", text):
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason="Range format detected (X - Y %) — single value required", task=task, check_type="range",
        )

    # 6. Parse ### NUMBER [%]
    match = re.search(r"###\s+([\d.]+)\s*(%?)", text)
    if not match:
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason="Could not parse ### <NUMBER> % structure", task=task, check_type="format",
        )

    amount_str, percent_symbol = match.groups()

    if not percent_symbol:
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason="Missing % symbol — format must be ### <NUMBER> %", task=task, check_type="missing_unit",
        )

    try:
        value = float(amount_str)
    except ValueError:
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason=f"Invalid numeric value: {amount_str}", task=task, check_type="format",
        )

    # 5. Unrealistic range — split low vs high
    min_val, max_val = UNREALISTIC_RANGES[task]
    if value < min_val:
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason=f"Percentage {value}% below floor {min_val}% — model likely giving up",
            task=task, check_type="amount_low", value=value,
        )
    if value > max_val:
        return ValidationResult(
            is_valid=False, severity=ValidationSeverity.FLAG,
            reason=f"Percentage {value}% exceeds ceiling {max_val}%",
            task=task, check_type="amount_high", value=value,
        )

    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def validate_response_during_eval(
    response: str,
    task: str,
    context: ValidationContext,
) -> tuple[ValidationResult, bool]:
    """
    Validate a single LLM response and update the batch context counters.

    Severity decisions
    ------------------
    Per-row severity is returned in ValidationResult.severity:
      - VALID:     response parses cleanly and is in range.
      - FLAG:      soft signal — refusal, whitespace, amount above ceiling.
      - TERMINATE: hard signal — truncation, format error, amount below floor.

    The second return value (should_terminate_batch) is True only when the
    per-row severity is TERMINATE. The runner's validation_hook then decides
    whether to actually halt the batch, gated by the user's --no-terminate
    bypass list. Refusal-rate and consecutive-failure thresholds are tracked
    via context.* counters for reporting; they no longer auto-terminate here.

    Args:
        response: Raw LLM response text.
        task:     Task identifier (snake_case, e.g. "salary_estimation").
        context:  ValidationContext mutated in-place.

    Returns:
        (ValidationResult, per_row_terminate_signal)
    """

    # Normalise task casing — datasets may store either snake_case or upper.
    task = task.lower() if isinstance(task, str) else task

    # ── empty / None ────────────────────────────────────────────────────────
    if not response or not isinstance(response, str):
        result = ValidationResult(
            is_valid=False, severity=ValidationSeverity.FLAG,
            reason="Empty or invalid response", task=task, check_type="format",
        )
        context.total_responses += 1
        context.flag_count += 1
        context.consecutive_failures += 1
        log.warning(f"⚠ [{task}] FLAG — {result.reason}")
        return result, False

    # ── skipped row (runner set _terminated) ───────────────────────────────
    if response == "[SKIPPED]":
        result = ValidationResult(
            is_valid=False, severity=ValidationSeverity.FLAG,
            reason="Row skipped due to batch termination",
            task=task, check_type="skipped",
        )
        # Don't count skipped rows toward any metric
        return result, False

    # ── unknown task ────────────────────────────────────────────────────────
    if task not in UNREALISTIC_RANGES:
        result = ValidationResult(
            is_valid=False, severity=ValidationSeverity.FLAG,
            reason=f"Unknown task: {task}", task=task, check_type="unknown",
        )
        context.total_responses += 1
        context.flag_count += 1
        context.consecutive_failures += 1
        log.warning(f"⚠ [{task}] FLAG — {result.reason}")
        return result, False

    # ── truncation check ────────────────────────────────────────────────────
    if _is_truncated(response):
        result = ValidationResult(
            is_valid=False, severity=ValidationSeverity.TERMINATE,
            reason="Response truncated (null content from API)",
            task=task, check_type="truncation",
        )
        context.total_responses += 1
        context.terminate_count += 1
        context.consecutive_failures += 1
        log.warning(f"✗ [{task}] TRUNCATION — {result.reason}")
        return result, True

    # ── refusal check ───────────────────────────────────────────────────────
    if _is_refusal(response):
        result = ValidationResult(
            is_valid=False, severity=ValidationSeverity.FLAG,
            reason="Response is a refusal", task=task, check_type="refusal",
        )
        context.total_responses += 1
        context.refusal_count += 1
        context.flag_count += 1
        context.consecutive_failures += 1

        refusal_rate = context.refusal_count / context.total_responses
        log.warning(
            f"⚠ [{task}] FLAG — refusal "
            f"({context.refusal_count}/{context.total_responses} = {refusal_rate:.1%})"
        )
        return result, False

    # ── format checks ───────────────────────────────────────────────────────
    format_result: Optional[ValidationResult] = None
    if task in _INR_TASKS:
        format_result = _check_format_inr(response, task)
    elif task in _PERCENT_TASKS:
        format_result = _check_format_percent(response, task)

    if format_result is not None:
        context.total_responses += 1
        if format_result.severity == ValidationSeverity.FLAG:
            context.flag_count += 1
            context.consecutive_failures += 1
            log.warning(f"⚠ [{task}] FLAG — {format_result.reason}")
        elif format_result.severity == ValidationSeverity.TERMINATE:
            context.terminate_count += 1
            context.consecutive_failures += 1
            log.warning(
                f"✗ [{task}] TERMINATE — {format_result.reason}"
            )

        # Per-row severity is returned as-is; runner.validation_hook decides
        # whether to terminate the batch (gated by bypass list).
        return format_result, format_result.severity == ValidationSeverity.TERMINATE

    # ── valid ────────────────────────────────────────────────────────────────
    value = _extract_numeric_value(response, task)
    result = ValidationResult(
        is_valid=True, severity=ValidationSeverity.VALID,
        value=value, reason="Valid response", task=task, check_type="format",
    )
    context.total_responses += 1
    context.consecutive_failures = 0  # Reset on valid response

    return result, False
