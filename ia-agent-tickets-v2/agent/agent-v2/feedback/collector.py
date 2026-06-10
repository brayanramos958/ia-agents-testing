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
