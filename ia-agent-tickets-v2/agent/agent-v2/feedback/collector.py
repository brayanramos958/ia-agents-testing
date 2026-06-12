"""
AI assistant feedback storage — PostgreSQL.

Persists ratings, comments, RAG usage and LLM cost tracking to PostgreSQL
(same DSN as the RAG vector store and LangGraph checkpointer).

ARCHITECTURE NOTE (2026-06-11 — migration from SQLite):
    The original implementation used a local SQLite file. For production
    this had three problems:
      1. SQLite serialises all writers — bottleneck under concurrent load
      2. The file lived inside the container — lost on container restart
      3. Backups were decoupled from the main PostgreSQL backup
    All agent state (RAG, checkpointer, cache, feedback) now lives in
    the same PostgreSQL instance, owned by ``settings.postgres_dsn``.

Public API (unchanged from SQLite version — call sites in tools/rag_tools.py
continue to work as-is):

    FeedbackCollector().record(...)
    FeedbackCollector().record_rag_usage(...)
    FeedbackCollector().record_llm_usage(...)
    FeedbackCollector().get_summary()
    FeedbackCollector().get_rag_summary()
    FeedbackCollector().get_llm_summary()
    FeedbackCollector().get_recent(...)

Each method is wrapped in a thread lock so concurrent FastAPI workers do
not race. (psycopg connections themselves are NOT thread-safe, so we keep
one per call rather than sharing across threads.)
"""

import threading
from datetime import datetime
from typing import Any

import psycopg

from config.settings import settings
from feedback.schemas import AgentFeedbackRecord


def _ensure_schema() -> None:
    """Create the 3 tables if they do not exist. Idempotent."""
    dsn = settings.postgres_dsn
    if not dsn:
        raise RuntimeError(
            "settings.postgres_dsn is not configured — cannot use PostgreSQL feedback store"
        )

    with psycopg.connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            # ── agent_feedback ──────────────────────────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_feedback (
                    id            SERIAL PRIMARY KEY,
                    ticket_id     INTEGER,
                    ticket_name   TEXT,
                    user_id       INTEGER NOT NULL,
                    rating        INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                    comment       TEXT DEFAULT '',
                    feedback_type TEXT NOT NULL
                        CHECK(feedback_type IN ('ticket_created', 'solution_suggested')),
                    created_at    TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_feedback_user ON agent_feedback(user_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_feedback_type ON agent_feedback(feedback_type)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_agent_feedback_created ON agent_feedback(created_at)"
            )

            # ── rag_usage ───────────────────────────────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS rag_usage (
                    id              SERIAL PRIMARY KEY,
                    user_id         INTEGER,
                    user_role       TEXT,
                    query           TEXT,
                    solutions_found INTEGER NOT NULL DEFAULT 0,
                    top_score       REAL DEFAULT 0.0,
                    threshold_used  REAL DEFAULT 0.0,
                    latency_ms      REAL DEFAULT 0.0,
                    created_at      TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_usage_created ON rag_usage(created_at)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_usage_hits ON rag_usage(solutions_found)"
            )

            # ── llm_usage ───────────────────────────────────────────────────
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS llm_usage (
                    id                 SERIAL PRIMARY KEY,
                    thread_id          TEXT,
                    user_id            INTEGER,
                    user_role          TEXT,
                    provider_used      TEXT,
                    model_used         TEXT,
                    tokens_input       INTEGER DEFAULT 0,
                    tokens_output      INTEGER DEFAULT 0,
                    tokens_total       INTEGER DEFAULT 0,
                    latency_ms         REAL DEFAULT 0.0,
                    fallback_triggered INTEGER DEFAULT 0,
                    cost_usd           REAL DEFAULT 0.0,
                    error              TEXT DEFAULT '',
                    created_at         TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_usage_thread ON llm_usage(thread_id)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at)"
            )
            cur.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_usage_provider ON llm_usage(provider_used)"
            )


# Run schema migration on first import (idempotent).
_ensure_schema()


