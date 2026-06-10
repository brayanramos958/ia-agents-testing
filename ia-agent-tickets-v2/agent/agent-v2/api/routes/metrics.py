"""
GET /agent/metrics — SARA usage dashboard (MON-1).

Returns key metrics: deflection rate, average satisfaction,
RAG hit rate, tickets deflected, and more.
"""

import logging
from fastapi import APIRouter, HTTPException

from feedback.collector import FeedbackCollector

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/agent/metrics")
async def get_metrics():
    """
    Returns aggregate metrics about SARA's performance.

    Fields:
    - deflection_rate: ratio of problems solved via RAG (no ticket needed)
    - avg_satisfaction: average user rating (1-5 scale)
    - tickets_deflected: count of success stories (solution found, no ticket)
    - tickets_created: count of tickets created through SARA
    - rag_hit_rate: percentage of suggest_solution calls that found a match
    - rag_total_calls: total suggest_solution calls
    - total_feedback: total feedback entries recorded
    - by_type: breakdown by feedback_type
    """
    try:
        collector = FeedbackCollector()
        feedback_metrics = collector.get_summary()
    except Exception as exc:
        logger.exception("Failed to collect metrics")
        raise HTTPException(status_code=500, detail=str(exc))

    # Calcular metrics derivados de los datos crudos
    by_type = feedback_metrics.get("by_type", [])
    type_map = {t["feedback_type"]: t for t in by_type}

    suggested = type_map.get("solution_suggested", {}).get("count", 0)
    created = type_map.get("ticket_created", {}).get("count", 0)
    total = suggested + created
    deflection_rate = (suggested / total) if total > 0 else 0.0

    return {
        "total_feedback": feedback_metrics.get("total_feedback", 0),
        "avg_satisfaction": feedback_metrics.get("average_rating", 0.0),
        "tickets_created": created,
        "tickets_deflected": suggested,
        "deflection_rate": round(deflection_rate, 4),
        # RAG stats — placeholder hasta que se implemente tracking detallado
        "rag_hit_rate": None,
        "rag_total_calls": None,
        "by_type": by_type,
    }
