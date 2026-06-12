"""
GET /agent/metrics — SARA usage dashboard (MON-1).

Returns key metrics in five sections:
    feedback   — agent evaluation (rating, deflection, satisfaction)
    operation  — helpdesk KPIs (MTTN, MTTR, distribution by category/urgency)
    rag        — RAG usage (hit rate, avg score) — Phase 2
    llm        — LLM usage (tokens, latency, cost) — Phase 3
    summary    — KPI cards: top 5 numbers the dashboard shows
    adoption   — usage & unique users (Fase 1.5)
    creation   — ticket creation flow (Fase 1.6)

Fase 1.7: each section now includes _metadata with description, unit,
and SLO targets (queried from metrics_registry).
"""

import logging
from fastapi import APIRouter, HTTPException

from config.settings import settings
from feedback.collector import FeedbackCollector
from metrics.audit import log_request
from metrics.creation_tracker import get_creation_summary
from metrics.registry import MetricsRegistry
from metrics.usage_tracker import get_adoption_summary

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
        adoption   — usage & unique users (Fase 1.5)
        creation   — ticket creation flow (Fase 1.6)
    """
    # Audit log (Fase 1.7)
    log_request(endpoint="/agent/metrics", query_params={})
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

    # ── Adoption section (Fase 1.5) ──────────────────────────────────────────
    adoption_section = await _get_adoption_metrics()

    # ── Creation section (Fase 1.6) ──────────────────────────────────────────
    creation_section = await _get_creation_metrics()

    # ── Metadata (Fase 1.7) ──────────────────────────────────────────────────
    metadata = _build_metadata(summary_section, feedback_section, operation_section,
                                rag_section, llm_section, adoption_section, creation_section)

    return {
        "summary": summary_section,
        "feedback": feedback_section,
        "operation": operation_section,
        "rag": rag_section,
        "llm": llm_section,
        "adoption": adoption_section,
        "creation": creation_section,
        "metadata": metadata,
    }


async def _get_adoption_metrics() -> dict:
    """Compute adoption metrics (Fase 1.5)."""
    try:
        return get_adoption_summary()
    except Exception as exc:
        logger.warning("Failed to collect adoption metrics: %s", exc)
        return {
            "usage_daily_count": 0,
            "usage_weekly_count": 0,
            "unique_users_daily": 0,
            "unique_users_weekly": 0,
            "unique_users_monthly": 0,
            "retention_rate_7d_pct": 0.0,
            "activation_rate_pct": 0.0,
            "sessions_per_user_avg": 0.0,
            "power_users_count": 0,
            "dormant_users_count": 0,
        }


async def _get_creation_metrics() -> dict:
    """Compute creation metrics (Fase 1.6)."""
    try:
        return get_creation_summary()
    except Exception as exc:
        logger.warning("Failed to collect creation metrics: %s", exc)
        return {
            "tickets_created_daily": 0,
            "tickets_created_weekly": 0,
            "avg_creation_time_seconds": 0.0,
            "median_creation_time_seconds": 0.0,
            "p95_creation_time_seconds": 0.0,
            "tickets_abandoned_count": 0,
            "tickets_abandoned_rate_pct": 0.0,
            "tickets_created_in_first_message_pct": 0.0,
            "avg_messages_per_ticket": 0.0,
            "duplicate_detection_rate_pct": 0.0,
            "satisfaction_avg": 0.0,
            "satisfaction_pct": 0.0,
            "total_ratings_count": 0,
        }


def _build_metadata(*sections: dict) -> dict:
    """
    Build a metadata map for each section: which key metrics have
    descriptions, units, and SLO targets.

    Fase 1.7: trazabilidad de cada número.
    """
    try:
        registry = MetricsRegistry()
        catalog = {m["metric_name"]: m for m in registry.get_all()}
    except Exception:
        catalog = {}

    def _meta_for(key: str) -> dict:
        m = catalog.get(key)
        if not m:
            return {}
        return {
            "description": m["description"],
            "unit": m["unit"],
            "slo_target": m["slo_target"],
            "slo_alert_threshold": m["slo_alert_threshold"],
        }

    return {
        "summary": {
            "satisfaction_pct": _meta_for("satisfaction_pct"),
            "deflection_pct": _meta_for("deflection_pct"),
            "rag_hit_rate_pct": _meta_for("rag_hit_rate_pct"),
            "avg_resolution_hours": _meta_for("avg_resolution_hours"),
            "sla_breach_count": _meta_for("sla_breach_count"),
            "total_cost_usd": _meta_for("total_cost_usd"),
            "total_llm_calls": _meta_for("total_llm_calls"),
            "total_open_tickets": _meta_for("total_open_tickets"),
            "total_resolved_tickets": _meta_for("total_resolved_tickets"),
        },
        "feedback": {
            "total_feedback": _meta_for("total_feedback"),
            "avg_satisfaction": _meta_for("avg_satisfaction"),
            "tickets_created": _meta_for("tickets_created"),
            "tickets_deflected": _meta_for("tickets_deflected"),
            "deflection_rate_pct": _meta_for("deflection_rate_pct"),
        },
        "rag": {
            "rag_total_calls": _meta_for("rag_total_calls"),
            "rag_hits": _meta_for("rag_hits"),
            "rag_hit_rate": _meta_for("rag_hit_rate"),
            "rag_avg_score": _meta_for("rag_avg_score"),
            "rag_avg_latency_ms": _meta_for("rag_avg_latency_ms"),
        },
        "llm": {
            "total_calls": _meta_for("llm_total_calls"),
            "total_tokens": _meta_for("llm_total_tokens"),
            "avg_latency_ms": _meta_for("llm_avg_latency_ms"),
            "fallback_count": _meta_for("llm_fallback_count"),
            "fallback_rate": _meta_for("llm_fallback_rate"),
            "error_count": _meta_for("llm_error_count"),
            "error_rate": _meta_for("llm_error_rate"),
        },
        "adoption": {
            "description": "Adoption & usage metrics (Fase 1.5) — how much and who uses SARA",
            "unit": "mixed",
        },
        "creation": {
            "description": "Ticket creation flow metrics (Fase 1.6) — time and satisfaction",
            "unit": "mixed",
        },
    }
