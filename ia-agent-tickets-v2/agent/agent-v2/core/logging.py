"""
PROD-9: Structured logging with request context.

Injects user_id and thread_id into every log line automatically
via contextvars. Uses both a Formatter (controls output format)
and a Filter (ensures fields exist even with third-party handlers).

Usage:
    from core.logging import setup_structured_logging
    setup_structured_logging()  # call ONCE at module level before uvicorn

After setup, all agent log lines include:
    [2026-06-01 14:23:45] [user=2608 thread=2608:t1] INFO - core.agent - message here
"""

import logging

from core.context import current_user_id, current_thread_id

CTX_FORMAT = (
    "[%(asctime)s] [user=%(user_id)s thread=%(thread_id)s] "
    "%(levelname)s - %(name)s - %(message)s"
)
CTX_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


class ContextFormatter(logging.Formatter):
    """
    Custom formatter that injects user_id and thread_id from contextvars.

    Unlike a Filter, the Formatter controls the final output regardless of
    which handler processes the record. This avoids issues with uvicorn's
    subprocess handlers that may not run root logger filters.
    """

    def format(self, record: logging.LogRecord) -> str:
        uid = current_user_id.get(0)
        tid = current_thread_id.get("?")
        record.user_id = str(uid) if uid else "?"
        record.thread_id = tid or "?"
        return super().format(record)


class ContextFilter(logging.Filter):
    """
    Fallback filter that ensures user_id and thread_id are on every record.

    Runs BEFORE the Formatter. If the record already has these fields
    (set by ContextFormatter), this is a no-op. If a handler bypasses
    the Formatter (e.g. third-party libs), this filter ensures the
    record has the expected attributes so %(user_id)s doesn't crash.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if not hasattr(record, "user_id") or getattr(record, "user_id", None) is None:
            try:
                uid = current_user_id.get(0)
                record.user_id = str(uid) if uid else "?"
            except LookupError:
                record.user_id = "?"
        if not hasattr(record, "thread_id") or getattr(record, "thread_id", None) is None:
            try:
                record.thread_id = current_thread_id.get("?") or "?"
            except LookupError:
                record.thread_id = "?"
        return True


def setup_structured_logging(level: int = logging.INFO) -> None:
    """
    Configures root logger with context-aware formatting.

    Call this ONCE at module level before uvicorn starts.
    Replaces any existing root handlers with our configured one.
    Sets proper levels for all agent logger namespaces.
    """
    root = logging.getLogger()
    root.setLevel(level)

    # Replace all handlers with our context-aware one
    root.handlers.clear()

    handler = logging.StreamHandler()
    handler.setFormatter(ContextFormatter(CTX_FORMAT, datefmt=CTX_DATE_FORMAT))
    handler.addFilter(ContextFilter())
    root.addHandler(handler)

    # Ensure ALL agent sub-loggers are visible at INFO level
    agent_namespaces = [
        "core",
        "core.agent",
        "tools",
        "tools.ticket_tools",
        "tools.rag_tools",
        "tools.user_tools",
        "api",
        "api.routes",
        "api.routes.chat",
        "api.routes.stream",
        "api.routes.metrics",
        "api.middleware",
        "api.middleware.auth",
        "api.middleware.rate_limit",
        "feedback",
        "feedback.collector",
        "adapters",
        "adapters.odoo_adapter",
        "adapters.express_adapter",
        "rag",
        "rag.store",
        "config",
        "config.settings",
    ]
    for name in agent_namespaces:
        logging.getLogger(name).setLevel(level)
