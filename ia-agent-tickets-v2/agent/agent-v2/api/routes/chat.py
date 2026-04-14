"""
POST /agent/chat — conversational endpoint for human users.

One compiled LangGraph agent per role is cached in _agents dict.
All users with the same role share one agent; thread_id differentiates them.
Agents are lazy-initialized on first request for that role.
"""

import logging
from fastapi import APIRouter, HTTPException
from api.schemas.chat import ChatRequest, ChatResponse
from core.agent import get_or_create_agent, get_response

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agent/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    thread_id = request.thread_id or f"user-{request.user_id}"
    try:
        agent = get_or_create_agent(request.user_rol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    try:
        reply = await get_response(
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
