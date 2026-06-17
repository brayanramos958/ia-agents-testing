"""
POST /agent/chat    — conversational endpoint for human users.
POST /agent/confirm — resume an interrupted graph after human confirmation.
POST /agent/reject  — cancel all pending tool calls in an interrupted graph.

One compiled LangGraph agent per role is cached in _agents dict.
All users with the same role share one agent; thread_id differentiates them.
Agents are lazy-initialized on first request for that role.
"""

import logging
from datetime import date
from fastapi import APIRouter, HTTPException
from api.schemas.chat import ChatRequest, ChatResponse, ConfirmRequest, RejectRequest
from api.middleware.rate_limit import check_rate_limit
from api.middleware.injection_detector import scan_message  # Security Capa 2
from core.agent import get_or_create_agent, get_response, resume_agent, reject_agent
from core.context import current_thread_id, current_user_id, current_user_role
from core.events import emit

logger = logging.getLogger(__name__)
router = APIRouter()

# ── user_id validation ─────────────────────────────────────────────────────


def _validate_body_match(request: ChatRequest | ConfirmRequest | RejectRequest) -> None:
    """Verify body user_id/role match the JWT claims (Security: user_id validation)."""
    token_uid = current_user_id.get(0)
    token_role = current_user_role.get("")
    if token_uid and request.user_id != token_uid:
        raise HTTPException(
            status_code=403,
            detail=(f"user_id mismatch: token={token_uid} body={request.user_id}. "
                    "El user_id del body debe coincidir con el del token."),
        )
    if token_role and request.user_rol != token_role:
        raise HTTPException(
            status_code=403,
            detail=(f"role mismatch: token={token_role} body={request.user_rol}. "
                    "El rol del body debe coincidir con el del token."),
        )


def _normalize_thread_id(raw: str, user_id: int) -> str:
    """
    Normalise a thread_id to the format ``{user_id}:{id}`` used by the checkpointer.

    Accepts both the raw id (e.g. "test-001") and the already-prefixed form
    (e.g. "2796:test-001") returned by ChatResponse.thread_id.
    """
    if not raw.startswith(f"{user_id}:"):
        raw = raw.removeprefix(str(user_id)).lstrip(":")
        raw = raw or str(date.today())
    else:
        raw = raw[len(str(user_id)) + 1:]
    return f"{user_id}:{raw}"


# ── Routes ──────────────────────────────────────────────────────────────────


@router.post("/agent/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
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
    session_id = thread_id  # session_id = thread_id (one conversation = one session)
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
    try:
        agent_reply = await get_response(
            agent=agent,
            user_message=request.message,
            thread_id=thread_id,
            user_id=request.user_id,
            user_role=request.user_rol,
            auto_confirm=request.auto_confirm or False,
        )
    except Exception as exc:
        logger.exception("Agent error for thread=%s user=%s", thread_id, request.user_id)
        raise HTTPException(status_code=500, detail=str(exc))
    return ChatResponse(
        reply=agent_reply["reply"],
        thread_id=thread_id,
        status=agent_reply.get("status", "ok"),
        pending_actions=agent_reply.get("pending_actions", []),
    )


@router.post("/agent/confirm", response_model=ChatResponse)
async def confirm(request: ConfirmRequest) -> ChatResponse:
    """
    Resume a graph that was interrupted waiting for human confirmation.

    When /agent/chat returns status="pending_actions", the frontend renders
    a confirmation UI. When the user confirms, this endpoint resumes the
    graph so the pending tool calls execute and the LLM generates a final
    response.

    The same thread may interrupt AGAIN after resume if the LLM emits
    more tool calls (multi-step workflows) — the response will again have
    status="pending_actions".
    """
    _validate_body_match(request)
    check_rate_limit(request.user_id)

    thread_id = _normalize_thread_id(request.thread_id, request.user_id)
    current_thread_id.set(thread_id)

    # Confirmation always uses the interactive agent (auto_confirm=False).
    # The confirm flow is the definition of human-in-the-loop.
    try:
        agent = get_or_create_agent(request.user_rol, auto_confirm=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        agent_reply = await resume_agent(
            agent=agent,
            thread_id=thread_id,
            user_id=request.user_id,
            confirm_action_ids=request.confirm_action_ids,
        )
    except RuntimeError as exc:
        # 409 Conflict: the graph is not in a state that can be resumed
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.exception(
            "Confirm error for thread=%s user=%s", thread_id, request.user_id,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(
        reply=agent_reply["reply"],
        thread_id=thread_id,
        status=agent_reply.get("status", "ok"),
        pending_actions=agent_reply.get("pending_actions", []),
    )


@router.post("/agent/reject", response_model=ChatResponse)
async def reject(request: RejectRequest) -> ChatResponse:
    """
    Reject all pending tool calls in an interrupted graph.

    When /agent/chat returns status="pending_actions", the frontend renders
    a confirmation UI with a "Cancelar" button. When the user rejects,
    this endpoint sends rejection ToolMessages to the graph so the LLM
    can acknowledge the cancellation and the thread is freed for further
    conversation.
    """
    _validate_body_match(request)
    check_rate_limit(request.user_id)

    thread_id = _normalize_thread_id(request.thread_id, request.user_id)
    current_thread_id.set(thread_id)

    # Rejection always uses the interactive agent.
    try:
        agent = get_or_create_agent(request.user_rol, auto_confirm=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    try:
        agent_reply = await reject_agent(
            agent=agent,
            thread_id=thread_id,
            user_id=request.user_id,
            reason=request.reason or "",
        )
    except RuntimeError as exc:
        # 409 Conflict: the graph is not in a state that can be rejected
        raise HTTPException(status_code=409, detail=str(exc))
    except Exception as exc:
        logger.exception(
            "Reject error for thread=%s user=%s", thread_id, request.user_id,
        )
        raise HTTPException(status_code=500, detail=str(exc))

    return ChatResponse(
        reply=agent_reply["reply"],
        thread_id=thread_id,
        status=agent_reply.get("status", "ok"),
        pending_actions=agent_reply.get("pending_actions", []),
    )
