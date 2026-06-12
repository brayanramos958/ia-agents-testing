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

    Designed for the Odoo metrics dashboard (sara_metrics_action.js).
    All percentages are 0-100 (not 0-1) for easier display.

    Sections:
        summary    — KPI cards: top 5 numbers the dashboard shows
        feedback   — user satisfaction & deflection
        operation  — helpdesk KPIs (MTTR, MTTA, SLA)
        rag        — knowledge base quality
        llm        — AI usage & cost
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
    avg_satisfaction = feedback_metrics.get("average_rating", 0.0)

    feedback_section = {
        "total_feedback": feedback_metrics.get("total_feedback", 0),
        "avg_satisfaction": round(avg_satisfaction, 2),
        "tickets_created": created,
        "tickets_deflected": suggested,
        "deflection_rate_pct": round(deflection_rate * 100, 2),
        "by_type": by_type,
    }

    # ── Operation section ─────────────────────────────────────────
    operation_section = {
        "avg_time_to_assign_hours": 0.0,
        "avg_time_to_resolve_hours": 0.0,
        "tickets_by_category": [],
        "tickets_by_urgency": [],
        "tickets_by_status": {},
        "approval_rate": {"approved": 0, "rejected": 0, "pending": 0},
        "sla_breach_count": 0,
        "sla_at_risk_count": 0,
        "reopen_rate_pct": 0.0,
        "total_open_tickets": 0,
        "total_resolved_tickets": 0,
    }
    from tools.ticket_tools import _port as _runtime_port
    if _runtime_port is not None:
        try:
            op_metrics = await _runtime_port.get_operation_metrics()
            operation_section.update(op_metrics)
            # Normalise reopen_rate to percentage if backend returns 0-1
            if isinstance(operation_section.get("reopen_rate"), float):
                operation_section["reopen_rate_pct"] = round(operation_section["reopen_rate"] * 100, 2)
        except Exception as exc:
            logger.warning("Failed to collect operation metrics: %s", exc)
            operation_section["_error"] = str(exc)

    # ── RAG section ───────────────────────────────────────────────
    try:
        rag_section = collector.get_rag_summary()
        # Normalise hit_rate to percentage if backend returns 0-1
        if isinstance(rag_section.get("rag_hit_rate"), float):
            rag_section["rag_hit_rate_pct"] = round(rag_section["rag_hit_rate"] * 100, 2)
        else:
            rag_section["rag_hit_rate_pct"] = 0.0
    except Exception as exc:
        logger.warning("Failed to collect RAG metrics: %s", exc)
        rag_section = {
            "rag_hit_rate": None,
            "rag_hit_rate_pct": 0.0,
            "rag_total_calls": 0,
            "rag_hits": 0,
            "rag_avg_score": None,
            "rag_avg_latency_ms": None,
        }

    # ── LLM section ───────────────────────────────────────────────
    try:
        llm_section = collector.get_llm_summary()
        llm_section["provider"] = settings.llm_provider
        llm_section["model"] = (
            settings.ai_gateway_model
            if settings.llm_provider == "vercel"
            else settings.llm_model
        )
        # Normalise cost to 2 decimals
        if "total_cost_usd" in llm_section:
            llm_section["total_cost_usd"] = round(llm_section["total_cost_usd"], 2)
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

    # ── Summary section (top 5 KPIs for the dashboard) ──────────────────────────
    summary_section = {
        "satisfaction_pct": round(avg_satisfaction * 100 / 5, 2),  # 5-star scale
        "deflection_pct": round(deflection_rate * 100, 2),
        "rag_hit_rate_pct": rag_section.get("rag_hit_rate_pct", 0.0),
        "avg_resolution_hours": operation_section.get("avg_time_to_resolve_hours", 0.0),
        "sla_breach_count": operation_section.get("sla_breach_count", 0),
        "total_cost_usd": llm_section.get("total_cost_usd", 0.0),
        "total_llm_calls": llm_section.get("total_calls", 0),
        "total_open_tickets": operation_section.get("total_open_tickets", 0),
        "total_resolved_tickets": operation_section.get("total_resolved_tickets", 0),
    }

    return {
        "summary": summary_section,
        "feedback": feedback_section,
        "operation": operation_section,
        "rag": rag_section,
        "llm": llm_section,
    }
