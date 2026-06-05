"""
Structured logging with JSON output — PROD-9.

All logs are JSON-lines (one object per line) to stdout for consumption by
Docker, ELK, Datadog, or any log aggregator.

Every log line includes:
  - timestamp       ISO 8601 with milliseconds + timezone
  - level           log level string
  - logger          module name
  - event           human-readable message
  - user_id         from ContextVar (0 if not set)
  - thread_id       from ContextVar ("" if not set)
  - request_id      from ContextVar ("" if not set)

Usage:
    from core.logging import get_logger
    _log = get_logger(__name__)
    _log.info("request_received", extra={"latency_ms": 45})

Initialization:
    configure_logging() is called in main.py lifespan startup exactly once.
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any


# ── Context injection filter ──────────────────────────────────────────────────


class _ContextFilter(logging.Filter):
    """Injects user_id, thread_id, request_id from ContextVars into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        from core.context import current_user_id, current_thread_id, current_request_id

        record.user_id = current_user_id.get(0)
        record.thread_id = current_thread_id.get("")
        record.request_id = current_request_id.get("")
        return True


# ── JSON formatter ────────────────────────────────────────────────────────────


class _StructuredFormatter(logging.Formatter):
    """Formats log records as JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        obj: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "event": record.getMessage(),
        }

        # Context from filter
        uid = getattr(record, "user_id", 0)
        if uid:
            obj["user_id"] = uid
        tid = getattr(record, "thread_id", "")
        if tid:
            obj["thread_id"] = tid
        rid = getattr(record, "request_id", "")
        if rid:
            obj["request_id"] = rid

        # Extra structured fields (passed via extra={} dict)
        extra = getattr(record, "extra_fields", None)
        if extra:
            obj.update(extra)

        # Exception info
        if record.exc_info and record.exc_info[0] is not None:
            obj["exception"] = self.formatException(record.exc_info)

        return json.dumps(obj, ensure_ascii=False, default=str)


# ── Logger factory ─────────────────────────────────────────────────────────────


def get_logger(name: str) -> logging.Logger:
    """Returns a logger for the given module. Use as: _log = get_logger(__name__)."""
    return logging.getLogger(name)


# ── Audit logger ──────────────────────────────────────────────────────────────


AUDIT_LOG_PATH = "/app/data/audit.log"


def get_audit_logger() -> logging.Logger:
    """Returns the audit logger for security events."""
    return logging.getLogger("sara.audit")


# ── Configuration ──────────────────────────────────────────────────────────────


_configured = False


def configure_logging(level: str = "INFO") -> None:
    """
    Configures structured JSON logging globally.

    Call once during FastAPI lifespan startup. Idempotent.
    """
    global _configured
    if _configured:
        return
    _configured = True

    # ── Root handler: JSON to stdout ──────────────────────────────────────
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(_StructuredFormatter())
    handler.addFilter(_ContextFilter())

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()
    root.addHandler(handler)

    # Suppress noisy third-party loggers
    for noisy in ("httpx", "httpcore", "urllib3", "asyncio", "langsmith"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # ── Audit logger: separate file for security events ────────────────────
    audit = logging.getLogger("sara.audit")
    audit.propagate = False
    try:
        audit_handler = logging.FileHandler(AUDIT_LOG_PATH, delay=True)
        audit_handler.setFormatter(_StructuredFormatter())
        audit_handler.addFilter(_ContextFilter())
        audit.addHandler(audit_handler)
        audit.setLevel(logging.INFO)
    except OSError:
        pass  # File not writable — security events go to stdout via root
