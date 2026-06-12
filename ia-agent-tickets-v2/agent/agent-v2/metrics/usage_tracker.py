"""
Usage & adoption tracking — Fase 1.5 del PLAN_METRICS.md.

Tracks every interaction with SARA in a usage_events table.
Provides endpoints for adoption metrics (daily/weekly usage, unique users).

Architecture:
  - usage_events table in PostgreSQL
  - Async event recorder (fire-and-forget) — never blocks the user request
  - Aggregations computed on-demand via SQL
  - Session tracking via session_id (groups multiple messages of one conversation)

Public API:
    record_event(user_id, user_role, event_type, thread_id, session_id, metadata)
    get_adoption_summary(period_days=7)  -> dict with all adoption KPIs
    get_top_users(period_days=7, limit=10)
"""

import json
import logging
import asyncio
from typing import Optional, Dict, Any

import psycopg

from config.settings import settings

logger = logging.getLogger(__name__)


def _ensure_schema() -> None:
    """Create usage_events table. Idempotent."""
    dsn = settings.postgres_dsn
    if not dsn:
        raise RuntimeError("settings.postgres_dsn is not configured")

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS usage_events (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    user_id INTEGER NOT NULL,
                    user_role TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    thread_id TEXT,
                    session_id TEXT,
                    metadata JSONB DEFAULT '{}'::jsonb
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_events_timestamp
                ON usage_events(timestamp)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_events_user
                ON usage_events(user_id)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_events_type
                ON usage_events(event_type)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_usage_events_session
                ON usage_events(session_id)
            """)


# Run on first import
_ensure_schema()


# Valid event types
VALID_EVENT_TYPES = frozenset({
    "chat_started",
    "message_sent",
    "ticket_created",
    "ticket_resolved",
    "rag_used",
    "feedback_given",
    "session_ended",
})


def record_event(
    user_id: int,
    user_role: str,
    event_type: str,
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """
    Record a usage event (SYNCHRONOUS — blocks ~5ms).

    Prefer record_event_async for high-throughput paths.
    """
    if event_type not in VALID_EVENT_TYPES:
        logger.warning("Invalid event_type: %s", event_type)
        return

    dsn = settings.postgres_dsn
    if not dsn:
        return

    try:
        with psycopg.connect(dsn, autocommit=True) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO usage_events
                    (user_id, user_role, event_type, thread_id, session_id, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    user_id,
                    user_role,
                    event_type,
                    thread_id or "",
                    session_id or "",
                    json.dumps(metadata or {}),
                ))
    except psycopg.Error as exc:
        # Only catch DB errors. Programming bugs (TypeError etc.) will
        # surface in tests instead of being silently swallowed.
        logger.warning("Failed to record usage event: %s", exc)


async def record_event_async(
    user_id: int,
    user_role: str,
    event_type: str,
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None:
    """Record a usage event (ASYNCHRONOUS — fire-and-forget)."""
    if event_type not in VALID_EVENT_TYPES:
        return

    dsn = settings.postgres_dsn
    if not dsn:
        return

    try:
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute("""
                    INSERT INTO usage_events
                    (user_id, user_role, event_type, thread_id, session_id, metadata)
                    VALUES (%s, %s, %s, %s, %s, %s)
                """, (
                    user_id,
                    user_role,
                    event_type,
                    thread_id or "",
                    session_id or "",
                    json.dumps(metadata or {}),
                ))
            await conn.commit()
    except psycopg.Error as exc:
        # Only catch DB errors. Programming bugs (TypeError etc.) will
        # surface in tests instead of being silently swallowed.
        logger.warning("Failed to record async usage event: %s", exc)


def get_adoption_summary() -> dict:
    """
    Compute adoption metrics. Single SQL pass.

    Returns dict with all KPIs (Fase 1.5).
    """
    dsn = settings.postgres_dsn
    if not dsn:
        return _empty_adoption()

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # Daily/weekly/monthly usage counts (events from any user)
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE timestamp >= CURRENT_DATE) AS daily_count,
                    COUNT(*) FILTER (WHERE timestamp >= NOW() - INTERVAL '7 days') AS weekly_count,
                    COUNT(*) FILTER (WHERE timestamp >= NOW() - INTERVAL '30 days') AS monthly_count
                FROM usage_events
            """)
            daily, weekly, monthly = cur.fetchone()

            # Unique users (DAU, WAU, MAU)
            cur.execute("""
                SELECT
                    COUNT(DISTINCT user_id) FILTER (WHERE timestamp >= CURRENT_DATE) AS dau,
                    COUNT(DISTINCT user_id) FILTER (WHERE timestamp >= NOW() - INTERVAL '7 days') AS wau,
                    COUNT(DISTINCT user_id) FILTER (WHERE timestamp >= NOW() - INTERVAL '30 days') AS mau
                FROM usage_events
            """)
            dau, wau, mau = cur.fetchone()

            # Sessions per user (avg)
            cur.execute("""
                SELECT
                    COALESCE(AVG(session_count), 0) AS avg_sessions_per_user
                FROM (
                    SELECT user_id, COUNT(DISTINCT session_id) AS session_count
                    FROM usage_events
                    WHERE timestamp >= NOW() - INTERVAL '7 days'
                      AND session_id != ''
                    GROUP BY user_id
                ) s
            """)
            avg_sessions = cur.fetchone()[0] or 0

            # Power users (>= 50 events in last 30 days)
            cur.execute("""
                SELECT COUNT(*) FROM (
                    SELECT user_id
                    FROM usage_events
                    WHERE timestamp >= NOW() - INTERVAL '30 days'
                    GROUP BY user_id
                    HAVING COUNT(*) >= 50
                ) p
            """)
            power_users = cur.fetchone()[0] or 0

            # Dormant users (no events in last 30 days but had events before)
            cur.execute("""
                SELECT COUNT(*) FROM (
                    SELECT user_id
                    FROM usage_events
                    GROUP BY user_id
                    HAVING MAX(timestamp) < NOW() - INTERVAL '30 days'
                ) d
            """)
            dormant_users = cur.fetchone()[0] or 0

            # Retention rate 7d: users active in 7-14d who came back in last 7d
            cur.execute("""
                SELECT
                    COALESCE(
                        100.0 * COUNT(DISTINCT recent.user_id) / NULLIF(COUNT(DISTINCT previous.user_id), 0),
                        0
                    ) AS retention
                FROM (
                    SELECT DISTINCT user_id FROM usage_events
                    WHERE timestamp >= NOW() - INTERVAL '14 days'
                      AND timestamp < NOW() - INTERVAL '7 days'
                ) previous
                LEFT JOIN (
                    SELECT DISTINCT user_id FROM usage_events
                    WHERE timestamp >= NOW() - INTERVAL '7 days'
                ) recent ON previous.user_id = recent.user_id
            """)
            retention = cur.fetchone()[0] or 0

            # Activation rate: new users (first event in last 7d) with >=3 sessions
            cur.execute("""
                SELECT
                    COALESCE(
                        100.0 * COUNT(*) FILTER (WHERE session_count >= 3) / NULLIF(COUNT(*), 0),
                        0
                    ) AS activation
                FROM (
                    SELECT u.user_id, COUNT(DISTINCT u.session_id) AS session_count
                    FROM usage_events u
                    WHERE u.session_id != ''
                      AND u.user_id IN (
                          SELECT user_id FROM usage_events
                          GROUP BY user_id
                          HAVING MIN(timestamp) >= NOW() - INTERVAL '7 days'
                      )
                    GROUP BY u.user_id
                ) s
            """)
            activation = cur.fetchone()[0] or 0

    return {
        "usage_daily_count": int(daily or 0),
        "usage_weekly_count": int(weekly or 0),
        "usage_monthly_count": int(monthly or 0),
        "unique_users_daily": int(dau or 0),
        "unique_users_weekly": int(wau or 0),
        "unique_users_monthly": int(mau or 0),
        "sessions_per_user_avg": round(float(avg_sessions), 2),
        "retention_rate_7d_pct": round(float(retention), 2),
        "activation_rate_pct": round(float(activation), 2),
        "power_users_count": int(power_users),
        "dormant_users_count": int(dormant_users),
    }


