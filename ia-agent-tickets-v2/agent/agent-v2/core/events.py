"""
Lightweight async event bus — Observer pattern for cross-module communication.

Why this exists:
  - Avoids tight coupling between the domain (ticket_tools) and observability
    (metrics) modules. Domain code emits events; metrics (or any other consumer)
    subscribes to them.
  - Replaces direct calls like `start_creation()` with `emit_creation_started()`.
    Now `ticket_tools` doesn't need to know that metrics exists.
  - Error isolation: if a listener raises, the emitter logs and continues.
    A failing metric writer never breaks ticket creation.

Public API:
    emit(event_name, **kwargs)        — fire-and-forget, schedules async listeners
    subscribe(event_name, callback)   — register a listener (sync or async callback)
    clear(event_name=None)            — clear listeners (mostly for tests)

Event names (convention: dot-separated, past tense):
    "ticket.creation_started"     — kwargs: user_id, user_role, thread_id, session_id
    "ticket.creation_completed"   — kwargs: user_id, ticket_id, ticket_name, duration_seconds
    "ticket.creation_abandoned"   — kwargs: user_id, thread_id
    "user.message_sent"           — kwargs: user_id, user_role, thread_id, session_id
    "user.chat_started"           — kwargs: user_id, user_role, thread_id, session_id

Example:
    # Domain code (tools/ticket_tools.py) — no metrics import
    from core.events import emit
    emit("ticket.creation_started", user_id=uid, user_role=role, ...)

    # Metrics module — subscribes once at startup
    from core.events import subscribe
    subscribe("ticket.creation_started", _on_creation_started)
"""

import asyncio
import logging
from typing import Callable, Dict, List, Any

logger = logging.getLogger(__name__)

# Type alias: a listener can be sync or async
Listener = Callable[..., Any]

# Registry: event_name -> list of listeners
_listeners: Dict[str, List[Listener]] = {}


def subscribe(event_name: str, callback: Listener) -> None:
    """
    Register a listener for an event.

    The callback can be sync (def callback(**kwargs)) or async (async def callback(**kwargs)).
    If sync, it runs in the thread pool (won't block the event loop).
    If async, it runs in the event loop.

    Idempotent: subscribing the same callback twice has no effect.
    """
    if event_name not in _listeners:
        _listeners[event_name] = []
    if callback not in _listeners[event_name]:
        _listeners[event_name].append(callback)
        logger.debug("subscribed %s to %s", callback.__name__, event_name)


def unsubscribe(event_name: str, callback: Listener) -> None:
    """Remove a listener. No-op if not subscribed."""
    if event_name in _listeners and callback in _listeners[event_name]:
        _listeners[event_name].remove(callback)


def clear(event_name: str = None) -> None:
    """Clear listeners. If event_name is None, clears ALL (use in tests)."""
    if event_name is None:
        _listeners.clear()
    elif event_name in _listeners:
        _listeners[event_name].clear()


def emit(event_name: str, **kwargs: Any) -> None:
    """
    Fire an event. Schedules all listeners to run asynchronously.

    This function returns immediately. Listeners run in the background.
    If a listener raises, the error is logged but doesn't propagate.

    Note: emit() does NOT await async listeners — it schedules them.
    If you need to wait for completion, use emit_and_wait() instead.
    """
    listeners = _listeners.get(event_name, [])
    if not listeners:
        return

    for listener in listeners:
        try:
            if asyncio.iscoroutinefunction(listener):
                # Async listener — schedule on event loop
                task = asyncio.create_task(listener(**kwargs))
                # Track errors so they don't get silently lost
                task.add_done_callback(_log_task_error)
            else:
                # Sync listener — run in thread pool to avoid blocking.
                # Use get_running_loop() to avoid DeprecationWarning in Python 3.12+.
                # The except RuntimeError below handles the "no loop running" case.
                loop = asyncio.get_running_loop()
                loop.run_in_executor(
                    None, _safe_call, listener, kwargs
                )
        except RuntimeError as exc:
            # No event loop running (e.g., during module import) — fall back to sync
            logger.debug("No event loop, calling %s synchronously: %s",
                         listener.__name__, exc)
            try:
                listener(**kwargs)
            except Exception as inner_exc:
                logger.error("Sync listener %s failed: %s",
                             listener.__name__, inner_exc, exc_info=True)


def _log_task_error(task: asyncio.Task) -> None:
    """Callback for async task errors — logs but doesn't propagate."""
    if task.cancelled():
        return
    exc = task.exception()
    if exc:
        logger.error("Async event listener failed: %s", exc, exc_info=exc)


def _safe_call(listener: Listener, kwargs: dict) -> None:
    """Wrapper to catch exceptions from sync listeners in executor."""
    try:
        listener(**kwargs)
    except Exception as exc:
        logger.error("Sync listener %s failed: %s", listener.__name__, exc,
                     exc_info=True)
