"""
client.py — Single API call wrapper.

ChatClient.call() makes one request with HTTP-level retry on transient errors.
Returns ChatResult or raises:
  - HTTPRetryExhausted   when retries are used up
  - RequestTimeoutError  when the request times out (counted as a failure
                         by the validation hook, never silently retried away)

Termination is NOT handled here — that's orchestrator + validation_hook.
"""

import asyncio
import logging
import os
import random
from dataclasses import dataclass
from typing import Callable, Literal, Optional

from openai import AsyncOpenAI, APIStatusError, APITimeoutError, RateLimitError
from dotenv import load_dotenv

load_dotenv()

log = logging.getLogger(__name__)

_RETRY_STATUSES = {408, 409, 429, 500, 502, 503, 504}


# ---------------------------------------------------------------------------
# Result + errors
# ---------------------------------------------------------------------------


@dataclass
class ChatResult:
    content: str                    # message text, or "[TRUNCATED]" if API returned None
    finish_reason: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    reasoning_content: str
    reasoning_effort: str


class HTTPRetryExhausted(Exception):
    """Raised when all HTTP-level retries fail."""


class RequestTimeoutError(Exception):
    """Raised when the request times out. Counted as a consecutive failure."""


class SkippedAfterAcquire(Exception):
    """Raised when the should_skip predicate returns True after acquiring the
    semaphore — used to bail tasks that were queued before termination fired."""


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------


class ChatClient:
    """Thin wrapper around AsyncOpenAI with bounded concurrency + HTTP retry."""

    def __init__(
            self,
            api_key: Optional[str] = None,
            base_url: Optional[str] = None,
            rate_limit: int = 60,
            max_retries: int = 5,
            max_backoff: float = 30.0,
            timeout: float = 200.0,
    ):
        self._client = AsyncOpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            base_url=base_url or os.getenv("OPENAI_BASE_URL") or None,
            timeout=timeout,
            max_retries=0,  # we handle retry ourselves
        )
        self._sem = asyncio.Semaphore(rate_limit)
        self._max_retries = max_retries
        self._max_backoff = max_backoff

    async def call(
            self,
            model: str,
            prompt: str,
            system_prompt: Optional[str],
            temperature: float,
            max_tokens: int,
            features: dict,
            reasoning_effort: Literal[
                "none", "minimal", "low", "medium", "high", "xhigh"
            ] = "none",
            should_skip: Optional[Callable[[], bool]] = None,
    ) -> ChatResult:
        """
        Make one chat completion call. May retry on transient HTTP errors.

        should_skip: optional callable checked AFTER the semaphore is acquired,
        right before sending. If True, raises SkippedAfterAcquire so the
        orchestrator can mark this row as terminated without burning a request.
        """
        is_sarvam = "sarvam" in model.lower()

        messages = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})

        run_metadata = {
            k: str(v) for k, v in {
                "id":    features.get("id", ""),
                "task":  features.get("task", ""),
                "model": model,
            }.items() if v
        }

        call_kwargs = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        if is_sarvam:
            call_kwargs["reasoning_effort"] = reasoning_effort
            call_kwargs["extra_body"] = {"metadata": run_metadata}
        else:
            call_kwargs["extra_body"] = {
                "reasoning": {"effort": reasoning_effort, "exclude": False},
                "metadata": run_metadata,
            }

        for attempt in range(self._max_retries + 1):
            try:
                async with self._sem:
                    # Post-acquire skip check: termination may have fired while
                    # this task was queued at the semaphore.
                    if should_skip is not None and should_skip():
                        raise SkippedAfterAcquire()
                    # Logged inside the semaphore so the timing reflects actual send.
                    log.info(
                        f"→ sending  model={model} t={temperature} "
                        f"id={features.get('id', '?')}"
                    )
                    r = await self._client.chat.completions.create(**call_kwargs)

                content = r.choices[0].message.content
                if content is None:
                    content = "[TRUNCATED]"

                return ChatResult(
                    content=content,
                    finish_reason=r.choices[0].finish_reason,
                    prompt_tokens=r.usage.prompt_tokens,
                    completion_tokens=r.usage.completion_tokens,
                    total_tokens=r.usage.total_tokens,
                    reasoning_content=getattr(
                        r.choices[0].message, "reasoning_content", ""
                    ) or "",
                    reasoning_effort=reasoning_effort,
                )

            except APITimeoutError:
                # Timeout is NOT silently retried away — orchestrator decides
                # whether to count toward consecutive failures.
                raise RequestTimeoutError(
                    f"Request timed out after {self._client.timeout}s"
                )
            except (RateLimitError, APIStatusError) as e:
                retryable = isinstance(e, RateLimitError) or (
                        isinstance(e, APIStatusError)
                        and getattr(e, "status_code", None) in _RETRY_STATUSES
                )
                if retryable and attempt < self._max_retries:
                    wait = min(self._max_backoff, 2 ** attempt + random.random())
                    log.warning(
                        f"[retry {attempt + 1}/{self._max_retries}] "
                        f"model={model} — waiting {wait:.1f}s"
                    )
                    await asyncio.sleep(wait)
                    continue
                raise

        # All retries used — bug fix: previous code returned None here.
        raise HTTPRetryExhausted(
            f"All {self._max_retries} HTTP retries failed for model={model}"
        )
