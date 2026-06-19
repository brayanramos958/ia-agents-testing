"""
Thread state persistence for conversation resilience.

This module owns the ``thread_metadata`` table in PostgreSQL — a small sidecar
table that lets the agent survive LLM rate-limit failures without losing the
user's conversation.

Why a sidecar table and not the LangGraph checkpoint:
  The checkpoint already stores the full message history. But when the LLM
  fails with 429 BEFORE the message is persisted, the user has no way to
  continue. We need to persist the user's message AND a timestamp BEFORE
  the LLM call, then read it back when a retry or follow-up arrives.

Schema:
    thread_metadata (
        thread_id           TEXT  PRIMARY KEY,    -- matches LangGraph thread_id
        last_user_message   TEXT,                 -- the last message text
        last_user_message_at TIMESTAMPTZ,         -- UTC timestamp
        created_at          TIMESTAMPTZ DEFAULT now()
    )

Window of continuity (configurable via settings.continuity_window_seconds):
  When a new request comes in for a thread:
    - If now - last_user_message_at > window: NEW conversation.
    - If now - last_user_message_at <= window AND text matches: DUPLICATE →
      continue with the existing thread, do NOT re-add the message.
    - Otherwise: continue with the existing thread, persist new message.

This module is intentionally side-effect-free on import: nothing happens until
``init_thread_metadata_table()`` is called during application startup.
"""

from datetime import datetime, timezone
from typing import Optional

import psycopg

from config.settings import settings
from core.logging import get_logger

_log = get_logger(__name__)


_DDL = """
CREATE TABLE IF NOT EXISTS thread_metadata (
    thread_id            TEXT PRIMARY KEY,
    last_user_message    TEXT,
    last_user_message_at TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_thread_metadata_last_at
    ON thread_metadata (last_user_message_at);
"""


async def init_thread_metadata_table() -> None:
    """
    Create the thread_metadata table if it doesn't exist.

    Called once during FastAPI lifespan startup. Idempotent — safe to call
    multiple times (CREATE IF NOT EXISTS).

    If PostgreSQL is unreachable, logs a warning and continues. The agent
    must still be able to serve requests even when metadata persistence
    is degraded — the worst case is that conversation continuity is lost
    on the next LLM failure, which is the same behaviour as before this
    module existed.
    """
    dsn = settings.postgres_dsn
    if not dsn:
        _log.warning("thread_metadata init skipped: POSTGRES_DSN not configured")
        return

    try:
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute(_DDL)
            await conn.commit()
        _log.info("thread_metadata table ready")
    except (psycopg.Error, ConnectionError, TimeoutError) as exc:
        _log.warning(
            "thread_metadata init failed (continuity degraded): %s",
            exc,
        )


async def get_thread_metadata(thread_id: str) -> Optional[dict]:
    """
    Read the metadata row for a thread. Returns None if not found or on error.

    Failures are logged at debug and return None — the caller treats None
    as "no previous conversation" and proceeds with the new message.

    Returns:
        dict with keys: last_user_message, last_user_message_at, created_at
        or None if the row doesn't exist.
    """
    dsn = settings.postgres_dsn
    if not dsn or not thread_id:
        return None

    try:
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    SELECT last_user_message, last_user_message_at, created_at
                    FROM thread_metadata
                    WHERE thread_id = %s
                    """,
                    (thread_id,),
                )
                row = await cur.fetchone()
                if row is None:
                    return None
                return {
                    "last_user_message": row[0],
                    "last_user_message_at": row[1],
                    "created_at": row[2],
                }
    except (psycopg.Error, ConnectionError, TimeoutError) as exc:
        _log.debug("get_thread_metadata failed for %s: %s", thread_id, exc)
        return None


async def set_thread_metadata(
    thread_id: str,
    last_user_message: str,
    last_user_message_at: Optional[datetime] = None,
) -> bool:
    """
    Upsert the metadata row for a thread.

    Args:
        thread_id: The conversation thread (matches LangGraph thread_id).
        last_user_message: The user's message text to remember.
        last_user_message_at: When the message was received. Defaults to now (UTC).

    Returns:
        True on success, False on any DB error. Failures are logged at debug
        — a failed write does not block the user's request, the worst case
        is losing continuity on the next LLM failure.
    """
    dsn = settings.postgres_dsn
    if not dsn or not thread_id:
        return False

    if last_user_message_at is None:
        last_user_message_at = datetime.now(timezone.utc)

    try:
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO thread_metadata
                        (thread_id, last_user_message, last_user_message_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (thread_id) DO UPDATE
                    SET last_user_message    = EXCLUDED.last_user_message,
                        last_user_message_at = EXCLUDED.last_user_message_at
                    """,
                    (thread_id, last_user_message, last_user_message_at),
                )
            await conn.commit()
        return True
    except (psycopg.Error, ConnectionError, TimeoutError) as exc:
        _log.debug("set_thread_metadata failed for %s: %s", thread_id, exc)
        return False


async def delete_thread_metadata(thread_id: str) -> bool:
    """
    Remove the metadata row for a thread. Used when a new conversation
    is explicitly started (e.g. user_id changes mid-thread).
    """
    dsn = settings.postgres_dsn
    if not dsn or not thread_id:
        return False

    try:
        async with await psycopg.AsyncConnection.connect(dsn) as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "DELETE FROM thread_metadata WHERE thread_id = %s",
                    (thread_id,),
                )
            await conn.commit()
        return True
    except (psycopg.Error, ConnectionError, TimeoutError) as exc:
        _log.debug("delete_thread_metadata failed for %s: %s", thread_id, exc)
        return False


def is_within_continuity_window(
    last_user_message_at: Optional[datetime],
    now: Optional[datetime] = None,
) -> bool:
    """
    Return True if ``last_user_message_at`` is within the configured continuity
    window from ``now`` (default: current UTC time).

    A None timestamp is treated as "outside the window" — the caller should
    start a fresh conversation.

    The comparison is done in UTC to avoid timezone surprises. Stored values
    are TIMESTAMPTZ so psycopg returns timezone-aware datetimes.
    """
    if last_user_message_at is None:
        return False
    if now is None:
        now = datetime.now(timezone.utc)

    # Normalise to UTC — psycopg returns aware datetimes but we are defensive.
    if last_user_message_at.tzinfo is None:
        last_user_message_at = last_user_message_at.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    elapsed = (now - last_user_message_at).total_seconds()
    return 0 <= elapsed <= settings.continuity_window_seconds


def is_duplicate_message(
    last_user_message: Optional[str],
    new_message: str,
    last_user_message_at: Optional[datetime],
) -> bool:
    """
    Return True if ``new_message`` is identical to the last persisted user
    message AND we are still inside the continuity window.

    A duplicate is "the user resent the same message" — usually because the
    previous LLM call failed and they didn't see a reply. Per product spec
    we do NOT ignore the message; we just don't re-add it to the checkpoint.
    The LLM is then called with the existing thread state and produces a
    real answer based on the prior context.
    """
    if not last_user_message or not new_message:
        return False
    if not is_within_continuity_window(last_user_message_at):
        return False
    return last_user_message.strip() == new_message.strip()
