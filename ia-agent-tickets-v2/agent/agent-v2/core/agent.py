"""
Agent factory and central wiring point.

initialize_ports()        — called once at startup to inject dependencies into tools
get_tools_for_role()      — returns the correct tool set for each role
create_agent()            — builds a compiled LangGraph ReAct agent
get_or_create_agent()     — cached agent factory shared by all routes
_prepare_invocation()     — shared pre-flight: prompt build, context fetch, orphan fix
get_response()            — blocking invoke (returns full reply)
stream_response()         — async generator: yields SSE tokens via astream_events()
"""

import json
import logging
import asyncio
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from langgraph.prebuilt.tool_node import ToolNode

_log = logging.getLogger(__name__)


# ── Creator context cache ─────────────────────────────────────────────────────
# Avoids one Odoo round-trip per message in the same conversation.
# Key: thread_id. Value: pre-formatted context string.
# Cache is invalidated explicitly when create_ticket succeeds (see invalidate_creator_context).

_creator_context_cache: dict = {}
_CREATOR_CONTEXT_CACHE_MAX = 500  # threads to keep in memory


async def _fetch_creator_context(user_id: int, thread_id: str) -> str:
    """
    Pre-fetches open tickets for a creador user and returns a formatted
    context block to inject into the system prompt.

    Results are cached by thread_id — the Odoo call is made only ONCE
    per conversation thread, not on every message.

    Returns an empty string on any error so the agent can still function.
    """
    if thread_id in _creator_context_cache:
        return _creator_context_cache[thread_id]

    try:
        from tools.ticket_tools import _port
        if _port is None:
            return ""
        tickets = await asyncio.to_thread(_port.get_tickets_by_creator, user_id)
        if not tickets:
            result = "\n\n## Historial del usuario\nSin tickets registrados."
        else:
            # The adapter already filters is_close=False at the Odoo level.
            # This client-side filter is a secondary defense for adapters that
            # don't enforce the stage filter (e.g. express_adapter in dev).
            #
            # Odoo returns stage_id as [id, "Stage Name"] or False.
            # We treat False (no stage) as open — do not filter it out.
            _CLOSED_STAGE_NAMES = {
                "resuelto", "cerrado", "cancelado",
                "resolved", "closed", "cancelled", "done",
            }

            def _is_open(ticket: dict) -> bool:
                stage = ticket.get("stage_id")
                if isinstance(stage, list) and len(stage) >= 2:
                    return str(stage[1]).lower() not in _CLOSED_STAGE_NAMES
                return True  # False / missing stage → assume open

            open_tickets = [t for t in tickets if _is_open(t)]

            if not open_tickets:
                result = "\n\n## Historial del usuario\nSin tickets abiertos actualmente."
            else:
                lines = ["\n\n## Historial del usuario (tickets abiertos — usa esta info en el Paso 1A)"]
                for t in open_tickets[:10]:
                    stage = t.get("stage_id")
                    stage_name = stage[1] if isinstance(stage, list) and len(stage) >= 2 else "N/A"
                    lines.append(
                        f"- {t.get('name', 'N/A')}: {t.get('asunto', 'N/A')} "
                        f"[estado: {stage_name}]"
                    )
                result = "\n".join(lines)
    except Exception as exc:
        _log.debug("Could not pre-fetch user tickets for context: %s", exc)
        result = ""

    # Evict oldest entry if the cache is full (simple FIFO)
    if len(_creator_context_cache) >= _CREATOR_CONTEXT_CACHE_MAX:
        oldest = next(iter(_creator_context_cache))
        del _creator_context_cache[oldest]

    _creator_context_cache[thread_id] = result
    return result


def invalidate_creator_context(thread_id: str) -> None:
    """
    Removes the cached creator context for a thread.
    Call this after create_ticket succeeds so the next message reflects
    the newly created ticket in the user's history.
    """
    _creator_context_cache.pop(thread_id, None)


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
    "creador":    get_creator_prompt,
    "resueltor":  get_resolver_prompt,
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

    return []


# ── Agent creation ────────────────────────────────────────────────────────────

