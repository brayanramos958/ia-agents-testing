"""
GET /agent/metrics/* — SARA observability endpoints.

Fase 1.7 (trazabilidad): catalog + audit endpoints.
Fase 1.5 (adoption): /agent/metrics/adoption + /agent/metrics/users.
Fase 1.6 (creation): /agent/metrics/creation + /agent/metrics/creation/abandoned.

All endpoints are documented in /agent/metrics/catalog.
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Query

from config.settings import settings
from metrics.audit import log_request
from metrics.creation_tracker import get_abandoned_creations
from metrics.registry import MetricsRegistry
from metrics.usage_tracker import get_top_users

logger = logging.getLogger(__name__)
router = APIRouter()


# ── /agent/metrics/catalog ────────────────────────────────────────────────

@router.get("/agent/metrics/catalog")
async def get_metrics_catalog(category: Optional[str] = Query(None, description="Filter by category")):
    """
    Get the metadata catalog of ALL metrics exposed by SARA.

    Use ?category=summary to filter by category.

    Each metric includes:
      - description: what it measures
      - unit: percentage, count, ms, usd, etc.
      - data_source: which PostgreSQL table or backend
      - calculation_method: how it's computed
      - sql_query: the exact query (for transparency)
      - slo_target: SLO objective
      - slo_alert_threshold: when to alert
    """
    log_request(endpoint="/agent/metrics/catalog", query_params={"category": category})
    registry = MetricsRegistry()
    if category:
        metrics = registry.get_by_category(category)
    else:
        metrics = registry.get_all()

    return {
        "total": len(metrics),
        "categories": registry.get_categories(),
        "metrics": metrics,
    }


@router.get("/agent/metrics/catalog/{metric_name}")
async def get_metric_metadata(metric_name: str):
    """
    Get metadata for a single metric.
    """
    log_request(endpoint=f"/agent/metrics/catalog/{metric_name}", query_params={})
    registry = MetricsRegistry()
    metric = registry.get_by_name(metric_name)
    if not metric:
        raise HTTPException(status_code=404, detail=f"Metric '{metric_name}' not found in catalog")
    return metric


# ── /agent/metrics/audit ──────────────────────────────────────────────────

@router.get("/agent/metrics/audit")
async def get_metrics_audit(
    period: str = Query("7d", description="Time period: 1d, 7d, 30d, 1y"),
    endpoint: Optional[str] = Query(None, description="Filter by endpoint"),
    user_id: Optional[int] = Query(None, description="Filter by user_id"),
    limit: int = Query(100, description="Max records to return"),
):
    """
    Get the audit log of who consulted which metrics endpoint and when.

    Used for compliance and debugging ("who saw this number?").
    """
    log_request(endpoint="/agent/metrics/audit", query_params={
        "period": period, "endpoint": endpoint, "user_id": user_id, "limit": limit
    })
    import psycopg

    # Parse period
    period_days = {"1d": 1, "7d": 7, "30d": 30, "1y": 365}.get(period, 7)

    query = """
        SELECT id, timestamp, endpoint, user_id, user_role, query_params,
               response_size_bytes, response_time_ms
        FROM metrics_audit_log
        WHERE timestamp >= NOW() - make_interval(days => %s)
    """
    params: list = [period_days]

    if endpoint:
        query += " AND endpoint = %s"
        params.append(endpoint)
    if user_id is not None:
        query += " AND user_id = %s"
        params.append(user_id)

    query += " ORDER BY timestamp DESC LIMIT %s"
    params.append(limit)

    if not settings.postgres_dsn:
        return {"total": 0, "entries": [], "note": "PostgreSQL not configured"}

    try:
        with psycopg.connect(settings.postgres_dsn) as conn:
            with conn.cursor() as cur:
                cur.execute(query, params)
                rows = cur.fetchall()

        entries = [
            {
                "id": r[0],
                "timestamp": r[1].isoformat() if r[1] else None,
                "endpoint": r[2],
                "user_id": r[3],
                "user_role": r[4],
                "query_params": r[5],
                "response_size_bytes": r[6],
                "response_time_ms": r[7],
            }
            for r in rows
        ]
        return {"total": len(entries), "entries": entries}
    except Exception as exc:
        logger.exception("Failed to fetch audit log")
        return {"total": 0, "entries": [], "error": str(exc)}


# ── /agent/metrics/users (Fase 1.5) ───────────────────────────────────────

@router.get("/agent/metrics/users")
async def get_top_users_endpoint(
    limit: int = Query(10, description="Max users to return"),
    period: str = Query("7d", description="Time period: 1d, 7d, 30d"),
):
    """
    Return the top N most active users in the given period.

    Each entry includes user_id, user_role, event_count, sessions, last_seen.
    Useful for identifying power users and adoption patterns.
    """
    log_request(endpoint="/agent/metrics/users", query_params={
        "limit": limit, "period": period,
    })
    try:
        users = get_top_users(limit=limit)
        return {"total": len(users), "users": users}
    except Exception as exc:
        logger.exception("Failed to fetch top users")
        return {"total": 0, "users": [], "error": str(exc)}


# ── /agent/metrics/creation/abandoned (Fase 1.6) ──────────────────────────

@router.get("/agent/metrics/creation/abandoned")
async def get_abandoned_creations_endpoint(
    limit: int = Query(20, description="Max abandoned flows to return"),
):
    """
    Return the most recent abandoned ticket creation flows.

    An abandoned flow is one where the LLM started the creation process
    (calling create_ticket) but never completed it (no success response).
    Useful for UX research — "where do users give up?".
    """
    log_request(endpoint="/agent/metrics/creation/abandoned", query_params={"limit": limit})
    try:
        abandoned = get_abandoned_creations(limit=limit)
        return {"total": len(abandoned), "abandoned": abandoned}
    except Exception as exc:
        logger.exception("Failed to fetch abandoned creations")
        return {"total": 0, "abandoned": [], "error": str(exc)}
