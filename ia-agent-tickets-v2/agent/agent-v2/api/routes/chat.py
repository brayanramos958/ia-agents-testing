"""
POST /agent/chat — conversational endpoint for human users.

One compiled LangGraph agent per role is cached in _agents dict.
All users with the same role share one agent; thread_id differentiates them.
Agents are lazy-initialized on first request for that role.
"""

import logging
from fastapi import APIRouter, HTTPException
from api.schemas.chat import ChatRequest, ChatResponse
from core.agent import create_agent, get_tools_for_role, get_response

logger = logging.getLogger(__name__)
router = APIRouter()

# Cache: role → compiled agent (lazy initialized)
_agents: dict = {}


def _get_or_create_agent(role: str):
    if role not in _agents:
        tools = get_tools_for_role(role)
        if not tools:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown role '{role}'. Valid: creador, resueltor, supervisor",
            )
        _agents[role] = create_agent(tools)
    return _agents[role]


@router.post("/agent/chat", response_model=ChatResponse)
def chat(request: ChatRequest) -> ChatResponse:
    thread_id = request.thread_id or f"user-{request.user_id}"
    agent = _get_or_create_agent(request.user_rol)
    try:
        reply = get_response(
            agent=agent,
            user_message=request.message,
            thread_id=thread_id,
            user_id=request.user_id,
            user_role=request.user_rol,
        )
    except Exception as exc:
        logger.exception("Agent error for thread=%s user=%s", thread_id, request.user_id)
        raise HTTPException(status_code=500, detail=str(exc))
    return ChatResponse(reply=reply, thread_id=thread_id)
