"""Tests for validation.py — task-specific response validation."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.validation import (
    CONSECUTIVE_TERMINATE_THRESHOLD,
    ValidationContext,
    ValidationSeverity,
    validate_response_during_eval,
)


def _ctx(task: str = "salary_estimation") -> ValidationContext:
    return ValidationContext(model="gpt-4o", task=task, temperature=0.0)


# ---------------------------------------------------------------------------
# salary_estimation — ### AMOUNT INR
# ---------------------------------------------------------------------------

class TestSalaryEstimation:

    def test_valid(self):
        r, stop = validate_response_during_eval(
            "### 500000 INR", task="salary_estimation", context=_ctx())
        assert r.is_valid is True
        assert r.severity == ValidationSeverity.VALID
        assert stop is False

    def test_valid_lowercase_inr(self):
        r, _ = validate_response_during_eval(
            "### 500000 inr", task="salary_estimation", context=_ctx())
        assert r.is_valid is True

    def test_valid_trailing_space_on_unit(self):
        r, _ = validate_response_during_eval(
            "### 10000000 INR ", task="salary_estimation", context=_ctx())
        assert r.is_valid is True

    def test_below_range(self):
        r, _ = validate_response_during_eval(
            "### 12 INR", task="salary_estimation", context=_ctx())
        assert r.severity == ValidationSeverity.TERMINATE
        assert r.check_type == "amount_low"

    def test_above_range_flags_only(self):
        r, _ = validate_response_during_eval(
            "### 200000000 INR", task="salary_estimation", context=_ctx())
        assert r.severity == ValidationSeverity.FLAG
        assert r.check_type == "amount_high"

    def test_wrong_suffix(self):
        r, _ = validate_response_during_eval(
            "### 5 LPA", task="salary_estimation", context=_ctx())
        assert r.severity == ValidationSeverity.TERMINATE

    def test_missing_unit(self):
        r, _ = validate_response_during_eval(
            "### 500000", task="salary_estimation", context=_ctx())
        assert r.severity == ValidationSeverity.TERMINATE

    def test_currency_symbol(self):
        r, _ = validate_response_during_eval(
            "### ₹500000", task="salary_estimation", context=_ctx())
        assert r.severity == ValidationSeverity.TERMINATE

    def test_range_format(self):
        r, _ = validate_response_during_eval(
            "### 400000-600000 INR", task="salary_estimation", context=_ctx())
        assert r.severity == ValidationSeverity.TERMINATE

    def test_extra_whitespace_is_flag(self):
        r, stop = validate_response_during_eval(
            "###   500000 INR", task="salary_estimation", context=_ctx())
        assert r.severity == ValidationSeverity.FLAG
        assert stop is False


# ---------------------------------------------------------------------------
# salary_increment_estimation — ### NUMBER %
# ---------------------------------------------------------------------------

class TestSalaryIncrementEstimation:

    def test_valid(self):
        r, _ = validate_response_during_eval(
            "### 15 %", task="salary_increment_estimation",
            context=_ctx("salary_increment_estimation"))
        assert r.is_valid is True
        assert r.severity == ValidationSeverity.VALID

    def test_missing_percent(self):
        r, _ = validate_response_during_eval(
            "### 15", task="salary_increment_estimation",
            context=_ctx("salary_increment_estimation"))
        assert r.severity == ValidationSeverity.TERMINATE

    def test_wrong_suffix(self):
        r, _ = validate_response_during_eval(
            "### 15 INR", task="salary_increment_estimation",
            context=_ctx("salary_increment_estimation"))
        assert r.severity == ValidationSeverity.TERMINATE

    def test_range_format(self):
        r, _ = validate_response_during_eval(
            "### 10-20 %", task="salary_increment_estimation",
            context=_ctx("salary_increment_estimation"))
        assert r.severity == ValidationSeverity.TERMINATE

    def test_extra_whitespace_is_flag(self):
        r, _ = validate_response_during_eval(
            "###   15 %", task="salary_increment_estimation",
            context=_ctx("salary_increment_estimation"))
        assert r.severity == ValidationSeverity.FLAG


# ---------------------------------------------------------------------------
# service_pricing_{vendor,client} — ### AMOUNT INR (≥ ₹1K floor)
# ---------------------------------------------------------------------------

class TestServicePricingVendor:

    def test_valid(self):
        r, _ = validate_response_during_eval(
            "### 250000 INR", task="service_pricing_vendor",
            context=_ctx("service_pricing_vendor"))
        assert r.is_valid is True

    def test_below_range(self):
        r, _ = validate_response_during_eval(
            "### 500 INR", task="service_pricing_vendor",
            context=_ctx("service_pricing_vendor"))
        assert r.severity == ValidationSeverity.TERMINATE

    def test_above_range_flags(self):
        r, _ = validate_response_during_eval(
            "### 100000000 INR", task="service_pricing_vendor",
            context=_ctx("service_pricing_vendor"))
        assert r.severity == ValidationSeverity.FLAG
        assert r.check_type == "amount_high"


class TestServicePricingClient:

    def test_valid(self):
        r, _ = validate_response_during_eval(
            "### 250000 INR", task="service_pricing_client",
            context=_ctx("service_pricing_client"))
        assert r.is_valid is True

    def test_below_range(self):
        r, _ = validate_response_during_eval(
            "### 500 INR", task="service_pricing_client",
            context=_ctx("service_pricing_client"))
        assert r.severity == ValidationSeverity.TERMINATE


# ---------------------------------------------------------------------------
# counter_offer_recommendation — same shape as salary_estimation
# ---------------------------------------------------------------------------

class TestCounterOfferRecommendation:

    def test_valid(self):
        r, _ = validate_response_during_eval(
            "### 1500000 INR", task="counter_offer_recommendation",
            context=_ctx("counter_offer_recommendation"))
        assert r.is_valid is True

    def test_below_range(self):
        r, _ = validate_response_during_eval(
            "### 50000 INR", task="counter_offer_recommendation",
            context=_ctx("counter_offer_recommendation"))
        assert r.severity == ValidationSeverity.TERMINATE


# ---------------------------------------------------------------------------
# Truncation, refusal, edge cases
# ---------------------------------------------------------------------------

class TestTruncation:

    def test_marker_signals_terminate(self):
        ctx = _ctx()
        r, stop = validate_response_during_eval(
            "[TRUNCATED]", task="salary_estimation", context=ctx)
        assert r.severity == ValidationSeverity.TERMINATE
        assert r.check_type == "truncation"
        assert stop is True

    def test_ellipsis_terminates(self):
        r, stop = validate_response_during_eval(
            "### 500000 INR...", task="salary_estimation", context=_ctx())
        assert r.severity == ValidationSeverity.TERMINATE


class TestRefusal:

    def test_refusal_is_flag(self):
        ctx = _ctx()
        r, stop = validate_response_during_eval(
            "I cannot provide this information",
            task="salary_estimation", context=ctx)
        assert r.severity == ValidationSeverity.FLAG
        assert r.check_type == "refusal"
        assert stop is False
        assert ctx.refusal_count == 1


class TestEdgeCases:

    def test_empty_response(self):
        r, _ = validate_response_during_eval("", task="salary_estimation", context=_ctx())
        assert r.is_valid is False

    def test_none_response(self):
        r, _ = validate_response_during_eval(None, task="salary_estimation", context=_ctx())
        assert r.is_valid is False

    def test_unknown_task(self):
        r, _ = validate_response_during_eval(
            "### 500000 INR", task="not_a_task", context=_ctx("not_a_task"))
        assert r.is_valid is False
        assert r.check_type == "unknown"

    def test_uppercase_task_normalised(self):
        r, _ = validate_response_during_eval(
            "### 500000 INR", task="SALARY_ESTIMATION",
            context=_ctx("SALARY_ESTIMATION"))
        assert r.is_valid is True


class TestConsecutiveCounter:

    def test_valid_resets_counter(self):
        ctx = _ctx()
        for _ in range(4):
            validate_response_during_eval(
                "### 12 INR", task="salary_estimation", context=ctx)
        assert ctx.consecutive_failures == 4
        validate_response_during_eval(
            "### 500000 INR", task="salary_estimation", context=ctx)
        assert ctx.consecutive_failures == 0
