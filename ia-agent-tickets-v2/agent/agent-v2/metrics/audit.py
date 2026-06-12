"""
Metrics audit log — Fase 1.7 del PLAN_METRICS.md.

Logs every request to /agent/metrics/* endpoints for compliance
and traceability. The audit log records:
  - Who consulted which endpoint
  - When
  - With what query params
  - Response size and latency

Architecture:
  - metrics_audit_log table in PostgreSQL
  - Lightweight async writer (fire-and-forget)
  - Schema created on first import (idempotent)
"""

import asyncio
import time
import json
import logging
from typing import Optional
import psycopg

from config.settings import settings
from core.context import current_user_id, current_user_role

logger = logging.getLogger(__name__)


def _ensure_schema() -> None:
    """Create metrics_audit_log table. Idempotent."""
    dsn = settings.postgres_dsn
    if not dsn:
        logger.warning("postgres_dsn not configured — audit log disabled")
        return

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS metrics_audit_log (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    endpoint TEXT NOT NULL,
                    user_id INTEGER,
                    user_role TEXT,
                    query_params JSONB,
                    response_size_bytes INTEGER,
                    response_time_ms REAL
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_timestamp
                ON metrics_audit_log(timestamp)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_endpoint
                ON metrics_audit_log(endpoint)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_audit_user
                ON metrics_audit_log(user_id)
            """)


# Run on first import
_ensure_schema()


def log_request(
    endpoint: str,
    query_params: Optional[dict] = None,
    response_size_bytes: int = 0,
    response_time_ms: float = 0.0,
) -> None:
    """
    Synchronous audit log writer. Use sparingly — prefer async version.

    This blocks the request thread for ~5-10ms (one INSERT to PostgreSQL).
    For the /agent/metrics endpoints (which are called ~1x per minute by
    dashboards), this is acceptable.
    """
    dsn = settings.postgres_dsn
    if not dsn:
        return

    try:
        user_id = current_user_id.get(None)
        user_role = current_user_role.get(None)
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO metrics_audit_log
                    (endpoint, user_id, user_role, query_params,
                     response_size_bytes, response_time_ms)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    endpoint,
                    user_id,
                    user_role,
                    json.dumps(query_params or {}),
                    response_size_bytes,
                    response_time_ms,
                ))
    except psycopg.Error as exc:
        # Never fail the request because of audit log issues
        logger.warning("Failed to write audit log: %s", exc)


async def log_request_async(
    endpoint: str,
    query_params: Optional[dict] = None,
    response_size_bytes: int = 0,
    response_time_ms: float = 0.0,
) -> None:
    """Async audit log writer (fire-and-forget)."""
    dsn = settings.postgres_dsn
    if not dsn:
        return

    try:
        user_id = current_user_id.get(None)
        user_role = current_user_role.get(None)
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO metrics_audit_log
                    (endpoint, user_id, user_role, query_params,
                     response_size_bytes, response_time_ms)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    endpoint,
                    user_id,
                    user_role,
                    json.dumps(query_params or {}),
                    response_size_bytes,
                    response_time_ms,
                ))
            await conn.commit()
    except psycopg.Error as exc:
        logger.warning("Failed to write async audit log: %s", exc)


class AuditTimer:
    """
    Context manager that times a request and logs it to the audit log.

    Usage:
        @router.get("/agent/metrics/something")
        async def get_something():
            with AuditTimer("/agent/metrics/something", {"foo": "bar"}) as timer:
                result = await compute_something()
                timer.set_response_size(len(json.dumps(result)))
                return result
    """

    def __init__(self, endpoint: str, query_params: Optional[dict] = None):
        self.endpoint = endpoint
        self.query_params = query_params
        self.start_time: float = 0
        self.response_size: int = 0

    def set_response_size(self, size: int) -> None:
        self.response_size = size

    def __enter__(self):
        self.start_time = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        elapsed_ms = (time.perf_counter() - self.start_time) * 1000
        # Fire and forget — don't block on audit log writes
        asyncio.create_task(log_request_async(
            endpoint=self.endpoint,
            query_params=self.query_params,
            response_size_bytes=self.response_size,
            response_time_ms=elapsed_ms,
        ))
        return False  # don't suppress exceptions
