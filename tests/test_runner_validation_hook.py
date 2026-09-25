"""Tests for runner.validation_hook — bypass-list-aware termination decisions."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from runner.config import BypassChecks
from runner.validation_hook import ValidationHook
from scripts.validation import (
    CONSECUTIVE_TERMINATE_THRESHOLD,
    REFUSAL_RATE_THRESHOLD,
    ValidationSeverity,
)


def _hook(task: str = "salary_estimation", bypass=None):
    return ValidationHook(
        model="test", task=task, temperature=0.0,
        bypass=bypass or BypassChecks(),
    )


class TestPerRowTerminate:

    def test_valid_does_not_terminate(self):
        d = _hook().evaluate("### 500000 INR")
        assert d.result.is_valid
        assert not d.should_terminate

    def test_amount_low_terminates(self):
        d = _hook().evaluate("### 12 INR")
        assert d.should_terminate
        assert d.result.check_type == "amount_low"

    def test_amount_high_is_only_flag(self):
        d = _hook().evaluate("### 200000000 INR")
        assert d.result.severity == ValidationSeverity.FLAG
        assert not d.should_terminate

    def test_truncation_terminates(self):
        d = _hook().evaluate("[TRUNCATED]")
        assert d.should_terminate
        assert "truncation" in d.terminate_reason

    def test_format_error_terminates(self):
        d = _hook().evaluate("just plain text without prefix")
        assert d.should_terminate


class TestBypass:

    def test_bypass_amount_low(self):
        h = _hook(bypass=BypassChecks.parse("amount_low"))
        d = h.evaluate("### 12 INR")
        assert not d.should_terminate

    def test_bypass_truncation(self):
        h = _hook(bypass=BypassChecks.parse("truncation"))
        d = h.evaluate("[TRUNCATED]")
        assert not d.should_terminate

    def test_bypass_format(self):
        h = _hook(bypass=BypassChecks.parse("format"))
        d = h.evaluate("just text")
        assert not d.should_terminate

    def test_bypass_does_not_affect_other_paths(self):
        # Bypass amount_low only — truncation still terminates.
        h = _hook(bypass=BypassChecks.parse("amount_low"))
        d = h.evaluate("[TRUNCATED]")
        assert d.should_terminate

    def test_bypass_all(self):
        h = _hook(bypass=BypassChecks.parse("all"))
        for response in ("[TRUNCATED]", "### 12 INR", "garbage"):
            assert not h.evaluate(response).should_terminate


class TestRateThresholds:

    def test_refusal_rate_terminates(self):
        h = _hook()
        # 11 responses, 2 refusals → 18% rate > 10% threshold.
        # But amount_low/truncation never injected — only refusals + valid.
        for i in range(11):
            response = "I cannot help" if i < 2 else "### 500000 INR"
            d = h.evaluate(response)
            if i == 1:  # 2/2 = 100% rate at this point
                assert d.should_terminate
                return
        # Should have terminated by now
        assert False, "Expected termination by 2nd refusal"

    def test_refusal_rate_bypassed(self):
        h = _hook(bypass=BypassChecks.parse("refusal"))
        for _ in range(5):
            d = h.evaluate("I cannot help")
            assert not d.should_terminate

    def test_consecutive_terminates(self):
        # Use whitespace-FLAG to bump consecutive without triggering per-row
        # TERMINATE. That way only the consecutive threshold can fire.
        h = _hook()
        for i in range(CONSECUTIVE_TERMINATE_THRESHOLD + 2):
            d = h.evaluate("###   500000 INR")  # FLAG: extra whitespace
            if i > CONSECUTIVE_TERMINATE_THRESHOLD:
                assert d.should_terminate
                return
        assert False, "Expected consecutive-threshold termination"

    def test_consecutive_bypassed(self):
        h = _hook(bypass=BypassChecks.parse("consecutive"))
        for _ in range(CONSECUTIVE_TERMINATE_THRESHOLD + 5):
            d = h.evaluate("###   500000 INR")
            assert not d.should_terminate


class TestTimeoutTracking:

    def test_timeout_counts_as_consecutive(self):
        h = _hook()
        for _ in range(3):
            h.record_timeout()
        assert h.context.consecutive_failures == 3

    def test_timeout_bypassed_does_not_count(self):
        h = _hook(bypass=BypassChecks.parse("timeout"))
        for _ in range(3):
            h.record_timeout()
        assert h.context.consecutive_failures == 0

    def test_enough_timeouts_terminate(self):
        h = _hook()
        for i in range(CONSECUTIVE_TERMINATE_THRESHOLD + 2):
            d = h.record_timeout()
            if i > CONSECUTIVE_TERMINATE_THRESHOLD:
                assert d.should_terminate
                return
        assert False, "Expected timeout-driven termination"
