"""
GET /agent/metrics — SARA usage dashboard (MON-1).

Returns key metrics in three sections:
    feedback   — agent evaluation (rating, deflection, satisfaction)
    operation  — helpdesk KPIs (MTTN, MTTR, distribution by category/urgency)
    rag        — RAG usage (hit rate, avg score) — Phase 2
    llm        — LLM usage (tokens, latency, cost) — Phase 3
"""

import logging
from fastapi import APIRouter, HTTPException

from config.settings import settings
from feedback.collector import FeedbackCollector

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/agent/metrics")
async def get_metrics():
    """
    Returns aggregate metrics about SARA's performance.

    Sections:
        feedback   — feedback.db based metrics
        operation  — Odoo/Express backend operation KPIs (Phase 1)
        rag        — RAG usage tracking (Phase 2 — placeholder)
        llm        — LLM usage tracking (Phase 3 — placeholder)
    """
    # ── Feedback section ────────────────────────────────────────────────────
    try:
        collector = FeedbackCollector()
        feedback_metrics = collector.get_summary()
    except Exception as exc:
        logger.exception("Failed to collect feedback metrics")
        feedback_metrics = {"total_feedback": 0, "average_rating": 0.0, "by_type": []}

    by_type = feedback_metrics.get("by_type", [])
    type_map = {t["feedback_type"]: t for t in by_type}

    suggested = type_map.get("solution_suggested", {}).get("count", 0)
    created = type_map.get("ticket_created", {}).get("count", 0)
    total = suggested + created
    deflection_rate = (suggested / total) if total > 0 else 0.0

    feedback_section = {
        "total_feedback": feedback_metrics.get("total_feedback", 0),
        "avg_satisfaction": feedback_metrics.get("average_rating", 0.0),
        "tickets_created": created,
        "tickets_deflected": suggested,
        "deflection_rate": round(deflection_rate, 4),
        "by_type": by_type,
    }

    # ── Operation section (Phase 1) ─────────────────────────────────────────
    operation_section = {
        "avg_time_to_assign_hours": 0.0,
        "avg_time_to_resolve_hours": 0.0,
        "tickets_by_category": [],
        "tickets_by_urgency": [],
        "approval_rate": {"approved": 0, "rejected": 0, "pending": 0},
        "reopen_rate": 0.0,
    }
    # Import lazily so we get the runtime-initialized _port (not the module-level None).
    from tools.ticket_tools import _port as _runtime_port
    if _runtime_port is not None:
        try:
            import asyncio
            op_metrics = await asyncio.to_thread(_runtime_port.get_operation_metrics)
            operation_section.update(op_metrics)
        except Exception as exc:
            logger.warning("Failed to collect operation metrics: %s", exc)
            operation_section["_error"] = str(exc)

    # ── RAG section (Phase 2) ───────────────────────────────────────────────
    try:
        rag_section = collector.get_rag_summary()
    except Exception as exc:
        logger.warning("Failed to collect RAG metrics: %s", exc)
        rag_section = {
            "rag_hit_rate": None,
            "rag_total_calls": 0,
            "rag_hits": 0,
            "rag_avg_score": None,
            "rag_avg_latency_ms": None,
        }

    # ── LLM section (Phase 3) ───────────────────────────────────────────────
    try:
        llm_section = collector.get_llm_summary()
        # Always include active provider/model for context
        llm_section["provider"] = settings.llm_provider
        llm_section["model"] = (
            settings.ai_gateway_model
            if settings.llm_provider == "vercel"
            else settings.llm_model
        )
    except Exception as exc:
        logger.warning("Failed to collect LLM metrics: %s", exc)
        llm_section = {
            "total_calls": 0,
            "total_tokens": 0,
            "total_cost_usd": 0.0,
            "avg_latency_ms": 0.0,
            "provider": settings.llm_provider,
            "model": (
                settings.ai_gateway_model
                if settings.llm_provider == "vercel"
                else settings.llm_model
            ),
        }

    return {
        "feedback": feedback_section,
        "operation": operation_section,
        "rag": rag_section,
        "llm": llm_section,
    }
