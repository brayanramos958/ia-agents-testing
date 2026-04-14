"""
Agent factory and central wiring point.

initialize_ports()      — called once at startup to inject dependencies into tools
get_tools_for_role()    — returns the correct tool set for each role
create_agent()          — builds a compiled LangGraph ReAct agent
get_or_create_agent()   — cached agent factory shared by all routes
get_response()          — blocking invoke (returns full reply)
stream_response()       — async generator: yields SSE tokens via astream_events()
"""

import json
import logging
from langchain_core.messages import SystemMessage, HumanMessage, BaseMessage, AIMessage
from langgraph.prebuilt import create_react_agent

_log = logging.getLogger(__name__)

from ports.ticket_port import ITicketPort
from ports.rag_port import IRAGPort
from core.graph import build_llm, build_checkpointer
from tools.ticket_tools import (
    set_ticket_port, set_rag_port_for_tickets,
    get_creator_tools, get_resolver_tools, get_supervisor_tools,
)
from tools.user_tools import set_user_port, get_catalog_tools
from tools.rag_tools import set_rag_port, get_rag_tools
from prompts.creator import get_creator_prompt
from prompts.resolver import get_resolver_prompt
from prompts.supervisor import get_supervisor_prompt


# ── Prompt registry ───────────────────────────────────────────────────────────

_PROMPT_BUILDERS = {
    "creador":   get_creator_prompt,
    "resueltor": get_resolver_prompt,
    "supervisor": get_supervisor_prompt,
}

_DEFAULT_PROMPT = (
    "Eres el asistente virtual de la mesa de ayuda. "
    "Por favor indica tu rol para poder ayudarte."
)


# ── Agent cache (shared across all API routes) ────────────────────────────────

_agent_cache: dict = {}


def get_or_create_agent(role: str):
    """
    Returns a compiled LangGraph ReAct agent for the given role.
    Agents are cached at module level — one per role, shared by all routes.
    Both /agent/chat and /agent/stream use the same instance.
    """
    if role not in _agent_cache:
        tools = get_tools_for_role(role)
        if not tools:
            raise ValueError(
                f"Unknown role '{role}'. Valid: creador, resueltor, supervisor"
            )
        _agent_cache[role] = create_agent(tools)
    return _agent_cache[role]


# ── Dependency injection ──────────────────────────────────────────────────────

def initialize_ports(ticket_port: ITicketPort, rag_port: IRAGPort) -> None:
    """
    Injects concrete port implementations into all tool modules.
    Must be called once during application startup (inside FastAPI lifespan).
    """
    set_ticket_port(ticket_port)
    set_rag_port_for_tickets(rag_port)
    set_user_port(ticket_port)   # user_tools reuses the ticket port for catalog queries
    set_rag_port(rag_port)


# ── Tool sets per role ────────────────────────────────────────────────────────

def get_tools_for_role(role: str) -> list:
    """
    Returns the tool list for the given role.
    LangGraph enforces this at the graph level — a role cannot call tools
    that are not in its list regardless of what the prompt says.
    """
    catalog = get_catalog_tools()
    rag     = get_rag_tools()

    if role == "creador":
        return get_creator_tools() + catalog + rag
    if role == "resueltor":
        return get_resolver_tools() + catalog + rag
    if role == "supervisor":
        return get_supervisor_tools() + catalog + rag

    return []  # Unknown role gets no tools


# ── Agent creation ────────────────────────────────────────────────────────────

