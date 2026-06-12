"""
Ticket creation tracking — Fase 1.6 del PLAN_METRICS.md.

Tracks the full lifecycle of ticket creation: from first user message
to successful ticket creation (or abandonment). Provides insights into
how long it takes to create a ticket and user satisfaction.

Architecture:
  - ticket_creation_events table in PostgreSQL
  - session_id links to usage_events (correlation)
  - satisfaction_rating captured separately (user gives rating AFTER creation)

Public API:
    start_creation(user_id, user_role, thread_id, session_id)
        -> creation_event_id  (call this on first message that hints at creation)
    complete_creation(creation_event_id, ticket_id, ticket_name, llm_calls)
        -> duration_seconds
    abandon_creation(creation_event_id)
    rate_creation(creation_event_id, rating, comment)
    get_creation_summary() -> dict with all KPIs
    get_abandoned_creations(limit=20)
"""

import logging
from typing import Any, Dict, Optional
import psycopg

from config.settings import settings

logger = logging.getLogger(__name__)


def _ensure_schema() -> None:
    """Create ticket_creation_events table. Idempotent."""
    dsn = settings.postgres_dsn
    if not dsn:
        raise RuntimeError("settings.postgres_dsn is not configured")

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS ticket_creation_events (
                    id SERIAL PRIMARY KEY,
                    ticket_id INTEGER,
                    ticket_name TEXT,
                    user_id INTEGER NOT NULL,
                    user_role TEXT NOT NULL,
                    thread_id TEXT,
                    session_id TEXT,
                    started_at TIMESTAMPTZ NOT NULL,
                    completed_at TIMESTAMPTZ,
                    abandoned_at TIMESTAMPTZ,
                    total_duration_seconds REAL,
                    messages_count INTEGER DEFAULT 0,
                    tool_calls_count INTEGER DEFAULT 0,
                    llm_calls_count INTEGER DEFAULT 0,
                    created BOOLEAN DEFAULT FALSE,
                    duplicate_of_ticket_id INTEGER,
                    satisfaction_rating INTEGER,
                    satisfaction_comment TEXT,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tce_user
                ON ticket_creation_events(user_id)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tce_completed
                ON ticket_creation_events(completed_at)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tce_created
                ON ticket_creation_events(created)
            """)
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_tce_session
                ON ticket_creation_events(session_id)
            """)


# Run on first import
_ensure_schema()


def start_creation(
    user_id: int,
    user_role: str,
    thread_id: Optional[str] = None,
    session_id: Optional[str] = None,
) -> int:
    """
    Mark the start of a ticket creation flow.
    Returns creation_event_id.

    Called when the LLM first invokes create_ticket tool (or detects
    creation intent from the user message).
    """
    dsn = settings.postgres_dsn
    if not dsn:
        return 0

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO ticket_creation_events
                    (user_id, user_role, thread_id, session_id, started_at,
                     messages_count, tool_calls_count, llm_calls_count)
                    VALUES (%s, %s, %s, %s, NOW(), 1, 0, 0)
                    RETURNING id
                """, (user_id, user_role, thread_id, session_id))
                event_id = cur.fetchone()[0]
            conn.commit()
        return event_id
    except psycopg.Error as exc:
        logger.warning("Failed to start creation event: %s", exc)
        return 0


def complete_creation(
    creation_event_id: int,
    ticket_id: int,
    ticket_name: str,
    llm_calls: int = 0,
    duplicate_of_ticket_id: Optional[int] = None,
) -> float:
    """
    Mark a creation flow as successfully completed.
    Returns duration in seconds.
    """
    dsn = settings.postgres_dsn
    if not dsn or not creation_event_id:
        return 0.0

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE ticket_creation_events
                    SET completed_at = NOW(),
                        total_duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at)),
                        created = TRUE,
                        ticket_id = %s,
                        ticket_name = %s,
                        llm_calls_count = %s,
                        duplicate_of_ticket_id = %s
                    WHERE id = %s
                    RETURNING total_duration_seconds
                """, (ticket_id, ticket_name, llm_calls, duplicate_of_ticket_id, creation_event_id))
                row = cur.fetchone()
            conn.commit()
        return float(row[0]) if row else 0.0
    except psycopg.Error as exc:
        logger.warning("Failed to complete creation event: %s", exc)
        return 0.0


