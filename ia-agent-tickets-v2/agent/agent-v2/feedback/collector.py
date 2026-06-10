"""
AI assistant feedback storage.

Persists ratings and comments about the agent's helpfulness to a local SQLite DB.
Thread-safe via threading.Lock for concurrent FastAPI requests.

This is separate from the enterprise ticket system's satisfaction survey.
Use get_summary() to build reports for improving the agent over time.
"""

import sqlite3
import threading
from datetime import datetime

from config.settings import settings
from feedback.schemas import AgentFeedbackRecord


class FeedbackCollector:

    _lock = threading.Lock()

    def __init__(self, db_path: str = None):
        """
        Args:
            db_path: Override the default path from settings.
                     Useful in tests to point to a temporary DB.
        """
        self._db_path = db_path or settings.feedback_db_path
        self._ensure_table()

    def _ensure_table(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_feedback (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id    INTEGER,
                    ticket_name  TEXT,
                    user_id      INTEGER NOT NULL,
                    rating       INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5),
                    comment      TEXT DEFAULT '',
                    feedback_type TEXT NOT NULL
                        CHECK(feedback_type IN ('ticket_created', 'solution_suggested')),
                    created_at   DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # RAG usage table — one row per suggest_solution() call.
            # Tracks hit rate, score distribution, and latency for RAG quality monitoring.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS rag_usage (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id         INTEGER,
                    user_role       TEXT,
                    query           TEXT,
                    solutions_found INTEGER NOT NULL DEFAULT 0,
                    top_score       REAL DEFAULT 0.0,
                    threshold_used  REAL DEFAULT 0.0,
                    latency_ms      REAL DEFAULT 0.0,
                    created_at      DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Indexes for fast aggregation queries on the metrics endpoint
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_usage_created ON rag_usage(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_rag_usage_hits ON rag_usage(solutions_found)"
            )

            # LLM usage table — one row per ainvoke()/astream_events() call.
            # Captures tokens, latency, cost, and provider for /agent/metrics/llm.
            # Designed for cost monitoring — primary use case is to know how much
            # each conversation is consuming from the LLM budget.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS llm_usage (
                    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
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
                    created_at         DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Indexes for aggregation queries
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_usage_thread ON llm_usage(thread_id)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_usage_created ON llm_usage(created_at)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_llm_usage_provider ON llm_usage(provider_used)"
            )

    def record(self, ticket_id: int | None, user_id: int, rating: int,
               comment: str, feedback_type: str,
               ticket_name: str = None) -> dict:
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
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    """INSERT INTO agent_feedback
                       (ticket_id, ticket_name, user_id, rating, comment, feedback_type)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (ticket_id, ticket_name, user_id, rating, comment, feedback_type),
                )
                return {"success": True, "feedback_id": cursor.lastrowid}

    def get_summary(self) -> dict:
        """
        Returns aggregate stats for reporting and agent improvement.
        """
        with sqlite3.connect(self._db_path) as conn:
            total, avg = conn.execute(
                "SELECT COUNT(*), AVG(rating) FROM agent_feedback"
            ).fetchone()

            by_type = conn.execute(
                """SELECT feedback_type, COUNT(*), AVG(rating)
                   FROM agent_feedback
                   GROUP BY feedback_type"""
            ).fetchall()

        return {
            "total_feedback": total or 0,
            "average_rating": round(avg or 0.0, 2),
            "by_type": [
                {"feedback_type": row[0], "count": row[1], "avg_rating": round(row[2], 2)}
                for row in by_type
            ],
        }

    def get_recent(self, limit: int = 20) -> list:
        """Returns the most recent feedback entries."""
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                """SELECT * FROM agent_feedback ORDER BY created_at DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]

    # ── RAG usage tracking (Phase 2) ────────────────────────────────────────

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

        Args:
            user_id: Authenticated user who triggered the call
            user_role: 'creador' | 'resueltor' | 'supervisor'
            query: The user's problem description (truncated to 500 chars)
            solutions_found: True if confidence > threshold
            top_score: Highest similarity score returned (0.0 if no results)
            threshold_used: The confidence threshold applied
            latency_ms: Time spent in the RAG search

        Returns:
            {"success": True, "rag_usage_id": int}
        """
        # Defensive truncation — the RAG query is free text, could be huge
        if query and len(query) > 500:
            query = query[:497] + "..."

        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    """INSERT INTO rag_usage
                       (user_id, user_role, query, solutions_found,
                        top_score, threshold_used, latency_ms)
                       VALUES (?, ?, ?, ?, ?, ?, ?)""",
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
                return {"success": True, "rag_usage_id": cursor.lastrowid}

    def get_rag_summary(self) -> dict:
        """
        Aggregate RAG usage statistics for /agent/metrics.

        Returns:
            {
                "rag_total_calls": int,
                "rag_hits": int,
                "rag_hit_rate": float,    # hits / total (0.0 if no calls)
                "rag_avg_score": float,   # avg of top_score across HITS only
                "rag_avg_latency_ms": float,
            }
        """
        with sqlite3.connect(self._db_path) as conn:
            row = conn.execute(
                """SELECT
                       COUNT(*),
                       SUM(CASE WHEN solutions_found = 1 THEN 1 ELSE 0 END),
                       AVG(CASE WHEN solutions_found = 1 THEN top_score ELSE NULL END),
                       AVG(latency_ms)
                   FROM rag_usage"""
            ).fetchone()

            total = row[0] or 0
            hits = row[1] or 0
            avg_score = round(row[2] or 0.0, 4)
            avg_latency = round(row[3] or 0.0, 2)
            hit_rate = round(hits / total, 4) if total > 0 else 0.0

        return {
            "rag_total_calls": total,
            "rag_hits": hits,
            "rag_hit_rate": hit_rate,
            "rag_avg_score": avg_score,
            "rag_avg_latency_ms": avg_latency,
        }

    # ── LLM usage tracking (Phase 3) ────────────────────────────────────────

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

        Captures all metrics needed for /agent/metrics/llm:
        - Token counts (input/output) — extracted from response_metadata.usage
        - Latency — wall time around ainvoke()/astream_events()
        - Provider and model — from settings + fallback chain detection
        - Cost — calculated from token counts (DeepSeek V4 Pro via OpenCode Go)
        - Fallback — True if a primary provider failure triggered fallback
        - Error — error message if the call failed (rows with error still get tracked)

        Args:
            thread_id: Conversation thread (for cost-per-conversation aggregation)
            user_id: Authenticated user who triggered the call
            user_role: 'creador' | 'resueltor' | 'supervisor'
            provider_used: 'vercel' | 'groq' | 'ollama'
            model_used: model name as known to the provider
            tokens_input: prompt tokens
            tokens_output: completion tokens
            latency_ms: wall time
            fallback_triggered: True if fallback was used
            cost_usd: pre-calculated cost in USD
            error: error message if call failed

        Returns:
            {"success": True, "llm_usage_id": int}
        """
        with self._lock:
            with sqlite3.connect(self._db_path) as conn:
                cursor = conn.execute(
                    """INSERT INTO llm_usage
                       (thread_id, user_id, user_role, provider_used, model_used,
                        tokens_input, tokens_output, tokens_total,
                        latency_ms, fallback_triggered, cost_usd, error)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
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
                        (error or "")[:500],  # truncate long error messages
                    ),
                )
                return {"success": True, "llm_usage_id": cursor.lastrowid}

    def get_llm_summary(self) -> dict:
        """
        Aggregate LLM usage statistics for /agent/metrics.

        Returns:
            {
                "total_calls": int,
                "total_tokens": int,
                "total_input_tokens": int,
                "total_output_tokens": int,
                "total_cost_usd": float,
                "avg_latency_ms": float,
                "avg_tokens_per_call": float,
                "fallback_count": int,
                "fallback_rate": float,     # 0.0 if no calls
                "error_count": int,
                "by_provider": list[dict],  # [{"provider": str, "count": int, "cost_usd": float}, ...]
                "by_model": list[dict],     # [{"model": str, "count": int, "cost_usd": float}, ...]
                "top_threads_by_cost": list[dict],  # top 5 most expensive conversations
            }
        """
        with sqlite3.connect(self._db_path) as conn:
            conn.row_factory = sqlite3.Row

            # Overall aggregates
            overall = conn.execute(
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
            ).fetchone()

            total = overall[0] or 0
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

            # By provider
            by_provider = conn.execute(
                """SELECT provider_used, COUNT(*), COALESCE(SUM(cost_usd), 0)
                   FROM llm_usage
                   GROUP BY provider_used
                   ORDER BY COUNT(*) DESC"""
            ).fetchall()

            # By model
            by_model = conn.execute(
                """SELECT model_used, COUNT(*), COALESCE(SUM(cost_usd), 0)
                   FROM llm_usage
                   GROUP BY model_used
                   ORDER BY COUNT(*) DESC
                   LIMIT 10"""
            ).fetchall()

            # Top threads by cost
            top_threads = conn.execute(
                """SELECT thread_id,
                          user_role,
                          COUNT(*) AS turns,
                          COALESCE(SUM(cost_usd), 0) AS cost,
                          COALESCE(SUM(tokens_total), 0) AS tokens
                   FROM llm_usage
                   WHERE thread_id != ''
                   GROUP BY thread_id
                   ORDER BY cost DESC
                   LIMIT 5"""
            ).fetchall()

        return {
            "total_calls": total,
            "total_tokens": overall[3] or 0,
            "total_input_tokens": overall[1] or 0,
            "total_output_tokens": overall[2] or 0,
            "total_cost_usd": round(overall[4] or 0.0, 6),
            "avg_latency_ms": round(overall[5] or 0.0, 2),
            "avg_tokens_per_call": round((overall[3] or 0) / total, 2),
            "fallback_count": overall[6] or 0,
            "fallback_rate": round((overall[6] or 0) / total, 4),
            "error_count": overall[7] or 0,
            "by_provider": [
                {
                    "provider": row["provider_used"] or "unknown",
                    "count": row[1],
                    "cost_usd": round(row[2], 6),
                }
                for row in by_provider
            ],
            "by_model": [
                {
                    "model": row["model_used"] or "unknown",
                    "count": row[1],
                    "cost_usd": round(row[2], 6),
                }
                for row in by_model
            ],
            "top_threads_by_cost": [
                {
                    "thread_id": row["thread_id"],
                    "user_role": row["user_role"] or "",
                    "turns": row["turns"],
                    "cost_usd": round(row["cost"], 6),
                    "tokens": row["tokens"],
                }
                for row in top_threads
            ],
        }
