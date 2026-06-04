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
