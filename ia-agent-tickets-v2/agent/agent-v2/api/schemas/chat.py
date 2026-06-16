"""
Request and response schemas for the /agent/chat endpoint.

user_rol field name is intentional (matches v1 API contract so the
existing frontend requires zero changes).
"""

from pydantic import BaseModel
from typing import Optional


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


class ChatResponse(BaseModel):
    reply: str
    thread_id: str
