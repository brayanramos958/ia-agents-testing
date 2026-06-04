"""
GET /agent/alerts — SLA alert dashboard for supervisors.

Returns active (unacknowledged) SLA alerts: tickets that are about to expire
or have already expired. Zero LLM tokens consumed — pure PostgreSQL query.
"""

import logging
from fastapi import APIRouter, HTTPException, Query

logger = logging.getLogger(__name__)
router = APIRouter()

# Reference to the scheduler — set by main.py during lifespan startup
_scheduler = None


def set_scheduler(scheduler) -> None:
    """Injects the SARAScheduler instance so the route can query alerts."""
    global _scheduler
    _scheduler = scheduler


@router.get("/agent/alerts")
async def get_alerts():
    """
    Returns active SLA alerts not yet acknowledged by a supervisor.

    Response:
        {
            "total": 3,
            "alerts": [
                {
                    "id": 1,
                    "ticket_id": 2839,
                    "ticket_name": "INC-002839",
                    "alert_type": "expires_soon",   # or "expired"
                    "deadline": "2026-06-03T16:00:00+00:00",
                    "assigned_name": "María García",
                    "created_at": "2026-06-03T15:55:00+00:00"
                },
                ...
            ]
        }

    Only supervisors should access this endpoint (role gating is done
    by the Odoo proxy or middleware — this endpoint itself is role-agnostic).
    """
    if _scheduler is None:
        raise HTTPException(
            status_code=503,
            detail="Alerts system not available — scheduler not initialized.",
        )

    try:
        import psycopg
        from config.settings import settings

        if not settings.postgres_dsn:
            return {"total": 0, "alerts": [], "note": "PostgreSQL not configured"}

        async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
            cur = await conn.execute("""
                SELECT id, ticket_id, ticket_name, alert_type, deadline,
                       assigned_name, created_at
                FROM sla_alerts
                WHERE acknowledged_by IS NULL
                ORDER BY
                    CASE alert_type
                        WHEN 'expired' THEN 0
                        WHEN 'expires_soon' THEN 1
                    END,
                    deadline ASC
            """)
            rows = await cur.fetchall()

        alerts = [
            {
                "id": row[0],
                "ticket_id": row[1],
                "ticket_name": row[2],
                "alert_type": row[3],
                "deadline": row[4].isoformat() if row[4] else None,
                "assigned_name": row[5],
                "created_at": row[6].isoformat() if row[6] else None,
            }
            for row in rows
        ]

        return {"total": len(alerts), "alerts": alerts}

    except Exception as exc:
        logger.exception("Failed to fetch SLA alerts")
        raise HTTPException(
            status_code=500, detail=f"Error fetching alerts: {exc}"
        )
