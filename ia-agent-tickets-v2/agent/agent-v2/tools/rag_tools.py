"""
RAG tools — knowledge base search and AI feedback recording.

suggest_solution is the enforcement point for the resolution-first flow.
The creator prompt mandates calling it before create_ticket.

record_agent_feedback stores the user's rating of the AI's helpfulness.
This is separate from the ticket system's own satisfaction survey.
"""

from typing import Optional, Union

from langchain_core.tools import tool
from ports.rag_port import IRAGPort, SuggestionResult
from feedback.collector import FeedbackCollector

_rag_port: IRAGPort = None


def set_rag_port(port: IRAGPort) -> None:
    global _rag_port
    _rag_port = port


@tool
def suggest_solution(description: str, category: str = "") -> str:
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
        description: Natural language description of the user's problem
        category: Optional category name to narrow the search
    """
    if not _rag_port:
        return (
            "SIN SOLUCIONES: No se encontraron casos similares en la base de conocimiento. "
            "Procede a recopilar los datos del ticket y llama a create_ticket."
        )

    result: SuggestionResult = _rag_port.search_similar(
        query=description,
        category=category or None,
        k=5,
    )

    if not result.solutions_found or result.confidence < 0.6:
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

    return (
        f"SOLUCIÓN ENCONTRADA (confianza: {result.confidence:.2f}): "
        f"Caso similar: {top.ticket_name} — {top.description}. "
        f"Solución aplicada: {top.motivo_resolucion}. "
        f"Causa raíz: {top.causa_raiz or 'No registrada'}.{others} "
        "Presenta esta solución al usuario en pasos simples y pregunta si resolvió su problema."
    )


@tool
def record_agent_feedback(
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
    collector = FeedbackCollector()
    return collector.record(
        ticket_id=int(ticket_id) if ticket_id else None,
        user_id=int(user_id),
        rating=int(rating),
        comment=comment,
        feedback_type=feedback_type,
        ticket_name=ticket_name,
    )


def get_rag_tools() -> list:
    """RAG tools included in every role."""
    return [suggest_solution, record_agent_feedback]
