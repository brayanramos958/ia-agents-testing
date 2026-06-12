"""
RAG tools — knowledge base search and AI feedback recording.

``suggest_solution`` is the enforcement point for the resolution-first flow.
The creator prompt mandates calling it before ``create_ticket``.

``record_agent_feedback`` stores the user's rating of the AI's helpfulness.
This is separate from the ticket system's own satisfaction survey.

ARCHITECTURE NOTE (Fase 8 — async migration):
    - ``suggest_solution`` is ``async def`` and awaits the async RAG port.
    - ``record_agent_feedback`` is ``async def`` and uses ``asyncio.to_thread``
      for the sync ``FeedbackCollector`` (SQLite). The collector itself is
      small and fast; rewriting it async is deferred.
    - RAG usage tracking in the collector also goes through ``to_thread`` for
      the same reason.
"""

import asyncio
import json
import logging
import time
from typing import Any, Optional, Union

from langchain_core.tools import tool

from core.security import frame_external_data
from feedback.collector import FeedbackCollector
from ports.rag_port import IRAGPort, SuggestionResult

logger = logging.getLogger(__name__)

# Confidence threshold for considering a RAG match "useful" (Phase 2 tracking)
_RAG_HIT_THRESHOLD = 0.6


def _safe_uid(llm_provided) -> int:
    """
    Return the authenticated user_id from the request context.

    Falls back to the LLM-provided value only in test environments where
    the context var was never set.

    Args:
        llm_provided: User ID from the LLM tool arguments.

    Returns:
        int: Authenticated user ID.
    """
    from core.context import current_user_id as _uid_var
    ctx = _uid_var.get()
    return ctx if ctx else int(llm_provided)


def _safe_role() -> str:
    """Return the current user role from context (set by middleware)."""
    try:
        from core.context import current_user_role as _role_var
        return _role_var.get() or ""
    except Exception:
        return ""


_rag_port: IRAGPort | None = None


def set_rag_port(port: IRAGPort) -> None:
    """Inject the RAG port at application startup."""
    global _rag_port
    _rag_port = port


def _to_str(v: Any, fallback: str = "") -> str:
    """
    Coerce an arbitrary LLM-supplied value to a string.

    The model sometimes wraps values: ``{"text": "...", ...}`` — take the
    first non-empty value.

    Args:
        v: Value to coerce.
        fallback: Returned if ``v`` is ``None``.

    Returns:
        str: String representation.
    """
    if v is None:
        return fallback
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        return next((str(x) for x in v.values() if x), json.dumps(v))
    return str(v)


@tool
async def suggest_solution(description: Any, category: Any = "") -> str:
    """
    Search the knowledge base for resolved tickets similar to the user's problem.

    MANDATORY: Call this BEFORE ``create_ticket`` — every single time.

    Returns a plain-text result you must read and act on:
    - If it says "SOLUCIÓN ENCONTRADA": present the solution to the user and ask
      if it resolves their issue. If yes → ``record_agent_feedback``, no ticket.
      If no → proceed to collect ticket data and call ``create_ticket``.
    - If it says "SIN SOLUCIONES": tell the user you'll create a ticket and
      proceed to collect the required fields for ``create_ticket``.

    Args:
        description: Description of the user's problem (plain text).
        category: Optional category name to narrow the search (plain text).
    """
    description = _to_str(description)
    category = _to_str(category)

    # ── Latency tracking (Phase 2) ──────────────────────────────────────────
    started = time.perf_counter()

    if not _rag_port:
        return (
            "SIN SOLUCIONES: No se encontraron casos similares en la base de conocimiento. "
            "Procede a recopilar los datos del ticket y llama a create_ticket."
        )

    # The RAG port may be sync (PGVector) or async. If sync, run in thread pool
    # to avoid blocking the event loop. Fast enough (< 100ms) that this is safe.
    if asyncio.iscoroutinefunction(_rag_port.search_similar):
        result: SuggestionResult = await _rag_port.search_similar(
            query=description,
            category=category or None,
            k=5,
        )
    else:
        result = await asyncio.to_thread(
            _rag_port.search_similar,
            query=description,
            category=category or None,
            k=5,
        )

    # ── Record RAG usage in PostgreSQL (Phase 2) ───────────────────────────
    elapsed_ms = (time.perf_counter() - started) * 1000
    try:
        await asyncio.to_thread(
            _record_rag_usage_sync,
            description=description,
            solutions_found=bool(result.solutions_found and result.confidence >= _RAG_HIT_THRESHOLD),
            top_score=float(result.solutions[0].score) if result.solutions else 0.0,
            latency_ms=elapsed_ms,
        )
    except Exception:
        # Tracking is best-effort — never fail the tool call because of metrics
        logger.debug("RAG usage tracking failed", exc_info=True)

    if not result.solutions_found or result.confidence < _RAG_HIT_THRESHOLD:
        return (
            "SIN SOLUCIONES: No se encontraron casos similares en la base de conocimiento "
            f"(confianza: {result.confidence:.2f}). "
            "Procede a recopilar los datos del ticket y llama a create_ticket."
        )

    top = result.solutions[0]
    others = ""
    if len(result.solutions) > 1:
        others = " También hay casos similares: " + ", ".join(
            f"{s.ticket_name} ({s.category})" for s in result.solutions[1:3]
        ) + "."

    return frame_external_data(
        f"SOLUCIÓN ENCONTRADA (confianza: {result.confidence:.2f}). "
        f"Caso similar: {top.ticket_name} — {top.description}. "
        f"Solución aplicada: {top.motivo_resolucion}. "
        f"Causa raíz: {top.causa_raiz or 'No registrada'}.{others}",
        source="rag (base de conocimiento)",
    ) + "\nPresenta esta solución al usuario en pasos simples y pregunta si resolvió su problema."


