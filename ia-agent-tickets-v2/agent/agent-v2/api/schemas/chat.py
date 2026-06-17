"""
Request and response schemas for the /agent/chat and /agent/confirm endpoints.

user_rol field name is intentional (matches v1 API contract so the
existing frontend requires zero changes).
"""

from pydantic import BaseModel
from typing import Optional, Any


class ChatRequest(BaseModel):
    user_id: int
    user_rol: str          # "creador" | "resueltor" | "supervisor"
    message: str
    thread_id: Optional[str] = None
    auto_confirm: Optional[bool] = False
    # When True, the agent graph is compiled without interrupt_before=["tools"],
    # so tool calls execute as soon as the LLM emits them. Used for E2E tests
    # and automation. When False (default), the graph pauses before tool
    # execution so the caller (chat route) can present pending actions to the
    # user for confirmation. This is the standard LangGraph human-in-the-loop
    # pattern: see core/agent.py::get_or_create_agent().


class PendingAction(BaseModel):
    """A tool call that the graph wants to execute but needs human confirmation."""
    tool_call_id: str
    tool_name: str
    arguments: dict[str, Any]
    description: str = ""  # Human-readable summary for the UI (e.g. "Crear ticket 'VPN caída'")


class ChatResponse(BaseModel):
    reply: str
    thread_id: str
    status: str = "ok"  # "ok" | "pending_actions" — new clients check this, old clients ignore
    pending_actions: list[PendingAction] = []  # empty on "ok", populated on "pending_actions"


class ConfirmRequest(BaseModel):
    """
    Request to confirm and execute pending tool calls.

    When ``confirm_action_ids`` is empty or None, ALL pending actions
    for the thread are executed (confirm-all behaviour, the safe default).

    The thread_id format is ``{user_id}:{date_or_id}`` as built by
    ``/agent/chat``.
    """
    thread_id: str
    user_id: int
    user_rol: str  # "creador" | "resueltor" | "supervisor" — must match JWT
    confirm_action_ids: Optional[list[str]] = None  # None = confirm all