def get_top_users(limit: int = 10) -> list:
    """Return top users by activity in the last 7 days."""
    dsn = settings.postgres_dsn
    if not dsn:
        return []

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT user_id, user_role,
                       COUNT(*) AS event_count,
                       COUNT(DISTINCT session_id) AS sessions,
                       MAX(timestamp) AS last_seen
                FROM usage_events
                WHERE timestamp >= NOW() - INTERVAL '7 days'
                GROUP BY user_id, user_role
                ORDER BY event_count DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()

    return [
        {
            "user_id": r[0],
            "user_role": r[1],
            "event_count": int(r[2]),
            "sessions": int(r[3]),
            "last_seen": r[4].isoformat() if r[4] else None,
        }
        for r in rows
    ]


def _empty_adoption() -> dict:
    """Return zero-filled adoption metrics (for fallback)."""
    return {
        "usage_daily_count": 0,
        "usage_weekly_count": 0,
        "usage_monthly_count": 0,
        "unique_users_daily": 0,
        "unique_users_weekly": 0,
        "unique_users_monthly": 0,
        "sessions_per_user_avg": 0.0,
        "retention_rate_7d_pct": 0.0,
        "activation_rate_pct": 0.0,
        "power_users_count": 0,
        "dormant_users_count": 0,
    }


# ── Event subscribers (Fase 1.5) ──────────────────────────────────────────
# This module listens to events from core.events. Domain code (chat, stream)
# emits "user.chat_started" and "user.message_sent" without knowing that
# metrics exists. This decouples the domain from observability.

from core.events import subscribe  # noqa: E402


def _on_chat_started(
    user_id: int, user_role: str, thread_id: str,
    session_id: str = "", **_: Any,
) -> None:
    record_event(
        user_id=user_id, user_role=user_role,
        event_type="chat_started", thread_id=thread_id, session_id=session_id,
    )


def _on_message_sent(
    user_id: int, user_role: str, thread_id: str,
    session_id: str = "", **_: Any,
) -> None:
    record_event(
        user_id=user_id, user_role=user_role,
        event_type="message_sent", thread_id=thread_id, session_id=session_id,
    )


subscribe("user.chat_started", _on_chat_started)
subscribe("user.message_sent", _on_message_sent)