def _record_rag_usage_sync(
    *,
    description: str,
    solutions_found: bool,
    top_score: float,
    latency_ms: float,
) -> None:
    """Sync helper that records RAG usage via the SQLite FeedbackCollector."""
    collector = FeedbackCollector()
    collector.record_rag_usage(
        user_id=_safe_uid(0) or None,  # 0 = trust ContextVar
        user_role=_safe_role(),
        query=description,
        solutions_found=solutions_found,
        top_score=top_score,
        threshold_used=_RAG_HIT_THRESHOLD,
        latency_ms=latency_ms,
    )


@tool
async def record_agent_feedback(
    user_id: Union[int, str],
    rating: Union[int, str],
    feedback_type: str,
    ticket_id: Optional[Union[int, str]] = None,
    ticket_name: str = "",
    comment: str = "",
) -> dict:
    """
    Record the user's rating of the AI assistant's helpfulness.

    Call this after:
    - A solution was suggested and the user rated it (``feedback_type='solution_suggested'``)
    - A ticket was created and the user rated the interaction (``feedback_type='ticket_created'``)

    Args:
        user_id: Current user's ID.
        rating: Integer from 1 (very unhelpful) to 5 (very helpful).
        feedback_type: Either ``'ticket_created'`` or ``'solution_suggested'``.
        ticket_id: Ticket ID if a ticket was created (None for ``solution_suggested``).
        ticket_name: Ticket name like ``'TCK-0001'`` (optional).
        comment: User's free-text feedback (optional).

    Returns:
        dict: ``{"success": True, "feedback_id": int}`` or
              ``{"success": False, "error": str}``.
    """
    # FeedbackCollector uses sync SQLite — run in thread pool
    return await asyncio.to_thread(
        _record_feedback_sync,
        user_id=_safe_uid(user_id),
        rating=int(rating),
        feedback_type=feedback_type,
        ticket_id=int(ticket_id) if ticket_id else None,
        ticket_name=ticket_name,
        comment=comment,
    )


def _record_feedback_sync(
    *,
    user_id: int,
    rating: int,
    feedback_type: str,
    ticket_id: int | None,
    ticket_name: str,
    comment: str,
) -> dict:
    """Sync helper that records feedback via the SQLite FeedbackCollector."""
    collector = FeedbackCollector()
    return collector.record(
        ticket_id=ticket_id,
        user_id=user_id,
        rating=rating,
        comment=comment,
        feedback_type=feedback_type,
        ticket_name=ticket_name,
    )


def get_rag_tools() -> list:
    """Return the RAG tools included in every role."""
    return [suggest_solution, record_agent_feedback]
