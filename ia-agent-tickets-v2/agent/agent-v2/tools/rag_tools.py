"""
RAG tools — knowledge base search and AI feedback recording.

suggest_solution_before_ticket is the enforcement point for the
resolution-first flow. The creator prompt mandates calling it before
create_ticket. The tool's docstring reinforces this as a precondition.

record_agent_feedback stores the user's rating of the AI's helpfulness.
This is separate from the ticket system's own satisfaction survey.
"""

from langchain_core.tools import tool
from ports.rag_port import IRAGPort, SuggestionResult
from feedback.collector import FeedbackCollector

_rag_port: IRAGPort = None


def set_rag_port(port: IRAGPort) -> None:
    global _rag_port
    _rag_port = port


@tool
def suggest_solution_before_ticket(description: str, category: str = "") -> dict:
    """
    Searches the knowledge base for resolved tickets similar to the user's problem.

    MANDATORY: Call this BEFORE create_ticket — every single time.
    This is non-negotiable. The resolution-first flow requires it.

    If solutions_found is True AND confidence >= 0.6:
        - Present the solution to the user clearly
        - Ask: "Does this resolve your issue, or would you like to create a ticket?"
        - If resolved: ask for rating, call record_agent_feedback with
          feedback_type='solution_suggested', then stop (no ticket created)
        - If not resolved: continue to collect ticket data and call create_ticket

    If solutions_found is False OR confidence < 0.6:
        - Inform the user: "No previous solutions found in our knowledge base
          for this type of problem."
        - Proceed to collect ticket data and call create_ticket

    Args:
        description: Natural language description of the user's problem
        category: Category name to narrow the search (optional but improves results)

    Returns:
        {
          "solutions_found": bool,
          "confidence": float,   # 0.0–1.0, use 0.6 as the threshold
          "solutions": [
            {
              "ticket_name": str,
              "category": str,
              "description": str,
              "motivo_resolucion": str,
              "score": float
            },
            ...
          ]
        }
    """
    if not _rag_port:
        return {"solutions_found": False, "confidence": 0.0, "solutions": []}

    result: SuggestionResult = _rag_port.search_similar(
        query=description,
        category=category or None,
        k=5,
    )

    return {
        "solutions_found": result.solutions_found,
        "confidence": result.confidence,
        "solutions": [
            {
                "ticket_name": s.ticket_name,
                "category": s.category,
                "description": s.description,
                "motivo_resolucion": s.motivo_resolucion,
                "causa_raiz": s.causa_raiz,
                "score": s.score,
            }
            for s in result.solutions
        ],
    }


@tool
def record_agent_feedback(
    user_id: str,
    rating: str,
    feedback_type: str,
    ticket_id: str = None,
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
    return [suggest_solution_before_ticket, record_agent_feedback]
