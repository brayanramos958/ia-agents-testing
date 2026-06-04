"""
Per-user sliding-window rate limiter.

Keyed by user_id (from the authenticated request body).
Uses an in-process sliding window — safe for single-worker async deployments.

For multi-worker production: replace _windows with a Redis-backed counter.
The interface (check_rate_limit) stays the same — only this module changes.
"""

from collections import defaultdict
from fastapi import HTTPException
import time

from config.settings import settings

# thread_id → list of request timestamps within the current window
_windows: dict[str, list[float]] = defaultdict(list)
_WINDOW_SECONDS = 60.0


def check_rate_limit(user_id: int) -> None:
    """
    Raises HTTP 429 if user_id has exceeded settings.rate_limit_per_minute
    within the last 60 seconds.

    Call at the top of any rate-limited route handler before any LLM work.
    """
    key = str(user_id)
    now = time.time()
    window = _windows[key]

    # Evict timestamps that have left the sliding window
    cutoff = now - _WINDOW_SECONDS
    while window and window[0] <= cutoff:
        window.pop(0)

    limit = settings.rate_limit_per_minute
    if len(window) >= limit:
        retry_after = max(1, int(_WINDOW_SECONDS - (now - window[0])))
        raise HTTPException(
            status_code=429,
            detail=f"Demasiadas solicitudes. Máximo {limit} por minuto.",
            headers={"Retry-After": str(retry_after)},
        )

    window.append(now)