class FeedbackCollector:
    """
    Thread-safe wrapper around PostgreSQL for agent feedback.

    Each public method opens its own short-lived psycopg connection
    (PostgreSQL connections are not thread-safe and psycopg recommends
    a fresh connection per short transaction). The threading.Lock below
    serialises access so two FastAPI workers don't write concurrently
    to the same row.

    For high-throughput callers the same connection is reused within a
    single ``with`` block — see the methods below.
    """

    _lock = threading.Lock()

    def __init__(self, dsn: str = None):
        """
        Args:
            dsn: Override the default DSN from settings. Useful in tests
                 to point to a temporary PostgreSQL instance.
        """
        self._dsn = dsn or settings.postgres_dsn
        if not self._dsn:
            raise RuntimeError(
                "FeedbackCollector requires settings.postgres_dsn "
                "(set BACKEND=postgres and configure POSTGRES_DSN)"
            )

    # ── agent_feedback ─────────────────────────────────────────────────────

    def record(
        self,
        ticket_id: int | None,
        user_id: int,
        rating: int,
        comment: str,
        feedback_type: str,
        ticket_name: str = None,
    ) -> dict:
        """
        Store one feedback entry.

        Returns:
            {"success": True, "feedback_id": int}
            {"success": False, "error": str}
        """
        if not 1 <= rating <= 5:
            return {"success": False, "error": "Rating must be between 1 and 5"}

        valid_types = ("ticket_created", "solution_suggested")
        if feedback_type not in valid_types:
            return {"success": False, "error": f"feedback_type must be one of {valid_types}"}

        with self._lock:
            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO agent_feedback
                           (ticket_id, ticket_name, user_id, rating, comment, feedback_type)
                           VALUES (%s, %s, %s, %s, %s, %s)
                           RETURNING id""",
                        (ticket_id, ticket_name, user_id, rating, comment, feedback_type),
                    )
                    feedback_id = cur.fetchone()[0]
                conn.commit()
        return {"success": True, "feedback_id": feedback_id}

    def get_summary(self) -> dict:
        """Aggregate stats for reporting and agent improvement."""
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT COUNT(*), COALESCE(AVG(rating), 0) FROM agent_feedback"
                )
                total, avg = cur.fetchone()

                cur.execute(
                    """SELECT feedback_type, COUNT(*), COALESCE(AVG(rating), 0)
                       FROM agent_feedback
                       GROUP BY feedback_type"""
                )
                by_type = cur.fetchall()

        return {
            "total_feedback": int(total or 0),
            "average_rating": round(float(avg or 0.0), 2),
            "by_type": [
                {
                    "feedback_type": row[0],
                    "count": int(row[1]),
                    "avg_rating": round(float(row[2]), 2),
                }
                for row in by_type
            ],
        }

    def get_recent(self, limit: int = 20) -> list:
        """Returns the most recent feedback entries."""
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT id, ticket_id, ticket_name, user_id, rating,
                              comment, feedback_type, created_at
                       FROM agent_feedback
                       ORDER BY created_at DESC
                       LIMIT %s""",
                    (limit,),
                )
                rows = cur.fetchall()
        return [
            {
                "id": r[0],
                "ticket_id": r[1],
                "ticket_name": r[2],
                "user_id": r[3],
                "rating": r[4],
                "comment": r[5],
                "feedback_type": r[6],
                "created_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]

    # ── RAG usage tracking ──────────────────────────────────────────────────

    def record_rag_usage(
        self,
        user_id: int | None,
        user_role: str | None,
        query: str,
        solutions_found: bool,
        top_score: float,
        threshold_used: float,
        latency_ms: float,
    ) -> dict:
        """
        Records one suggest_solution() call.

        Returns:
            {"success": True, "rag_usage_id": int}
        """
        if query and len(query) > 500:
            query = query[:497] + "..."

        with self._lock:
            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO rag_usage
                           (user_id, user_role, query, solutions_found,
                            top_score, threshold_used, latency_ms)
                           VALUES (%s, %s, %s, %s, %s, %s, %s)
                           RETURNING id""",
                        (
                            user_id,
                            user_role or "",
                            query or "",
                            1 if solutions_found else 0,
                            round(top_score, 4),
                            round(threshold_used, 4),
                            round(latency_ms, 2),
                        ),
                    )
                    rag_id = cur.fetchone()[0]
                conn.commit()
        return {"success": True, "rag_usage_id": rag_id}

    def get_rag_summary(self) -> dict:
        """Aggregate RAG usage statistics for /agent/metrics."""
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT
                           COUNT(*),
                           COALESCE(SUM(CASE WHEN solutions_found = 1 THEN 1 ELSE 0 END), 0),
                           COALESCE(AVG(CASE WHEN solutions_found = 1 THEN top_score ELSE NULL END), 0),
                           COALESCE(AVG(latency_ms), 0)
                       FROM rag_usage"""
                )
                row = cur.fetchone()
        total = int(row[0] or 0)
        hits = int(row[1] or 0)
        avg_score = round(float(row[2] or 0.0), 4)
        avg_latency = round(float(row[3] or 0.0), 2)
        hit_rate = round(hits / total, 4) if total > 0 else 0.0
        return {
            "rag_total_calls": total,
            "rag_hits": hits,
            "rag_hit_rate": hit_rate,
            "rag_avg_score": avg_score,
            "rag_avg_latency_ms": avg_latency,
        }

    # ── LLM usage tracking ──────────────────────────────────────────────────

    def record_llm_usage(
        self,
        thread_id: str,
        user_id: int | None,
        user_role: str | None,
        provider_used: str,
        model_used: str,
        tokens_input: int,
        tokens_output: int,
        latency_ms: float,
        fallback_triggered: bool = False,
        cost_usd: float = 0.0,
        error: str = "",
    ) -> dict:
        """
        Records one LLM invocation.

        Returns:
            {"success": True, "llm_usage_id": int}
        """
        with self._lock:
            with psycopg.connect(self._dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """INSERT INTO llm_usage
                           (thread_id, user_id, user_role, provider_used, model_used,
                            tokens_input, tokens_output, tokens_total,
                            latency_ms, fallback_triggered, cost_usd, error)
                           VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                           RETURNING id""",
                        (
                            thread_id or "",
                            user_id,
                            user_role or "",
                            provider_used or "",
                            model_used or "",
                            int(tokens_input or 0),
                            int(tokens_output or 0),
                            int(tokens_input or 0) + int(tokens_output or 0),
                            round(latency_ms, 2),
                            1 if fallback_triggered else 0,
                            round(cost_usd, 6),
                            (error or "")[:500],
                        ),
                    )
                    llm_id = cur.fetchone()[0]
                conn.commit()
        return {"success": True, "llm_usage_id": llm_id}

    def get_llm_summary(self) -> dict:
        """Aggregate LLM usage statistics for /agent/metrics."""
        with psycopg.connect(self._dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """SELECT
                           COUNT(*),
                           COALESCE(SUM(tokens_input),  0),
                           COALESCE(SUM(tokens_output), 0),
                           COALESCE(SUM(tokens_total),  0),
                           COALESCE(SUM(cost_usd),       0),
                           COALESCE(AVG(latency_ms),     0),
                           COALESCE(SUM(fallback_triggered), 0),
                           COALESCE(SUM(CASE WHEN error != '' THEN 1 ELSE 0 END), 0)
                       FROM llm_usage"""
                )
                overall = cur.fetchone()
                total = int(overall[0] or 0)

                if total == 0:
                    return {
                        "total_calls": 0,
                        "total_tokens": 0,
                        "total_input_tokens": 0,
                        "total_output_tokens": 0,
                        "total_cost_usd": 0.0,
                        "avg_latency_ms": 0.0,
                        "avg_tokens_per_call": 0.0,
                        "fallback_count": 0,
                        "fallback_rate": 0.0,
                        "error_count": 0,
                        "by_provider": [],
                        "by_model": [],
                        "top_threads_by_cost": [],
                    }

                cur.execute(
                    """SELECT provider_used, COUNT(*), COALESCE(SUM(cost_usd), 0)
                       FROM llm_usage
                       GROUP BY provider_used
                       ORDER BY COUNT(*) DESC"""
                )
                by_provider = cur.fetchall()

                cur.execute(
                    """SELECT model_used, COUNT(*), COALESCE(SUM(cost_usd), 0)
                       FROM llm_usage
                       GROUP BY model_used
                       ORDER BY COUNT(*) DESC
                       LIMIT 10"""
                )
                by_model = cur.fetchall()

                cur.execute(
                    """SELECT thread_id,
                              MAX(user_role) AS user_role,
                              COUNT(*) AS turns,
                              COALESCE(SUM(cost_usd), 0) AS cost,
                              COALESCE(SUM(tokens_total), 0) AS tokens
                       FROM llm_usage
                       WHERE thread_id != ''
                       GROUP BY thread_id
                       ORDER BY cost DESC
                       LIMIT 5"""
                )
                top_threads = cur.fetchall()

        return {
            "total_calls": total,
            "total_tokens": int(overall[3] or 0),
            "total_input_tokens": int(overall[1] or 0),
            "total_output_tokens": int(overall[2] or 0),
            "total_cost_usd": round(float(overall[4] or 0.0), 6),
            "avg_latency_ms": round(float(overall[5] or 0.0), 2),
            "avg_tokens_per_call": round(int(overall[3] or 0) / total, 2),
            "fallback_count": int(overall[6] or 0),
            "fallback_rate": round(int(overall[6] or 0) / total, 4),
            "error_count": int(overall[7] or 0),
            "by_provider": [
                {
                    "provider": row[0] or "unknown",
                    "count": int(row[1]),
                    "cost_usd": round(float(row[2]), 6),
                }
                for row in by_provider
            ],
            "by_model": [
                {
                    "model": row[0] or "unknown",
                    "count": int(row[1]),
                    "cost_usd": round(float(row[2]), 6),
                }
                for row in by_model
            ],
            "top_threads_by_cost": [
                {
                    "thread_id": row[0],
                    "user_role": row[1] or "",
                    "turns": int(row[2]),
                    "cost_usd": round(float(row[3]), 6),
                    "tokens": int(row[4]),
                }
                for row in top_threads
            ],
        }
