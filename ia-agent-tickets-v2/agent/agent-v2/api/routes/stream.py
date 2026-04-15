"""
POST /agent/stream — Server-Sent Events streaming endpoint.

Returns the agent reply token by token instead of waiting for the full response.
Uses the same compiled agent instance as /agent/chat (shared via get_or_create_agent).

SSE event format:
    data: {"t":"token","v":"<text>"}      — LLM text token
    data: {"t":"tool","v":"<tool_name>"}  — tool being called (UX hint)
    data: {"t":"done"}                    — stream finished
    data: {"t":"error","v":"<message>"}   — unrecoverable error

Frontend usage (fetch + ReadableStream):
    const resp = await fetch("/agent/stream", { method: "POST", body: ... });
    const reader = resp.body.getReader();
    // decode and split on "\\n\\n" to get individual frames

Frontend usage (EventSource — GET only, not suitable for POST with body):
    Use fetch streaming above instead of EventSource for POST endpoints.
"""

import logging
from datetime import date
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from api.schemas.chat import ChatRequest
from core.agent import get_or_create_agent, stream_response

logger = logging.getLogger(__name__)
router = APIRouter()


@router.post("/agent/stream")
async def chat_stream(request: ChatRequest):
    """
    Streams the agent reply token by token via Server-Sent Events.

    Same auth, same roles, same conversation memory as /agent/chat.
    The thread_id links this stream to the conversation history in the checkpointer.
    """
    thread_id = request.thread_id or f"user-{request.user_id}-{date.today()}"

    try:
        agent = get_or_create_agent(request.user_rol)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return StreamingResponse(
        stream_response(
            agent=agent,
            user_message=request.message,
            thread_id=thread_id,
            user_id=request.user_id,
            user_role=request.user_rol,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection":    "keep-alive",
            "X-Accel-Buffering": "no",   # Disable nginx/proxy buffering
        },
    )
