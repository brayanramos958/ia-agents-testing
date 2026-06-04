"""
GET /agent/metrics — SARA usage dashboard (MON-1).

Returns key metrics: deflection rate, average satisfaction,
RAG hit rate, tickets deflected, and more.
"""

import logging
from fastapi import APIRouter, HTTPException

from feedback.collector import FeedbackCollector
from tools.rag_tools import get_rag_stats

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
        feedback_metrics = await collector.get_metrics()
        rag_stats = get_rag_stats()
    except Exception as exc:
        logger.exception("Failed to collect metrics")
        raise HTTPException(status_code=500, detail=str(exc))

    return {
        **feedback_metrics,
        **rag_stats,
    }
