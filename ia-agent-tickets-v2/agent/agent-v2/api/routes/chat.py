"""
POST /agent/chat — conversational endpoint for human users.

One compiled LangGraph agent per role is cached in _agents dict.
All users with the same role share one agent; thread_id differentiates them.
Agents are lazy-initialized on first request for that role.
"""

import logging
from datetime import date
from fastapi import APIRouter, HTTPException
from api.schemas.chat import ChatRequest, ChatResponse
from api.middleware.rate_limit import check_rate_limit
from core.agent import get_or_create_agent, get_response
from core.graph import build_checkpointer

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agent/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    check_rate_limit(request.user_id)
    raw_thread = request.thread_id or str(date.today())
    thread_id = f"{request.user_id}:{raw_thread}"

    # Set thread_id for structured logging (Prop-9)
    from core.context import current_thread_id
    current_thread_id.set(thread_id)

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
        logger.exception("Agent error")
        raise HTTPException(status_code=500, detail=str(exc))
    return ChatResponse(reply=reply, thread_id=thread_id)


@router.get("/agent/debug/thread/{thread_id}")
async def debug_thread(thread_id: str):
    """Return the full message history for a thread (debug only)."""
    try:
        checkpointer = build_checkpointer()
        config = {"configurable": {"thread_id": thread_id}}
        state = await checkpointer.aget(config)
        if not state:
            raise HTTPException(status_code=404, detail="Thread not found")
        messages = state.get("channel_values", {}).get("messages", [])
        serializable = []
        for m in messages:
            d = {"type": type(m).__name__}
            if hasattr(m, "content"):
                d["content"] = m.content[:500] if isinstance(m.content, str) else str(m.content)[:500]
            if hasattr(m, "tool_calls") and m.tool_calls:
                d["tool_calls"] = [{"name": tc.get("name"), "args": tc.get("args")} for tc in m.tool_calls]
            if hasattr(m, "name") and m.name:
                d["name"] = m.name
            if hasattr(m, "tool_call_id") and m.tool_call_id:
                d["tool_call_id"] = m.tool_call_id
            serializable.append(d)
        return {"thread_id": thread_id, "message_count": len(serializable), "messages": serializable}
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("debug_thread error")
        raise HTTPException(status_code=500, detail=str(exc))
