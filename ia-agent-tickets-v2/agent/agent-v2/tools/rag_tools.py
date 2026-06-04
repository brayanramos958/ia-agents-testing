"""
RAG tools — knowledge base search and AI feedback recording.

suggest_solution is the enforcement point for the resolution-first flow.
The creator prompt mandates calling it before create_ticket.

record_agent_feedback stores the user's rating of the AI's helpfulness.
This is separate from the ticket system's own satisfaction survey.
"""

import json
from typing import Any, Optional, Union

from langchain_core.tools import tool
from ports.rag_port import IRAGPort, SuggestionResult
from feedback.collector import FeedbackCollector
from core.security import wrap_external_data  # Capa 3: framing anti-inyección


def _safe_uid(llm_provided) -> int:
    from core.context import current_user_id as _uid_var
    ctx = _uid_var.get()
    return ctx if ctx else int(llm_provided)

_rag_port: IRAGPort = None

# Cache of last suggest_solution result per thread_id (used by record_agent_feedback to boost)
_suggestion_cache: dict[str, SuggestionResult] = {}
_SUGGESTION_CACHE_MAX = 500

# RAG hit/miss counters for metrics (MON-1)
_rag_total_calls = 0
_rag_hits = 0  # confidence >= threshold


def get_rag_stats() -> dict:
    """Return RAG hit rate stats (thread-safe enough for metrics display)."""
    total = _rag_total_calls
    hits = _rag_hits
    return {
        "rag_total_calls": total,
        "rag_hits": hits,
        "rag_hit_rate": round(hits / total, 3) if total > 0 else 0.0,
    }


def set_rag_port(port: IRAGPort) -> None:
    global _rag_port
    _rag_port = port


def _to_str(v: Any, fallback: str = "") -> str:
    if v is None:
        return fallback
    if isinstance(v, str):
        return v
    if isinstance(v, dict):
        # Model sometimes wraps the value: {"text": "...", ...} — take first value
        return next((str(x) for x in v.values() if x), json.dumps(v))
    return str(v)


@tool
async def suggest_solution(description: Any, category: Any = "") -> str:
    """
    Searches the knowledge base for resolved tickets similar to the user's problem.

    MANDATORY: Call this BEFORE create_ticket — every single time.

    Returns a plain-text result you must read and act on:
    - If it says "SOLUCIÓN ENCONTRADA": present the solution to the user and ask
      if it resolves their issue. If yes → record_agent_feedback, no ticket.
      If no → proceed to collect ticket data and call create_ticket.
    - If it says "SIN SOLUCIONES": tell the user you'll create a ticket and
      proceed to collect the required fields for create_ticket.

    Args:
        description: Description of the user's problem (plain text)
        category: Optional category name to narrow the search (plain text)
    """
    description = _to_str(description)
    category = _to_str(category)

    if not _rag_port:
        return wrap_external_data(
            "SIN SOLUCIONES: No se encontraron casos similares en la base de conocimiento. "
            "Procede a recopilar los datos del ticket y llama a create_ticket."
        )

    result: SuggestionResult = await _rag_port.search_similar(
        query=description,
        category=category or None,
        k=5,
    )

    # MON-1: track RAG hit/miss for metrics
    global _rag_total_calls, _rag_hits
    _rag_total_calls += 1
    if result.solutions_found and result.confidence >= 0.6:
        _rag_hits += 1

    # Cache for potential boost via record_agent_feedback (RAG-2)
    from core.context import current_thread_id
    tid = current_thread_id.get()
    if tid and tid != "?":
        if len(_suggestion_cache) >= _SUGGESTION_CACHE_MAX:
            oldest = next(iter(_suggestion_cache))
            del _suggestion_cache[oldest]
        _suggestion_cache[tid] = result

    if not result.solutions_found or result.confidence < 0.6:
        return wrap_external_data(
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

    return wrap_external_data(
        f"SOLUCIÓN ENCONTRADA (confianza: {result.confidence:.2f}): "
        f"Caso similar: {top.ticket_name} — {top.description}. "
        f"Solución aplicada: {top.motivo_resolucion}. "
        f"Causa raíz: {top.causa_raiz or 'No registrada'}.{others} "
        "Presenta esta solución al usuario en pasos simples y pregunta si resolvió su problema."
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
    Records the user's rating of the AI assistant's helpfulness.

    Call this after:
    - A solution was suggested and the user rated it (feedback_type='solution_suggested')
    - A ticket was created and the user rated the interaction (feedback_type='ticket_created')

    Args:
        user_id: Current user's ID
        rating: Integer from 1 (very unhelpful) to 5 (very helpful)
        feedback_type: Either 'ticket_created' or 'solution_suggested'
        ticket_id: Ticket ID if a ticket was created (None for solution_suggested)
        ticket_name: Ticket name like 'TCK-0001' (optional)
        comment: User's free-text feedback (optional)

    Returns:
        {"success": True, "feedback_id": int}
        {"success": False, "error": str}
    """
    # RAG-2: boost the document if the user rated a solution positively
    # This runs regardless of feedback recording success — they are independent.
    boosted = None
    if int(rating) >= 4 and feedback_type == "solution_suggested":
        from core.context import current_thread_id
        tid = current_thread_id.get()
        cached = _suggestion_cache.get(tid) if tid and tid != "?" else None
        if cached and cached.solutions_found:
            top = cached.solutions[0]
            _suggestion_cache.pop(tid, None)
            if _rag_port:
                boost_result = await _rag_port.boost_document(top.ticket_id)
                boosted = top.ticket_id
                print(f"[RAG-2] Boosted ticket {boosted} → count={boost_result.boost_count}")
        else:
            print(f"[RAG-2] Boost skipped: tid={tid} cached={bool(cached)} rating={rating} type={feedback_type}")

    # Feedback DB is optional — don't let it block the boost or the UX.
    feedback_error = None
    try:
        collector = FeedbackCollector()
        result = await collector.record(
            ticket_id=int(ticket_id) if ticket_id else None,
            user_id=_safe_uid(user_id),
            rating=int(rating),
            comment=comment,
            feedback_type=feedback_type,
            ticket_name=ticket_name,
        )
    except Exception as exc:
        feedback_error = str(exc)
        result = {"success": True, "feedback_recorded": False, "feedback_error": feedback_error}

    if boosted:
        result["boosted_ticket_id"] = boosted
        result["rag_boost_applied"] = True

    return result


def invalidate_suggestion_cache(thread_id: str) -> None:
    """Clears cached suggestions for a thread (e.g. on thread reset)."""
    _suggestion_cache.pop(thread_id, None)


def get_rag_tools() -> list:
    """RAG tools included in every role."""
    return [suggest_solution, record_agent_feedback]
