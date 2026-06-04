"""
Circuit breaker for LLM providers with retry backoff.

Prevents cascading failures when the primary LLM provider rate-limits.
Uses a simple failure counter per provider — if a provider fails 3 times
consecutively, the circuit opens for 30 seconds. During that time, requests
are routed to the fallback provider without attempting the primary.

Zero LLM token cost — pure Python state machine.
"""

from __future__ import annotations

import time
import logging
import asyncio
from enum import Enum

_log = logging.getLogger("sara.circuit_breaker")


class CircuitState(Enum):
    CLOSED = "closed"        # Normal — requests go to primary
    OPEN = "open"            # Primary is failing — requests go to fallback
    HALF_OPEN = "half_open"  # Probing if primary recovered


class ProviderStatus:
    """Tracks failure/success stats for a single LLM provider."""

    def __init__(self, name: str):
        self.name = name
        self.failures = 0
        self.successes = 0
        self.consecutive_failures = 0
        self.last_failure_at: float | None = None
        self.last_success_at: float | None = None
        self.state = CircuitState.CLOSED
        self.open_since: float | None = None

    def record_success(self) -> None:
        self.successes += 1
        self.consecutive_failures = 0
        self.last_success_at = time.time()
        if self.state == CircuitState.HALF_OPEN:
            self.state = CircuitState.CLOSED
            _log.info("Circuit CLOSED for %s — provider recovered", self.name)

    def record_failure(self) -> None:
        self.failures += 1
        self.consecutive_failures += 1
        self.last_failure_at = time.time()

        if self.state == CircuitState.CLOSED and self.consecutive_failures >= 3:
            self.state = CircuitState.OPEN
            self.open_since = time.time()
            _log.warning(
                "Circuit OPEN for %s — %d consecutive failures. "
                "Will retry in 30s.",
                self.name, self.consecutive_failures,
            )

    def should_attempt(self) -> bool:
        """Returns True if we should try this provider right now."""
        if self.state == CircuitState.CLOSED:
            return True
        if self.state == CircuitState.HALF_OPEN:
            return True
        # OPEN: wait 30s before trying again
        if self.open_since and (time.time() - self.open_since) > 30:
            self.state = CircuitState.HALF_OPEN
            _log.info("Circuit HALF_OPEN for %s — probing...", self.name)
            return True
        return False

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self.state.value,
            "failures": self.failures,
            "successes": self.successes,
            "consecutive_failures": self.consecutive_failures,
            "last_failure_at": self.last_failure_at,
            "last_success_at": self.last_success_at,
            "open_since": self.open_since,
        }


# ── Global provider status registry ────────────────────────────────────────

_status: dict[str, ProviderStatus] = {}


def get_provider_status(name: str) -> ProviderStatus:
    """Returns or creates the ProviderStatus for a named provider."""
    if name not in _status:
        _status[name] = ProviderStatus(name)
    return _status[name]


def get_all_status() -> dict[str, dict]:
    """Returns status of all known providers for the /agent/llm-status endpoint."""
    return {name: ps.to_dict() for name, ps in _status.items()}


# ── Retry with exponential backoff ──────────────────────────────────────────

async def retry_with_backoff(
    provider_name: str,
    call_fn,
    max_retries: int = 2,
    base_delay: float = 2.0,
) -> str:
    """
    Calls an LLM with retry backoff on the SAME provider before falling back.

    Args:
        provider_name: Human-readable name (e.g. "deepseek-v4-flash")
        call_fn: Async callable that returns an LLM response
        max_retries: Number of retries on the same provider before giving up
        base_delay: Initial delay in seconds (doubles each retry)

    Returns:
        The LLM response string.

    Raises:
        The last exception if all retries fail.
    """
    status = get_provider_status(provider_name)
    last_exc = None

    for attempt in range(max_retries + 1):
        if not status.should_attempt():
            raise CircuitOpenError(
                f"Circuit OPEN for {provider_name} — routing to fallback"
            )

        try:
            result = await call_fn()
            status.record_success()
            return result
        except (RateLimitError, TimeoutError, ConnectionError, OSError) as exc:
            last_exc = exc
            status.record_failure()
            if attempt < max_retries:
                delay = base_delay * (2 ** attempt)
                _log.debug(
                    "Retry %d/%d for %s after %.1fs: %s",
                    attempt + 1, max_retries, provider_name, delay, exc,
                )
                await asyncio.sleep(delay)
            else:
                _log.warning(
                    "All %d retries exhausted for %s",
                    max_retries, provider_name,
                )

    raise last_exc or RuntimeError(f"All retries failed for {provider_name}")


# ── Custom exceptions ──────────────────────────────────────────────────────

class CircuitOpenError(Exception):
    """Raised when the circuit is open and the provider should not be called."""


class RateLimitError(Exception):
    """Raised when the LLM provider returns 429 Too Many Requests."""