def abandon_creation(creation_event_id: int) -> None:
    """Mark a creation flow as abandoned (user left without creating)."""
    dsn = settings.postgres_dsn
    if not dsn or not creation_event_id:
        return

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE ticket_creation_events
                    SET abandoned_at = NOW(),
                        total_duration_seconds = EXTRACT(EPOCH FROM (NOW() - started_at)),
                        created = FALSE
                    WHERE id = %s AND completed_at IS NULL AND abandoned_at IS NULL
                """, (creation_event_id,))
            conn.commit()
    except psycopg.Error as exc:
        logger.warning("Failed to abandon creation event: %s", exc)


def increment_message_count(creation_event_id: int, llm_calls: int = 1) -> None:
    """Track that another message was exchanged in this creation flow."""
    dsn = settings.postgres_dsn
    if not dsn or not creation_event_id:
        return

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE ticket_creation_events
                    SET messages_count = messages_count + 1,
                        llm_calls_count = llm_calls_count + %s
                    WHERE id = %s AND completed_at IS NULL AND abandoned_at IS NULL
                """, (llm_calls, creation_event_id))
            conn.commit()
    except psycopg.Error as exc:
        logger.warning("Failed to increment message count: %s", exc)


def rate_creation(creation_event_id: int, rating: int, comment: str = "") -> None:
    """Record user's satisfaction rating for the creation flow."""
    dsn = settings.postgres_dsn
    if not dsn or not creation_event_id:
        return

    try:
        with psycopg.connect(dsn) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    UPDATE ticket_creation_events
                    SET satisfaction_rating = %s,
                        satisfaction_comment = %s
                    WHERE id = %s
                """, (rating, comment, creation_event_id))
            conn.commit()
    except psycopg.Error as exc:
        logger.warning("Failed to rate creation: %s", exc)


def get_creation_summary() -> dict:
    """
    Compute ticket creation metrics. Single SQL pass.

    Returns dict with all KPIs (Fase 1.6).
    """
    dsn = settings.postgres_dsn
    if not dsn:
        return _empty_creation()

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            # Daily/weekly created
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE created = TRUE AND completed_at >= CURRENT_DATE) AS daily,
                    COUNT(*) FILTER (WHERE created = TRUE AND completed_at >= NOW() - INTERVAL '7 days') AS weekly
                FROM ticket_creation_events
            """)
            daily, weekly = cur.fetchone()

            # Time stats (avg, median, p95)
            cur.execute("""
                SELECT
                    COALESCE(AVG(total_duration_seconds), 0) AS avg_dur,
                    COALESCE(PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY total_duration_seconds), 0) AS median_dur,
                    COALESCE(PERCENTILE_CONT(0.95) WITHIN GROUP (ORDER BY total_duration_seconds), 0) AS p95_dur
                FROM ticket_creation_events
                WHERE created = TRUE AND total_duration_seconds IS NOT NULL
            """)
            avg_dur, median_dur, p95_dur = cur.fetchone()

            # Abandoned count
            cur.execute("""
                SELECT
                    COUNT(*) FILTER (WHERE abandoned_at IS NOT NULL) AS abandoned,
                    COUNT(*) AS total_started
                FROM ticket_creation_events
                WHERE started_at >= NOW() - INTERVAL '30 days'
            """)
            abandoned, total_started = cur.fetchone()

            # First-message creations
            cur.execute("""
                SELECT COUNT(*) FROM ticket_creation_events
                WHERE created = TRUE AND messages_count = 1
            """)
            first_msg = cur.fetchone()[0]

            # Total created (for ratio)
            cur.execute("""
                SELECT COUNT(*) FROM ticket_creation_events WHERE created = TRUE
            """)
            total_created = cur.fetchone()[0] or 0

            # Avg messages per ticket
            cur.execute("""
                SELECT COALESCE(AVG(messages_count), 0) FROM ticket_creation_events
                WHERE created = TRUE
            """)
            avg_msgs = cur.fetchone()[0] or 0

            # Duplicate detection rate
            cur.execute("""
                SELECT
                    COALESCE(
                        100.0 * COUNT(*) FILTER (WHERE duplicate_of_ticket_id IS NOT NULL) / NULLIF(COUNT(*), 0),
                        0
                    )
                FROM ticket_creation_events
                WHERE created = TRUE
            """)
            dup_rate = cur.fetchone()[0] or 0

            # Satisfaction
            cur.execute("""
                SELECT
                    COALESCE(AVG(satisfaction_rating), 0) AS avg_rating,
                    COUNT(satisfaction_rating) AS total_ratings,
                    COALESCE(
                        100.0 * COUNT(*) FILTER (WHERE satisfaction_rating >= 4) / NULLIF(COUNT(satisfaction_rating), 0),
                        0
                    ) AS pct_positive
                FROM ticket_creation_events
                WHERE satisfaction_rating IS NOT NULL
            """)
            avg_rating, total_ratings, pct_positive = cur.fetchone()

    abandoned_rate = (100.0 * abandoned / total_started) if total_started > 0 else 0
    first_msg_pct = (100.0 * first_msg / total_created) if total_created > 0 else 0

    return {
        "tickets_created_daily": int(daily or 0),
        "tickets_created_weekly": int(weekly or 0),
        "avg_creation_time_seconds": round(float(avg_dur or 0), 2),
        "median_creation_time_seconds": round(float(median_dur or 0), 2),
        "p95_creation_time_seconds": round(float(p95_dur or 0), 2),
        "tickets_abandoned_count": int(abandoned or 0),
        "tickets_abandoned_rate_pct": round(float(abandoned_rate), 2),
        "tickets_created_in_first_message_pct": round(float(first_msg_pct), 2),
        "avg_messages_per_ticket": round(float(avg_msgs), 2),
        "duplicate_detection_rate_pct": round(float(dup_rate), 2),
        "satisfaction_avg": round(float(avg_rating or 0), 2),
        "satisfaction_pct": round(float(pct_positive or 0), 2),
        "total_ratings_count": int(total_ratings or 0),
    }