def create_agent(tools: list):
    """
    Builds and compiles a LangGraph ReAct agent with the given tools.
    One agent per role is created and cached in api/routes/chat.py.

    messages_modifier: mantiene solo los últimos 8 mensajes de historial
    para no exceder los TPM de modelos free. El SystemMessage siempre
    se preserva via include_system=True.
    """
    from langchain_core.messages import SystemMessage as _SM, AIMessage as _AI, ToolMessage as _TM

    def _trim_hook(state):
        """
        Sanitiza y limita el historial antes de cada llamada al LLM.

        Problemas que resuelve:
        1. ToolMessages huérfanos: si el trim corta un AIMessage con tool_calls
           pero deja sus ToolMessages correspondientes, Groq los rechaza (400).
        2. ToolMessage con content vacío: Groq requiere string no vacío.
        3. Crecimiento ilimitado del contexto: limita a 12 mensajes no-sistema.

        Estrategia de trim:
        - Mantener los últimos N mensajes no-sistema.
        - Si el primer mensaje tras el corte es un ToolMessage, retroceder hasta
          el AIMessage con tool_calls que lo originó para evitar huérfanos.
        """
        from langchain_core.messages import HumanMessage as _HM
        msgs = state["messages"]
        system = [m for m in msgs if isinstance(m, _SM)]
        non_system = [m for m in msgs if not isinstance(m, _SM)]

        # Paso 1: corta a los últimos 12
        window = non_system[-12:] if len(non_system) > 12 else non_system

        # Paso 2: detecta ToolMessages huérfanos al inicio de la ventana.
        # Un TM es huérfano si no hay ningún AIMessage con tool_calls antes de él.
        safe_start = 0
        for i, m in enumerate(window):
            if isinstance(m, _TM):
                has_parent = any(
                    isinstance(window[j], _AI) and getattr(window[j], "tool_calls", None)
                    for j in range(i)
                )
                if not has_parent:
                    # Retrocede: arranca desde el siguiente HumanMessage
                    for k in range(i, len(window)):
                        if isinstance(window[k], _HM):
                            safe_start = k
                            break
                    break

        window = window[safe_start:]

        # Paso 3: sanea ToolMessages con content vacío o None (Groq rechaza content vacío).
        # model_copy() es el método correcto para Pydantic v2 (inmutable por defecto).
        sanitized = []
        for m in window:
            if isinstance(m, _TM) and not m.content:
                m = m.model_copy(update={"content": "[sin resultado]"})
            sanitized.append(m)

        # Paso 4: elimina AIMessages con tool_calls sin ToolMessage correspondiente.
        # Ocurre cuando una tool crashea antes de devolver resultado — el checkpoint
        # guarda el AIMessage pero nunca recibe el ToolMessage, corrompiendo el hilo.
        clean = []
        for i, m in enumerate(sanitized):
            if isinstance(m, _AI) and getattr(m, "tool_calls", None):
                expected_ids = {tc["id"] for tc in m.tool_calls}
                following_ids = {
                    r.tool_call_id
                    for r in sanitized[i + 1:]
                    if isinstance(r, _TM) and hasattr(r, "tool_call_id")
                }
                if not expected_ids.issubset(following_ids):
                    # AIMessage huérfano — descartar éste y todo lo que sigue
                    break
            clean.append(m)
        sanitized = clean

        # Debug temporal (quitar en producción)
        import logging
        _log = logging.getLogger(__name__)
        _log.debug("trim_hook: %d messages → sending %d", len(non_system), len(sanitized))

        return {"messages": system + sanitized}

    llm = build_llm()
    checkpointer = build_checkpointer()
    return create_react_agent(
        model=llm,
        tools=tools,
        checkpointer=checkpointer,
        pre_model_hook=_trim_hook,
    )


# ── Response extraction ───────────────────────────────────────────────────────

async def get_response(
    agent,
    user_message: str,
    thread_id: str,
    user_id: int,
    user_role: str,
) -> str:
    """
    Invokes the agent and returns the final text reply.

    Uses ainvoke() — compatible with AsyncSqliteSaver which is required
    for the streaming endpoint. The /agent/chat route must be async too.

    Handles the edge case where the last message has tool_calls but no
    text content — scans backwards for the first AIMessage with actual text.
    """
    prompt_fn = _PROMPT_BUILDERS.get(user_role)
    system_content = prompt_fn(user_id) if prompt_fn else _DEFAULT_PROMPT

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 30,
    }

    result = await agent.ainvoke(
        {
            "messages": [
                SystemMessage(content=system_content),
                HumanMessage(content=user_message),
            ]
        },
        config=config,
    )

    # Find the last AIMessage that has text content (not just tool calls)
    for msg in reversed(result.get("messages", [])):
        if (
            isinstance(msg, AIMessage)
            and msg.content
            and not getattr(msg, "tool_calls", None)
        ):
            return msg.content

    return (
        "No pude procesar tu solicitud en este momento. "
        "Por favor intenta de nuevo."
    )


# ── Streaming response ────────────────────────────────────────────────────────

async def stream_response(
    agent,
    user_message: str,
    thread_id: str,
    user_id: int,
    user_role: str,
):
    """
    Async generator that streams the agent reply token by token via SSE.

    Yields newline-delimited SSE frames:
        data: {"t":"token","v":"Hola"}\\n\\n   — text token from LLM
        data: {"t":"tool","v":"get_tickets"}\\n\\n — tool being executed (UX hint)
        data: {"t":"done"}\\n\\n                — stream complete
        data: {"t":"error","v":"..."}\\n\\n     — unrecoverable error

    Frontend consumes with fetch + ReadableStream or EventSource.
    The existing /agent/chat endpoint is unaffected — both routes share the
    same compiled agent instance via get_or_create_agent().
    """
    prompt_fn = _PROMPT_BUILDERS.get(user_role)
    system_content = prompt_fn(user_id) if prompt_fn else _DEFAULT_PROMPT

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 30,
    }

    input_data = {
        "messages": [
            SystemMessage(content=system_content),
            HumanMessage(content=user_message),
        ]
    }

    try:
        async for event in agent.astream_events(input_data, config, version="v2"):
            kind = event["event"]

            # ── Text token from LLM ──────────────────────────────────────────
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                # Skip tool_call_chunks — only stream final text tokens
                if chunk.content and not getattr(chunk, "tool_call_chunks", None):
                    yield f"data: {json.dumps({'t': 'token', 'v': chunk.content})}\n\n"

            # ── Tool execution started — send UX hint ────────────────────────
            elif kind == "on_tool_start":
                tool_name = event.get("name", "tool")
                yield f"data: {json.dumps({'t': 'tool', 'v': tool_name})}\n\n"

        yield f"data: {json.dumps({'t': 'done'})}\n\n"

    except Exception as exc:
        _log.exception("stream_response error thread=%s user=%s", thread_id, user_id)
        yield f"data: {json.dumps({'t': 'error', 'v': str(exc)})}\n\n"
