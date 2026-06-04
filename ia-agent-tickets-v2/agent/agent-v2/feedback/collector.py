"""
AI assistant feedback storage.

Persists ratings and comments about the agent's helpfulness to PostgreSQL.
This uses the same database as checkpoints and vector store for consistency.

This is separate from the enterprise ticket system's satisfaction survey.
Use get_summary() to build reports for improving the agent over time.
"""

from __future__ import annotations

import psycopg

from config.settings import settings


class FeedbackCollector:
    """Async feedback storage backed by PostgreSQL."""

    def __init__(self, dsn: str = None):
        self._dsn = dsn or settings.postgres_dsn

    async def _ensure_table(self) -> None:
        async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS agent_feedback (
                    id            SERIAL PRIMARY KEY,
                    ticket_id     INTEGER,
                    ticket_name   TEXT,
                    user_id       INTEGER NOT NULL,
                    rating        INTEGER CHECK(rating BETWEEN 1 AND 5),
                    comment       TEXT DEFAULT '',
                    feedback_type TEXT NOT NULL
                        CHECK(feedback_type IN ('ticket_created', 'solution_suggested')),
                    created_at    TIMESTAMPTZ DEFAULT NOW()
                )
                """
            )
            # Migration: make rating nullable (auto-tracked tickets have no rating)
            await conn.execute(
                "ALTER TABLE agent_feedback ALTER COLUMN rating DROP NOT NULL"
            )
            await conn.commit()

    async def record(
        self,
        ticket_id: int | None,
        user_id: int,
        rating: int | None,
        comment: str,
        feedback_type: str,
        ticket_name: str = None,
    ) -> dict:
        """
        Store one feedback entry.

        rating can be None for auto-tracked records (e.g. ticket creation).
        Manual user feedback MUST provide a rating between 1 and 5.

        Returns:
            {"success": True, "feedback_id": int}
            {"success": False, "error": str}
        """
        if rating is not None and not 1 <= rating <= 5:
            return {"success": False, "error": "Rating must be between 1 and 5"}

        valid_types = ("ticket_created", "solution_suggested")
        if feedback_type not in valid_types:
            return {"success": False, "error": f"feedback_type must be one of {valid_types}"}

        await self._ensure_table()

        async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
            row = await conn.execute(
                """
                INSERT INTO agent_feedback
                    (ticket_id, ticket_name, user_id, rating, comment, feedback_type)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (ticket_id, ticket_name, user_id, rating, comment, feedback_type),
            )
            feedback_id = (await row.fetchone())[0]
            await conn.commit()
            return {"success": True, "feedback_id": feedback_id}

    async def get_summary(self) -> dict:
        """Returns aggregate stats for reporting and agent improvement."""
        await self._ensure_table()

        async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
            cur = await conn.execute("SELECT COUNT(*), AVG(rating) FROM agent_feedback")
            total, avg = await cur.fetchone()

            cur = await conn.execute(
                """
                SELECT feedback_type, COUNT(*), AVG(rating)
                FROM agent_feedback
                GROUP BY feedback_type
                """
            )
            by_type = await cur.fetchall()

        return {
            "total_feedback": total or 0,
            "average_rating": round(float(avg) if avg else 0.0, 2),
            "by_type": [
                {"feedback_type": row[0], "count": row[1], "avg_rating": round(float(row[2]), 2)}
                for row in by_type
            ],
        }

    async def get_recent(self, limit: int = 20) -> list:
        """Returns the most recent feedback entries."""
        await self._ensure_table()

        async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
            cur = await conn.execute(
                """
                SELECT id, ticket_id, ticket_name, user_id, rating,
                       comment, feedback_type, created_at
                FROM agent_feedback
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (limit,),
            )
            rows = await cur.fetchall()
            cols = [desc[0] for desc in cur.description]

        return [dict(zip(cols, row)) for row in rows]

    async def get_metrics(self) -> dict:
        """Return key metrics for the SARA dashboard (MON-1)."""
        await self._ensure_table()

        async with await psycopg.AsyncConnection.connect(self._dsn) as conn:
            # Overall stats: AVG excludes auto-tracked rows (rating=NULL)
            cur = await conn.execute(
                "SELECT COUNT(*), COALESCE(AVG(rating) FILTER (WHERE rating IS NOT NULL), 0) FROM agent_feedback"
            )
            total, avg_rating = await cur.fetchone()

            # By type: COUNT all rows, AVG only rated rows
            cur = await conn.execute(
                """
                SELECT feedback_type, COUNT(*),
                       COALESCE(AVG(rating) FILTER (WHERE rating IS NOT NULL), 0)
                FROM agent_feedback
                GROUP BY feedback_type
                """
            )
            by_type_rows = await cur.fetchall()

            # Tickets deflected: solution_suggested feedbacks with rating >= 4 (NULL excluded)
            cur = await conn.execute(
                """
                SELECT COUNT(*)
                FROM agent_feedback
                WHERE feedback_type = 'solution_suggested'
                  AND rating IS NOT NULL
                  AND rating >= 4
                """
            )
            (tickets_deflected,) = await cur.fetchone()

        by_type = {}
        for row in by_type_rows:
            by_type[row[0]] = {"count": row[1], "avg_rating": round(float(row[2]), 2)}

        tickets_created = by_type.get("ticket_created", {}).get("count", 0)
        total_deflected_or_created = max(tickets_deflected + tickets_created, 1)

        return {
            "total_feedback": total or 0,
            "avg_satisfaction": round(float(avg_rating), 2),
            "deflection_rate": round(tickets_deflected / total_deflected_or_created, 3),
            "tickets_deflected": tickets_deflected,
            "tickets_created": tickets_created,
            "by_type": by_type,
        }
