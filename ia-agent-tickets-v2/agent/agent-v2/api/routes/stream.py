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
from api.middleware.rate_limit import check_rate_limit
from api.middleware.injection_detector import scan_message  # Security Capa 2
from core.agent import get_or_create_agent, stream_response
from core.context import current_thread_id, current_user_id, current_user_role
from core.events import emit

logger = logging.getLogger(__name__)
router = APIRouter()

# ── user_id validation ─────────────────────────────────────────────────────


def _validate_body_match(request: ChatRequest) -> None:
    """Verify body user_id/role match the JWT claims."""
    token_uid = current_user_id.get(0)
    token_role = current_user_role.get("")
    if token_uid and request.user_id != token_uid:
        raise HTTPException(status_code=403,
                            detail=f"user_id mismatch: token={token_uid} body={request.user_id}")
    if token_role and request.user_rol != token_role:
        raise HTTPException(status_code=403,
                            detail=f"role mismatch: token={token_role} body={request.user_rol}")


# ── Routes ──────────────────────────────────────────────────────────────────


@router.post("/agent/stream")
async def chat_stream(request: ChatRequest):
    """
    Streams the agent reply token by token via Server-Sent Events.

    Same auth, same roles, same conversation memory as /agent/chat.
    The thread_id links this stream to the conversation history in the checkpointer.
    """
    check_rate_limit(request.user_id)
    _validate_body_match(request)
    raw_thread = request.thread_id or str(date.today())
    thread_id = f"{request.user_id}:{raw_thread}"
    current_thread_id.set(thread_id)

    # Security Capa 2: scan for prompt injection before reaching the LLM
    detection = scan_message(request.message, request.user_id, thread_id)
    if detection.blocked:
        raise HTTPException(status_code=400, detail=f"Mensaje bloqueado: {detection.reason}")

    # Usage tracking (Fase 1.5) — fire-and-forget via event bus
    # metrics.usage_tracker subscribes to "user.chat_started" and "user.message_sent"
    session_id = thread_id  # session_id = thread_id
    emit("user.chat_started",
         user_id=request.user_id, user_role=request.user_rol,
         thread_id=thread_id, session_id=session_id)
    emit("user.message_sent",
         user_id=request.user_id, user_role=request.user_rol,
         thread_id=thread_id, session_id=session_id)

    try:
        agent = get_or_create_agent(
            request.user_rol, auto_confirm=request.auto_confirm or False,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    return StreamingResponse(
        stream_response(
            agent=agent,
            user_message=request.message,
            thread_id=thread_id,
            user_id=request.user_id,
            user_role=request.user_rol,
            auto_confirm=request.auto_confirm or False,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection":    "keep-alive",
            "X-Accel-Buffering": "no",   # Disable nginx/proxy buffering
        },
    )