def create_agent(tools: list):
    """
    Builds and compiles a LangGraph ReAct agent with the given tools.
    One agent per role is created and cached in _agent_cache.

    pre_model_hook (_trim_hook):
    - Mantiene solo el SystemMessage más reciente (evita acumulación entre turnos).
    - Limita el historial a los últimos 12 mensajes no-sistema.
    - Repara ToolMessages huérfanos y vacíos que Groq rechaza.
    """
    from langchain_core.messages import SystemMessage as _SM, AIMessage as _AI, ToolMessage as _TM

    def _trim_hook(state):
        """
        Sanitiza y limita el historial antes de cada llamada al LLM.

        Problemas que resuelve:
        1. SystemMessages acumulados: cada ainvoke() inyecta un SystemMessage nuevo al
           checkpoint. Sin este fix, N llamadas = N SystemMessages en el historial,
           inflando el contexto innecesariamente. Se conserva solo el más reciente.
        2. ToolMessages huérfanos: si el trim corta un AIMessage con tool_calls
           pero deja sus ToolMessages correspondientes, Groq los rechaza (400).
        3. ToolMessage con content vacío: Groq requiere string no vacío.
        4. Crecimiento ilimitado del contexto: limita a 12 mensajes no-sistema.
        """
        from langchain_core.messages import HumanMessage as _HM
        msgs = state["messages"]

        # Fix #5: keep only the MOST RECENT SystemMessage.
        # Each ainvoke/astream_events call appends a new SystemMessage to the checkpoint.
        # Collecting all of them inflates context on every turn — keep only the last.
        all_system = [m for m in msgs if isinstance(m, _SM)]
        system = [all_system[-1]] if all_system else []
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
                    for k in range(i, len(window)):
                        if isinstance(window[k], _HM):
                            safe_start = k
                            break
                    break

        window = window[safe_start:]

        # Paso 3: sanea ToolMessages con content vacío o None (Groq rechaza content vacío).
        sanitized = []
        for m in window:
            if isinstance(m, _TM) and not m.content:
                m = m.model_copy(update={"content": "[sin resultado]"})
            sanitized.append(m)

        # Paso 4: elimina AIMessages con tool_calls sin ToolMessage correspondiente.
        # Ocurre cuando una tool crashea antes de devolver resultado.
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
                    break
            clean.append(m)
        sanitized = clean

        _log.debug("trim_hook: %d messages → sending %d", len(non_system), len(sanitized))

        return {"messages": system + sanitized}

    llm = build_llm()
    checkpointer = build_checkpointer()
    tool_node = ToolNode(tools, handle_tool_errors=True)
    return create_react_agent(
        model=llm,
        tools=tool_node,
        checkpointer=checkpointer,
        pre_model_hook=_trim_hook,
    )


# ── Shared pre-flight logic ───────────────────────────────────────────────────

async def _prepare_invocation(
    agent,
    user_message: str,
    thread_id: str,
    user_id: int,
    user_role: str,
) -> tuple[dict, dict]:
    """
    Builds input_data and config for an agent invocation.

    Extracted to avoid duplicating this logic between get_response() and
    stream_response(). Both endpoints share exactly the same pre-flight:

    1. Build system prompt from role-specific builder.
    2. For creador: inject pre-fetched ticket context (cached per thread_id).
    3. Detect corrupted thread (orphaned tool_calls from a crashed Odoo session)
       and reset to a fresh thread_id if needed.

    Returns:
        (input_data, config) — ready to pass to ainvoke() or astream_events()
    """
    prompt_fn = _PROMPT_BUILDERS.get(user_role)
    system_content = prompt_fn(user_id) if prompt_fn else _DEFAULT_PROMPT

    if user_role == "creador":
        tickets_ctx = await _fetch_creator_context(user_id, thread_id)
        system_content = system_content + tickets_ctx

    config = {
        "configurable": {"thread_id": thread_id},
        "recursion_limit": 30,
    }

    # ── Detect corrupted thread (orphaned tool_calls from a crashed session) ──
    # When a session crashes mid-tool-call, the checkpoint stores an AIMessage
    # with tool_calls but no corresponding ToolMessage. On the next request,
    # LangGraph routes to the tools node BEFORE pre_model_hook can clean it up,
    # causing "INVALID_CHAT_HISTORY". We detect and reset the thread proactively.
    try:
        state = await agent.aget_state(config)
        if state and state.values.get("messages"):
            last_msg = state.values["messages"][-1]
            if isinstance(last_msg, AIMessage) and getattr(last_msg, "tool_calls", None):
                import time as _time
                fresh_thread = f"{thread_id}-r{int(_time.time())}"
                _log.warning(
                    "Thread %s has orphaned tool_calls (crashed session) — "
                    "resetting to fresh thread %s",
                    thread_id, fresh_thread,
                )
                config = {"configurable": {"thread_id": fresh_thread}, "recursion_limit": 30}
                # Also clear the stale creator context for the old thread
                invalidate_creator_context(thread_id)
    except Exception as _state_err:
        _log.debug("Could not inspect thread state: %s", _state_err)

    input_data = {
        "messages": [
            SystemMessage(content=system_content),
            HumanMessage(content=user_message),
        ]
    }

    return input_data, config


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
    """
    input_data, config = await _prepare_invocation(
        agent, user_message, thread_id, user_id, user_role
    )

    result = await agent.ainvoke(input_data, config=config)

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
    input_data, config = await _prepare_invocation(
        agent, user_message, thread_id, user_id, user_role
    )

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