def get_abandoned_creations(limit: int = 20) -> list:
    """Return the most recent abandoned creation flows (for UX research)."""
    dsn = settings.postgres_dsn
    if not dsn:
        return []

    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT id, user_id, user_role, thread_id, session_id,
                       started_at, abandoned_at, total_duration_seconds,
                       messages_count
                FROM ticket_creation_events
                WHERE abandoned_at IS NOT NULL
                  AND completed_at IS NULL
                ORDER BY abandoned_at DESC
                LIMIT %s
            """, (limit,))
            rows = cur.fetchall()

    return [
        {
            "id": r[0],
            "user_id": r[1],
            "user_role": r[2],
            "thread_id": r[3],
            "session_id": r[4],
            "started_at": r[5].isoformat() if r[5] else None,
            "abandoned_at": r[6].isoformat() if r[6] else None,
            "duration_seconds": r[7],
            "messages_exchanged": r[8],
        }
        for r in rows
    ]


def _empty_creation() -> dict:
    """Return zero-filled creation metrics (for fallback)."""
    return {
        "tickets_created_daily": 0,
        "tickets_created_weekly": 0,
        "avg_creation_time_seconds": 0.0,
        "median_creation_time_seconds": 0.0,
        "p95_creation_time_seconds": 0.0,
        "tickets_abandoned_count": 0,
        "tickets_abandoned_rate_pct": 0.0,
        "tickets_created_in_first_message_pct": 0.0,
        "avg_messages_per_ticket": 0.0,
        "duplicate_detection_rate_pct": 0.0,
        "satisfaction_avg": 0.0,
        "satisfaction_pct": 0.0,
        "total_ratings_count": 0,
    }


# ── Event subscribers (Fase 1.6 refactor) ─────────────────────────────────
# These listen to events from core.events and handle tracking without
# the caller needing to manage creation_event_id.
# The old start_creation/complete_creation/abandon_creation are kept
# for backward compatibility (e.g., direct callers in tests).

from core.events import subscribe  # noqa: E402

# Track in-flight creation events by thread_id (in-memory)
# This is safe because FastAPI is single-process per worker; in a multi-worker
# setup we'd need Redis. For now, this is acceptable for our scale.
_inflight: Dict[str, int] = {}


def _on_creation_started(
    user_id: int, user_role: str, thread_id: str, session_id: str = "", **_: Any
) -> None:
    """Handle 'ticket.creation_started' event."""
    if not thread_id:
        return
    event_id = start_creation(
        user_id=user_id, user_role=user_role,
        thread_id=thread_id, session_id=session_id,
    )
    if event_id:
        _inflight[thread_id] = event_id


def _on_creation_completed(
    user_id: int, ticket_id: int, ticket_name: str = "",
    duplicate_of_ticket_id: Optional[int] = None, **_: Any,
) -> None:
    """Handle 'ticket.creation_completed' event."""
    if not user_id:
        return
    # Find the in-flight event by user_id (most recent for that user)
    # In a single-conversation flow, there should be exactly one
    # matching thread - we take the last one started.
    event_id = None
    for tid, eid in reversed(list(_inflight.items())):
        event_id = eid
        del _inflight[tid]
        break

    if event_id:
        complete_creation(
            creation_event_id=event_id,
            ticket_id=ticket_id,
            ticket_name=ticket_name,
            llm_calls=0,
            duplicate_of_ticket_id=duplicate_of_ticket_id,
        )


def _on_creation_abandoned(
    user_id: int, thread_id: str = "", **_: Any,
) -> None:
    """Handle 'ticket.creation_abandoned' event."""
    event_id = None
    if thread_id and thread_id in _inflight:
        event_id = _inflight.pop(thread_id)
    else:
        # Fallback: take any in-flight for this user
        for tid, eid in reversed(list(_inflight.items())):
            event_id = eid
            _inflight.pop(tid, None)
            break

    if event_id:
        abandon_creation(event_id)


# Wire up the listeners
subscribe("ticket.creation_started", _on_creation_started)
subscribe("ticket.creation_completed", _on_creation_completed)
subscribe("ticket.creation_abandoned", _on_creation_abandoned)
