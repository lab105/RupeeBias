"""
validation_hook.py — Bridge between runner and scripts.validation.

Wraps validate_response_during_eval and applies the user's --no-terminate
bypass list. Also owns the rate-based / consecutive-based termination
decisions that used to live inside validation.py.
"""

import logging
from dataclasses import dataclass

from runner.config import BypassChecks
from scripts.validation import (
    CONSECUTIVE_TERMINATE_THRESHOLD,
    REFUSAL_RATE_THRESHOLD,
    ValidationContext,
    ValidationResult,
    ValidationSeverity,
    validate_response_during_eval,
)

log = logging.getLogger(__name__)


@dataclass
class HookDecision:
    result: ValidationResult
    should_terminate: bool
    terminate_reason: str = ""


class ValidationHook:
    """
    Per-(model, temp) validation gate. Holds one ValidationContext and
    decides whether each row's validation result should terminate the batch.

    The bypass list lets the user disable specific termination paths:
      - 'refusal'     → ignore refusal-rate threshold
      - 'consecutive' → ignore consecutive-failure threshold
      - 'amount_low'  → don't terminate on too-low values
      - 'amount_high' → already FLAG-only in validation.py (here for symmetry)
      - 'truncation'  → don't terminate on truncated responses
      - 'timeout'     → don't count timeouts as consecutive failures
      - 'format'      → don't terminate on format errors (missing ###, etc.)
    """

    def __init__(
            self,
            model: str,
            task: str,
            temperature: float,
            bypass: BypassChecks,
    ):
        self.context = ValidationContext(model=model, task=task, temperature=temperature)
        self.bypass = bypass
        self._task = task

    # ── per-row entry point ────────────────────────────────────────────────

    def evaluate(self, response: str) -> HookDecision:
        """
        Validate one response and decide whether to terminate the batch.

        Returns HookDecision with the per-row ValidationResult plus the
        batch-level should_terminate flag (after applying bypass list).
        """
        result, per_row_terminate = validate_response_during_eval(
            response=response, task=self._task, context=self.context,
        )

        terminate, reason = self._decide_terminate(result, per_row_terminate)
        return HookDecision(
            result=result,
            should_terminate=terminate,
            terminate_reason=reason,
        )

    def record_timeout(self) -> HookDecision:
        """
        Account for a request timeout. Counts as a consecutive failure unless
        'timeout' is bypassed. Returns a synthetic FLAG result.
        """
        result = ValidationResult(
            is_valid=False, severity=ValidationSeverity.FLAG,
            reason="Request timed out", task=self._task, check_type="timeout",
        )
        self.context.total_responses += 1
        self.context.flag_count += 1
        if "timeout" not in self.bypass:
            self.context.consecutive_failures += 1
            log.warning(
                f"⚠ [{self._task}] FLAG — timeout (consecutive="
                f"{self.context.consecutive_failures})"
            )
        else:
            log.warning(f"⚠ [{self._task}] FLAG — timeout (bypassed)")

        terminate, reason = self._check_consecutive()
        return HookDecision(result=result, should_terminate=terminate, terminate_reason=reason)

    # ── batch-level termination decisions ─────────────────────────────────

    def _decide_terminate(
            self, result: ValidationResult, per_row_terminate: bool,
    ) -> tuple[bool, str]:
        """
        Apply bypass list to the per-row terminate signal and check rate
        thresholds. Returns (should_terminate, reason).
        """
        # Per-row TERMINATE — gated by check_type bypass
        if per_row_terminate:
            check = result.check_type
            terminate_check_map = {
                "truncation": "truncation",
                "amount_low": "amount_low",
            }
            # Format-related check types all gate on 'format'
            bypass_key = terminate_check_map.get(check, "format")

            if bypass_key in self.bypass:
                log.info(
                    f"↳ [{self._task}] TERMINATE bypassed for check '{check}' "
                    f"({bypass_key} in --no-terminate)"
                )
            else:
                return True, f"{check}: {result.reason}"

        # Rate-based: refusal rate
        if (
                self.context.total_responses > 0
                and "refusal" not in self.bypass
                and self.context.refusal_count / self.context.total_responses
                > REFUSAL_RATE_THRESHOLD
        ):
            rate = self.context.refusal_count / self.context.total_responses
            return True, (
                f"refusal_rate: {rate:.1%} > {REFUSAL_RATE_THRESHOLD:.0%} "
                f"({self.context.refusal_count}/{self.context.total_responses})"
            )

        # Consecutive failures
        return self._check_consecutive()

    def _check_consecutive(self) -> tuple[bool, str]:
        if "consecutive" in self.bypass:
            return False, ""
        if self.context.consecutive_failures > CONSECUTIVE_TERMINATE_THRESHOLD:
            return True, (
                f"consecutive_failures: {self.context.consecutive_failures} "
                f"> {CONSECUTIVE_TERMINATE_THRESHOLD}"
            )
        return False, ""
