"""
PostgreSQL-backed shared cache for multi-worker agent deployments.

The agent caches per-thread creator and resolver contexts (``agent_cache:dict``)
to avoid one Odoo round-trip per message in the same conversation. In a
single-process dev setup this works fine. In production with multiple uvicorn
workers (or multiple pods), each worker has its own in-memory cache, so
invalidation events must be propagated across processes.

This module provides a PostgreSQL-backed cache that lives in the same database
as the LangGraph checkpointer. All workers share it, so:
- A ``create_ticket`` invalidation in worker A is visible to worker B
  within a few milliseconds (next read sees ``NULL``)
- The cache is durable across restarts
- The TTL bounds memory growth

ARCHITECTURE NOTE (Fase 8 — async migration):
    All operations are ``async def`` and use ``psycopg.AsyncConnection``.
    Connections are short-lived per call (one connection per get/set/delete)
    — the overhead is minimal because psycopg's connection setup is fast
    (~5ms) and the queries themselves are indexed primary-key lookups.
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import psycopg

from config.settings import settings

logger = logging.getLogger(__name__)


class PostgreSQLCache:
    """
    Async key-value cache backed by PostgreSQL.

    Replaces the in-process ``_creator_context_cache: dict`` and
    ``_resolver_context_cache: dict`` in :mod:`core.agent` for multi-worker
    deployments.

    Usage:
        >>> cache = PostgreSQLCache(ttl_seconds=3600)
        >>> await cache.set("key", "value")
        >>> value = await cache.get("key")
        >>> await cache.delete("key")

    Schema:
        ``agent_cache(key TEXT PRIMARY KEY, value TEXT NOT NULL, expires_at TIMESTAMP NOT NULL)``

    Concurrency:
        - Each get/set/delete uses a fresh async connection (no shared state).
        - The ``ON CONFLICT`` clause in ``set`` handles concurrent writers
          without raising an exception.
        - ``clear_expired`` is a maintenance operation; call it periodically
          (e.g. once per hour) to bound table size.
    """

    def __init__(self, ttl_seconds: int = 3600) -> None:
        """
        Initialize the cache.

        Args:
            ttl_seconds: Time-to-live in seconds for cache entries.
                         Default 3600 (1 hour). Use 1800 for shorter freshness.
        """
        self._ttl = ttl_seconds
        self._dsn = settings.postgres_dsn
        self._lock = asyncio.Lock()  # Serialize schema creation on first use
        self._schema_ready = False

    async def _ensure_schema(self) -> None:
        """
        Create the ``agent_cache`` table and index if they don't exist.

        Idempotent. The lock ensures only one coroutine creates the schema
        in a multi-worker startup race.
        """
        if self._schema_ready:
            return
        async with self._lock:
            if self._schema_ready:
                return  # Double-check inside the lock
            try:
                async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
                    async with conn.cursor() as cur:
                        await cur.execute("""
                            CREATE TABLE IF NOT EXISTS agent_cache (
                                key TEXT PRIMARY KEY,
                                value TEXT NOT NULL,
                                expires_at TIMESTAMP NOT NULL
                            )
                        """)
                        await cur.execute("""
                            CREATE INDEX IF NOT EXISTS idx_agent_cache_expires
                                ON agent_cache(expires_at)
                        """)
                    await conn.commit()
                self._schema_ready = True
                logger.info("agent_cache_schema_ready")
            except Exception as exc:
                logger.error("agent_cache_schema_failed: %s", exc)
                # Don't raise — cache failures should not block agent startup.
                # Subsequent operations will retry schema creation.

    async def get(self, key: str) -> Optional[str]:
        """
        Return the cached value for ``key``, or ``None`` if missing or expired.

        Args:
            key: Cache key.

        Returns:
            The cached string value, or ``None`` if not found / expired.
        """
        await self._ensure_schema()
        try:
            async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT value FROM agent_cache "
                        "WHERE key = %s AND expires_at > NOW()",
                        (key,),
                    )
                    row = await cur.fetchone()
                    return row[0] if row else None
        except Exception as exc:
            logger.warning("agent_cache_get_failed key=%s: %s", key, exc)
            return None  # Cache failures are non-fatal

    async def set(self, key: str, value: str) -> bool:
        """
        Store a value in the cache, replacing any existing entry.

        Args:
            key: Cache key.
            value: String value to store.

        Returns:
            bool: ``True`` on success, ``False`` on failure.
        """
        await self._ensure_schema()
        expires = datetime.now() + timedelta(seconds=self._ttl)
        try:
            async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        """INSERT INTO agent_cache (key, value, expires_at)
                           VALUES (%s, %s, %s)
                           ON CONFLICT (key) DO UPDATE SET
                               value = EXCLUDED.value,
                               expires_at = EXCLUDED.expires_at""",
                        (key, value, expires),
                    )
                await conn.commit()
            return True
        except Exception as exc:
            logger.warning("agent_cache_set_failed key=%s: %s", key, exc)
            return False

    async def delete(self, key: str) -> bool:
        """
        Remove a key from the cache.

        Args:
            key: Cache key.

        Returns:
            bool: ``True`` on success, ``False`` on failure.
        """
        await self._ensure_schema()
        try:
            async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "DELETE FROM agent_cache WHERE key = %s", (key,),
                    )
                await conn.commit()
            return True
        except Exception as exc:
            logger.warning("agent_cache_delete_failed key=%s: %s", key, exc)
            return False

    async def clear_expired(self) -> int:
        """
        Delete all expired entries from the cache.

        Returns:
            int: Number of rows deleted, or ``-1`` on failure.
        """
        await self._ensure_schema()
        try:
            async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "DELETE FROM agent_cache WHERE expires_at <= NOW()"
                    )
                    deleted = cur.rowcount
                await conn.commit()
            return deleted
        except Exception as exc:
            logger.warning("agent_cache_clear_expired_failed: %s", exc)
            return -1

    async def size(self) -> int:
        """
        Return the number of non-expired entries in the cache.

        Returns:
            int: Entry count, or ``-1`` on failure.
        """
        await self._ensure_schema()
        try:
            async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
                async with conn.cursor() as cur:
                    await cur.execute(
                        "SELECT COUNT(*) FROM agent_cache WHERE expires_at > NOW()"
                    )
                    row = await cur.fetchone()
                    return int(row[0]) if row else 0
        except Exception as exc:
            logger.warning("agent_cache_size_failed: %s", exc)
            return -1
