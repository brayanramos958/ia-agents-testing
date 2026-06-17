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
import os
from langchain_core.messages import SystemMessage, HumanMessage, AIMessage
from langgraph.prebuilt import create_react_agent
from langgraph.prebuilt.tool_node import ToolNode
from config.settings import settings
from core.security import frame_external_data

_log = logging.getLogger(__name__)

# ── LLM concurrency semaphore ─────────────────────────────────────────────────
# Limits simultaneous LLM calls to prevent saturating Groq/Vercel rate limits.
# Initialised lazily on first request so settings is fully loaded.
_LLM_SEMAPHORE: asyncio.Semaphore | None = None


def _get_llm_semaphore() -> asyncio.Semaphore:
    """Lazy-init the LLM semaphore from settings. Thread-safe idempotent."""
    global _LLM_SEMAPHORE
    if _LLM_SEMAPHORE is None:
        max_conc = settings.llm_max_concurrent
        _LLM_SEMAPHORE = asyncio.Semaphore(max_conc)
        _log.info("llm_semaphore_initialised", extra={"max_concurrent": max_conc})
    return _LLM_SEMAPHORE


# ── Creator context cache ─────────────────────────────────────────────────────
# Avoids one Odoo round-trip per message in the same conversation.
# Key: thread_id. Value: pre-formatted context string.
# Cache is invalidated explicitly when create_ticket succeeds (see invalidate_creator_context).
#
# In multi-worker production: uses PostgreSQL cache (shared across workers).
# In single-process dev: falls back to in-memory dict (avoids PostgreSQL round-trip).

_USE_SHARED_CACHE = bool(os.environ.get("AGENT_USE_SHARED_CACHE", "1") == "1")

_creator_context_cache: dict = {}  # In-memory fallback (dev only)
_CREATOR_CONTEXT_CACHE_MAX = settings.context_cache_max_size  # threads to keep in memory
_shared_cache = None  # PostgreSQL cache instance (lazy init)


def _extract_category_name(ticket: dict) -> str:
    """Extract human-readable category from Odoo/Express ticket dict."""
    cat = ticket.get("category_id")
    if isinstance(cat, list) and len(cat) >= 2:
        return str(cat[1])
    if isinstance(cat, str) and cat:
        return cat
    return "Sin categoría"


def _extract_type_name(ticket: dict) -> str:
    """Extract human-readable ticket type from Odoo/Express ticket dict."""
    tt = ticket.get("ticket_type_id")
    if isinstance(tt, list) and len(tt) >= 2:
        return str(tt[1])
    if isinstance(tt, str) and tt:
        return tt
    return "Sin tipo"


async def _fetch_creator_context(user_id: int, thread_id: str) -> str:
    """
    Pre-fetches open tickets for a creador user and returns a formatted
    context block to inject into the system prompt.

    Results are cached by thread_id — the Odoo call is made only ONCE
    per conversation thread, not on every message.

    In multi-worker production: uses PostgreSQL shared cache.
    In single-process dev: uses in-memory dict.

    Returns an empty string on any error so the agent can still function.
    """
    global _shared_cache

    cache_key = f"creator_ctx:{thread_id}"

    # ── Read from cache (shared or in-memory) ───────────────────────────────
    if _USE_SHARED_CACHE:
        if _shared_cache is None:
            from core.cache import PostgreSQLCache
            _shared_cache = PostgreSQLCache(ttl_seconds=settings.cache_ttl_seconds)
        cached = await _shared_cache.get(cache_key)
        if cached is not None:
            return cached
    else:
        if thread_id in _creator_context_cache:
            return _creator_context_cache[thread_id]

    # ── Cache miss — fetch from Odoo ────────────────────────────────────────
    try:
        from tools.ticket_tools import _port
        if _port is None:
            return ""
        # Direct async call — the adapter is now fully async (Fase 8).
        # No need for asyncio.to_thread() — the port is already on the event loop.
        tickets = await _port.get_tickets_by_creator(user_id)
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
                lines = ["\n\n## Historial del usuario (tickets abiertos):"]
                for t in open_tickets[:3]:
                    cat = _extract_category_name(t)
                    ttype = _extract_type_name(t)
                    created = str(t.get("create_date", "?"))[:10]
                    lines.append(
                        f"- {t.get('name','N/A')} | {ttype} | {cat} | {created}"
                        f"\n  Asunto: {t.get('asunto','N/A')}"
                    )
                if len(open_tickets) > 3:
                    lines.append(f"(+{len(open_tickets)-3} mas)")
                result = "\n".join(lines)
    except (psycopg.Error, ConnectionError, TimeoutError) as exc:
        # Pre-fetch is best-effort. If the backend or DB is unreachable,
        # we return an empty string and let the LLM proceed without context.
        _log.debug("Could not pre-fetch user tickets for context: %s", exc)
        result = ""

    # ── Write to cache (shared or in-memory) ───────────────────────────────
    if _USE_SHARED_CACHE:
        await _shared_cache.set(cache_key, result)
    else:
        # Evict oldest entry if the cache is full (simple FIFO)
        if len(_creator_context_cache) >= _CREATOR_CONTEXT_CACHE_MAX:
            oldest = next(iter(_creator_context_cache))
            del _creator_context_cache[oldest]
        _creator_context_cache[thread_id] = result

    return result


def invalidate_creator_context(thread_id: str) -> None:
    """
    Remove the cached creator context for a thread.

    Call this after ``create_ticket`` succeeds so the next message reflects
    the newly created ticket in the user's history.

    In multi-worker production: invalidates in PostgreSQL (visible to all workers).
    In single-process dev: invalidates in-memory dict.
    """
    if _USE_SHARED_CACHE and _shared_cache is not None:
        # Fire-and-forget — we don't await in sync context.
        # The next read will simply see the stale value briefly.
        cache_key = f"creator_ctx:{thread_id}"
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're inside a running event loop — schedule as a task
                loop.create_task(_shared_cache.delete(cache_key))
            else:
                loop.run_until_complete(_shared_cache.delete(cache_key))
        except RuntimeError:
            # No event loop available — fall back to in-memory invalidation
            _creator_context_cache.pop(thread_id, None)
    else:
        _creator_context_cache.pop(thread_id, None)


# ── Resolver context cache ────────────────────────────────────────────────────
# Same pattern as creator context: pre-fetch assigned tickets once per thread.
# Avoids the resolver having to call get_my_assigned_tickets on every message.

_resolver_context_cache: dict = {}  # In-memory fallback (dev only)
_RESOLVER_CONTEXT_CACHE_MAX = settings.context_cache_max_size


async def _fetch_resolver_context(user_id: int, thread_id: str) -> str:
    """
    Pre-fetches tickets assigned to this resolver and returns a formatted
    context block to inject into the system prompt.

    Cached by thread_id — only calls Odoo once per conversation.

    In multi-worker production: uses PostgreSQL shared cache.
    In single-process dev: uses in-memory dict.
    """
    global _shared_cache

    cache_key = f"resolver_ctx:{thread_id}"

    # ── Read from cache (shared or in-memory) ───────────────────────────────
    if _USE_SHARED_CACHE:
        if _shared_cache is None:
            from core.cache import PostgreSQLCache
            _shared_cache = PostgreSQLCache(ttl_seconds=settings.cache_ttl_seconds)
        cached = await _shared_cache.get(cache_key)
        if cached is not None:
            return cached
    else:
        if thread_id in _resolver_context_cache:
            return _resolver_context_cache[thread_id]

    # ── Cache miss — fetch from Odoo ────────────────────────────────────────
    try:
        from tools.ticket_tools import _port
        if _port is None:
            return ""
        # Direct async call — the adapter is now fully async (Fase 8).
        # No need for asyncio.to_thread() — the port is already on the event loop.
        tickets = await _port.get_tickets_by_assignee(user_id)
        if not tickets:
            result = "\n\n## Tickets asignados\nNo tienes tickets asignados."
        else:
            # Count SLA statuses
            sla_expired = sum(1 for t in tickets if t.get("sla_status") == "failed")
            sla_at_risk = sum(1 for t in tickets if t.get("is_about_to_expire"))
            pending_approval = sum(1 for t in tickets if t.get("approval_status") == "pending")

            lines = [
                "\n## Tickets asignados",
                f"Total: {len(tickets)} | "
                f"🔴 SLA vencido: {sla_expired} | "
                f"⚠️ SLA próximo: {sla_at_risk} | "
                f"📋 Pendiente aprobación: {pending_approval}",
                "",
            ]
            for t in tickets[:8]:
                cat = _extract_category_name(t)
                sla = t.get("sla_status", "-")
                sla_flag = "🔴" if sla == "failed" else "⚠️" if t.get("is_about_to_expire") else "  "
                # Extract human-readable priority (Odoo returns [id, "Name"])
                priority = t.get("priority_id")
                if isinstance(priority, list) and len(priority) >= 2:
                    priority = str(priority[1])
                elif isinstance(priority, str):
                    pass
                else:
                    priority = "?"
                lines.append(
                    f"{sla_flag} {t.get('name','N/A')} | {cat} | "
                    f"Prioridad: {priority} | "
                    f"Asunto: {t.get('asunto','N/A')[:60]}"
                )
            if len(tickets) > 8:
                lines.append(f"(+{len(tickets)-8} mas)")
            result = "\n".join(lines)
    except (psycopg.Error, ConnectionError, TimeoutError) as exc:
        # Pre-fetch is best-effort. If the backend or DB is unreachable,
        # we return an empty string and let the LLM proceed without context.
        _log.debug("Could not pre-fetch resolver tickets: %s", exc)
        result = ""

    # ── Write to cache (shared or in-memory) ───────────────────────────────
    if _USE_SHARED_CACHE:
        await _shared_cache.set(cache_key, result)
    else:
        # FIFO eviction
        if len(_resolver_context_cache) >= _RESOLVER_CONTEXT_CACHE_MAX:
            oldest = next(iter(_resolver_context_cache))
            del _resolver_context_cache[oldest]
        _resolver_context_cache[thread_id] = result

    return result


# ── Late imports (intentionally placed here, NOT at the top of the file) ─────
# These modules form a dependency graph with core/agent.py:
#   tools/* → ports/* → core/*
#   core/agent.py → tools/* (for get_creator_tools etc.)
#
# If we import them at the top, we get a circular dependency:
#   core/agent → tools/ticket_tools → core/agent (at import time)
#
# Python resolves this by deferring the imports until after the helper
# functions above are defined. By that point, the module-level setup in
# core/agent.py is complete and the circular chain breaks cleanly.
#
# DO NOT MOVE THESE TO THE TOP — it will break the import order.
from ports.ticket_port import ITicketPort
from ports.rag_port import IRAGPort
from core.graph import build_llm, build_checkpointer
from tools.ticket_tools import (
    set_ticket_port, set_rag_port_for_tickets,
    get_creator_tools, get_resolver_tools, get_supervisor_tools,
    create_ticket, get_my_created_tickets, get_my_assigned_tickets,
    get_ticket_detail, resolve_ticket, update_ticket,
    get_all_tickets, assign_ticket, reopen_ticket,
    approve_ticket, reject_ticket,
)
from tools.user_tools import (
    set_user_port, get_catalog_tools,
    get_ticket_types, get_categories, get_urgency_levels,
    get_impact_levels, get_priority_levels,
    get_resolvers, get_agent_groups, get_stages,
)
from tools.rag_tools import set_rag_port, get_rag_tools, suggest_solution
from prompts.creator import get_creator_prompt
from prompts.resolver import get_resolver_prompt
from prompts.supervisor import get_supervisor_prompt
from prompts.creator_executive import get_creator_executive_prompt
from prompts.resolver_executive import get_resolver_executive_prompt
from prompts.supervisor_executive import get_supervisor_executive_prompt


# ── Prompt registry ───────────────────────────────────────────────────────────

_PROMPT_BUILDERS = {
    "creador":    get_creator_prompt,
    "resueltor":  get_resolver_prompt,
    "supervisor": get_supervisor_prompt,
}

# Executive prompt registry: used when auto_confirm=True. These prompts are
# minimal versions that instruct the LLM to execute tools immediately without
# asking for clarification or confirmation. Designed for E2E tests and
# automation. The role-specific Q&A instructions are intentionally omitted
# because they block tool calls in automated flows.
_EXECUTIVE_PROMPT_BUILDERS = {
    "creador":    get_creator_executive_prompt,
    "resueltor":  get_resolver_executive_prompt,
    "supervisor": get_supervisor_executive_prompt,
}

_DEFAULT_PROMPT = (
    "Eres el asistente virtual de la mesa de ayuda. "
    "Por favor indica tu rol para poder ayudarte."
)


# ── Agent cache (shared across all API routes) ────────────────────────────────

_agent_cache: dict = {}


def get_or_create_agent(role: str, auto_confirm: bool = False):
    """
    Returns a compiled LangGraph ReAct agent for the given role.

    Two graph variants per role are cached:
    - {role}: auto_confirm=True  → tools execute immediately, no interruption.
      Used for E2E tests, automation, and programmatic flows.
    - {role}:interactive: auto_confirm=False → interrupt_before=["tools"].
      Used for the human chat UI: the graph pauses before tool execution and
      the caller (chat route) returns pending actions for user confirmation.

    Agents are cached at module level — one per (role, mode) pair, shared
    by all routes. Both /agent/chat and /agent/stream use the same instance
    for the same (role, auto_confirm) combination.
    """
    cache_key = f"{role}:auto" if auto_confirm else f"{role}:interactive"
    if cache_key not in _agent_cache:
        tools = get_tools_for_role(role)
        if not tools:
            raise ValueError(
                f"Unknown role '{role}'. Valid: creador, resueltor, supervisor"
            )
        # Interactive mode: pause before tool execution for human confirmation.
        # Auto mode: no pause, tools execute as soon as the LLM emits them.
        interrupt_before = None if auto_confirm else ["tools"]
        _agent_cache[cache_key] = create_agent(tools, interrupt_before=interrupt_before)
    return _agent_cache[cache_key]


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
    rag = get_rag_tools()

    if role == "creador":
        creator_catalog = [get_ticket_types, get_categories, get_urgency_levels,
                           get_impact_levels, get_priority_levels]
        return get_creator_tools() + creator_catalog + rag

    if role == "resueltor":
        return get_resolver_tools() + rag

    if role == "supervisor":
        supervisor_catalog = [get_resolvers, get_agent_groups, get_stages]
        return get_supervisor_tools() + supervisor_catalog + rag

    return []


# ── Agent creation ────────────────────────────────────────────────────────────

def create_agent(tools: list, interrupt_before: list = None):
    """
    Builds and compiles a LangGraph ReAct agent with the given tools.
    One agent per role is created and cached in _agent_cache.

    Args:
        tools: List of tools the agent can call.
        interrupt_before: Optional list of node names to pause before executing.
            Pass ["tools"] to implement human-in-the-loop confirmation: the graph
            will emit the AIMessage with tool_calls and pause, allowing the
            caller to confirm before the tools execute. Pass None (default)
            for a fully automated flow.

    pre_model_hook (_trim_hook):
    - Mantiene solo el SystemMessage más reciente (evita acumulación entre turnos).
    - Limita el historial a los últimos 8 mensajes no-sistema.
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
        4. Crecimiento ilimitado del contexto: limita a 8 mensajes no-sistema.
        """
        from langchain_core.messages import HumanMessage as _HM
        msgs = state["messages"]

        # Fix #5: keep only the MOST RECENT SystemMessage.
        # Each ainvoke/astream_events call appends a new SystemMessage to the checkpoint.
        # Collecting all of them inflates context on every turn — keep only the last.
        all_system = [m for m in msgs if isinstance(m, _SM)]
        system = [all_system[-1]] if all_system else []
        non_system = [m for m in msgs if not isinstance(m, _SM)]

        # Paso 1: corta a los últimos N mensajes (configurable via settings.chat_history_trim_limit)
        trim_limit = settings.chat_history_trim_limit
        window = non_system[-trim_limit:] if len(non_system) > trim_limit else non_system

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

        _log.debug("trim_hook: %d messages -> sending %d", len(non_system), len(sanitized))

        return {"messages": system + sanitized}

    llm = build_llm()
    checkpointer = build_checkpointer()
    tool_node = ToolNode(tools, handle_tool_errors=True)
    return create_react_agent(
        model=llm,
        tools=tool_node,
        checkpointer=checkpointer,
        pre_model_hook=_trim_hook,
        interrupt_before=interrupt_before,
    )


# ── Shared pre-flight logic ───────────────────────────────────────────────────

async def _prepare_invocation(
    agent,
    user_message: str,
    thread_id: str,
    user_id: int,
    user_role: str,
    auto_confirm: bool = False,
) -> tuple[dict, dict]:
    """
    Builds input_data and config for an agent invocation.

    Extracted to avoid duplicating this logic between get_response() and
    stream_response(). Both endpoints share exactly the same pre-flight:

    1. Build system prompt from role-specific builder (or executive variant).
    2. For creador: inject pre-fetched ticket context (cached per thread_id).
    3. Detect corrupted thread (orphaned tool_calls from a crashed Odoo session)
       and reset to a fresh thread_id if needed.

    Args:
        auto_confirm: When True, use the minimal executive prompt that tells
            the LLM to execute tools immediately without asking questions.
            Combined with the graph-level interrupt_before=False (handled by
            get_or_create_agent), this gives a fully automated E2E flow.

    Returns:
        (input_data, config) — ready to pass to ainvoke() or astream_events()
    """
    # Select the prompt builder based on mode. Executive prompts skip the
    # role-specific Q&A flow that would otherwise block tool calls.
    builders = _EXECUTIVE_PROMPT_BUILDERS if auto_confirm else _PROMPT_BUILDERS
    prompt_fn = builders.get(user_role)
    system_content = prompt_fn(user_id) if prompt_fn else _DEFAULT_PROMPT

    if user_role == "creador":
        tickets_ctx = await _fetch_creator_context(user_id, thread_id)
        if tickets_ctx:
            tickets_ctx = frame_external_data(tickets_ctx, "historial del usuario (Odoo)")
        system_content = system_content + tickets_ctx
    elif user_role == "resueltor":
        tickets_ctx = await _fetch_resolver_context(user_id, thread_id)
        if tickets_ctx:
            tickets_ctx = frame_external_data(tickets_ctx, "tickets asignados (Odoo)")
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
    except psycopg.Error as _state_err:
        # Checkpointer DB unreachable — proceed without orphan detection.
        # This is best-effort: the next successful get_state will catch it.
        _log.debug("Could not inspect thread state: %s", _state_err)

    input_data = {
        "messages": [
            SystemMessage(content=system_content),
            HumanMessage(content=user_message),
        ]
    }

    return input_data, config


# ── LLM usage tracking (Phase 3) ─────────────────────────────────────────────
# Token counts, latency, and cost are captured by intercepting ainvoke() and
# astream_events() and reading response_metadata.usage from the last AIMessage.
# Cost is calculated from a model-to-price map; unknown models fall back to $0.

# Cost per million tokens. Extend as new models are added.
# Source: OpenCode Go pricing (https://opencode.ai/docs) — May 2026
_LLM_PRICING = {
    # OpenCode Go — DeepSeek V4 Pro
    "deepseek-v4-pro":  {"input": 1.74, "output": 3.48},
    "deepseek-v4-flash": {"input": 0.14, "output": 0.28},
    # Groq fallback
    "llama-4-scout":    {"input": 0.11, "output": 0.34},
    # OpenRouter free models — $0
    "nemotron-3-super": {"input": 0.0,  "output": 0.0},
    "gemma-4-31b":      {"input": 0.0,  "output": 0.0},
    "gemma-4-26b":      {"input": 0.0,  "output": 0.0},
}


def _calc_cost(model: str, tokens_in: int, tokens_out: int) -> float:
    """Returns USD cost for a call. Unknown models → $0 (not free, just unmapped)."""
    model_lc = (model or "").lower()
    for key, rates in _LLM_PRICING.items():
        if key in model_lc:
            return (tokens_in * rates["input"] + tokens_out * rates["output"]) / 1_000_000
    return 0.0


def _extract_usage(result: dict) -> tuple[int, int]:
    """
    Reads token counts from the last AIMessage in the agent result.
    LangChain standardises usage under response_metadata.usage_metadata or .usage.
    Returns (tokens_input, tokens_output). Defaults to (0, 0) on any error.
    """
    try:
        msgs = result.get("messages", []) if isinstance(result, dict) else []
        if not msgs:
            return 0, 0
        last = msgs[-1]
        meta = getattr(last, "response_metadata", None) or {}
        # LangChain ≥0.2 puts usage in .usage_metadata (token_usage.TypedDict)
        usage = meta.get("usage") or meta.get("token_usage") or {}
        if not usage:
            # Some providers nest under .usage_metadata directly on the message
            usage = getattr(last, "usage_metadata", None) or {}
        tokens_in = (
            usage.get("input_tokens")
            or usage.get("prompt_tokens")
            or 0
        )
        tokens_out = (
            usage.get("output_tokens")
            or usage.get("completion_tokens")
            or 0
        )
        return int(tokens_in), int(tokens_out)
    except (AttributeError, TypeError, KeyError, ValueError):
        # Metadata format varies across LLM providers. Return zeros
        # so the caller can proceed without token tracking.
        return 0, 0


def _fallback_was_used() -> bool:
    """
    Returns True if the last LLM call went through a fallback.
    The primary LLM chain is built with .with_fallbacks() — this flag is set
    by the request middleware (api/middleware/request_context.py) when the
    primary provider raises and the fallback path is taken.
    For now we return False — full fallback detection requires instrumenting
    the .with_fallbacks() wrapper, which is a follow-up. Cost data is still
    accurate because we record the model that actually responded.
    """
    return False


# ── Response extraction ───────────────────────────────────────────────────────


def _describe_action(tool_name: str, args: dict) -> str:
    """
    Generate a brief human-readable description of a tool call for the UI.

    The description is shown in the confirmation prompt so the user
    understands what the agent wants to do before confirming or rejecting.
    """
    ticket_id = args.get("ticket_id", "?")
    asunto = str(args.get("asunto", ""))[:50]
    category = str(args.get("category_id", "?"))

    if tool_name == "create_ticket":
        label = f"Crear ticket: {asunto}" if asunto else f"Crear ticket #{ticket_id}"
        if category != "?":
            label += f" (categoría: {category})"
        return label
    if tool_name == "assign_ticket":
        return f"Asignar ticket #{ticket_id} al agente #{args.get('assignee_id', '?')}"
    if tool_name == "resolve_ticket":
        return f"Resolver ticket #{ticket_id}"
    if tool_name == "approve_ticket":
        return f"Aprobar ticket #{ticket_id}"
    if tool_name == "reject_ticket":
        return f"Rechazar ticket #{ticket_id}"
    if tool_name == "reopen_ticket":
        return f"Reabrir ticket #{ticket_id}"
    if tool_name == "update_ticket":
        fields = ", ".join(list(args.get("fields", {}).keys())[:3])
        desc = f"Actualizar ticket #{ticket_id}"
        return f"{desc} ({fields})" if fields else desc
    if tool_name == "suggest_solution":
        desc_text = str(args.get("description", ""))[:60]
        return f"Buscar soluciones para: {desc_text}" if desc_text else "Buscar soluciones en la base de conocimiento"
    if tool_name == "get_ticket_detail":
        return f"Ver detalle del ticket #{ticket_id}"
    if tool_name == "get_ticket_types":
        return "Consultar tipos de tickets disponibles"
    if tool_name == "get_categories":
        return "Consultar categorías disponibles"
    if tool_name == "get_urgency_levels":
        return "Consultar niveles de urgencia"
    if tool_name == "get_impact_levels":
        return "Consultar niveles de impacto"
    if tool_name == "get_priority_levels":
        return "Consultar niveles de prioridad"
    if tool_name == "get_resolvers":
        return "Consultar agentes disponibles"
    if tool_name == "get_agent_groups":
        return "Consultar grupos de agentes"
    if tool_name == "get_stages":
        return "Consultar etapas de tickets"
    if tool_name == "get_my_created_tickets":
        return "Consultar mis tickets creados"
    if tool_name == "get_my_assigned_tickets":
        return "Consultar tickets asignados a mí"
    if tool_name == "get_all_tickets":
        return "Consultar todos los tickets del sistema"
    return f"Ejecutar {tool_name}"


def _extract_pending_actions(result: dict) -> list[dict]:
    """
    Extract pending tool calls from the last AIMessage in the agent result.

    When the graph is interrupted before the tools node, the last message
    is an AIMessage with tool_calls but no corresponding ToolMessages.
    This helper reads those tool_calls and builds the pending_actions list
    expected by the API schema.

    Returns an empty list if there are no pending tool calls.
    """
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            actions = []
            for tc in msg.tool_calls:
                actions.append({
                    "tool_call_id": tc["id"],
                    "tool_name": tc["name"],
                    "arguments": tc.get("args", {}),
                    "description": _describe_action(tc["name"], tc.get("args", {})),
                })
            return actions
    return []


def _extract_pending_actions_from_state(state) -> list[dict]:
    """
    Extract pending tool calls from a LangGraph StateSnapshot.

    Used in the streaming path where we don't have a result dict —
    instead we query the checkpointer directly via agent.aget_state().
    """
    messages = state.values.get("messages", []) if state.values else []
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            actions = []
            for tc in msg.tool_calls:
                actions.append({
                    "tool_call_id": tc["id"],
                    "tool_name": tc["name"],
                    "arguments": tc.get("args", {}),
                    "description": _describe_action(tc["name"], tc.get("args", {})),
                })
            return actions
    return []


def _pending_reply_text(result: dict, pending: list) -> str:
    """
    Return a human-readable reply when the graph is awaiting confirmation.

    If the LLM provided text content in its tool-call message (e.g.
    "Voy a crear un ticket de VPN, ¿confirmás?"), use that. Otherwise
    generate a sensible default from the pending actions.
    """
    for msg in reversed(result.get("messages", [])):
        if isinstance(msg, AIMessage) and getattr(msg, "tool_calls", None):
            if msg.content:
                return msg.content
    # Fallback — LLM didn't provide text with its tool calls
    if len(pending) == 1:
        return f"Necesito tu confirmación para: {pending[0]['description']}"
    return f"Necesito tu confirmación para {len(pending)} acciones."


async def get_response(
    agent,
    user_message: str,
    thread_id: str,
    user_id: int,
    user_role: str,
    auto_confirm: bool = False,
) -> dict:
    """
    Invokes the agent and returns a structured reply.

    Returns a dict with keys:
        reply: str           — The text response for the user
        status: str          — "ok" or "pending_actions"
        pending_actions: list — Empty on "ok", populated when graph is interrupted

    When auto_confirm=False and the graph is compiled with interrupt_before=["tools"],
    the LLM may emit tool_calls that are paused before execution. This function
    detects that state and returns status="pending_actions" so the caller can
    display confirmation UI.

    Uses ainvoke() — compatible with AsyncSqliteSaver which is required
    for the streaming endpoint. The /agent/chat route must be async too.

    Args:
        auto_confirm: When True, the agent executes tools immediately without
            asking for confirmation. See _prepare_invocation() for details.
    """
    input_data, config = await _prepare_invocation(
        agent, user_message, thread_id, user_id, user_role, auto_confirm,
    )

    from core.context import current_user_id as _uid_var
    _uid_var.set(user_id)

    sem = _get_llm_semaphore()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=settings.llm_semaphore_timeout)
    except asyncio.TimeoutError:
        _log.warning(
            "llm_semaphore_timeout",
            extra={"timeout": settings.llm_semaphore_timeout, "thread_id": thread_id})
        return {
            "reply": (
                "El sistema está procesando muchas solicitudes en este momento. "
                "Por favor intenta de nuevo en unos segundos."
            ),
            "status": "ok",
            "pending_actions": [],
        }

    # ── LLM usage tracking (Phase 3) ──────────────────────────────────────
    import time as _time
    from feedback.collector import FeedbackCollector
    _llm_started = _time.perf_counter()
    _llm_collector = FeedbackCollector()
    provider = settings.llm_provider
    model = (
        settings.ai_gateway_model
        if provider == "vercel"
        else settings.llm_model
    )
    result = None
    _llm_error = ""

    try:
        _log.info("LLM call started user=%s thread=%s", user_id, thread_id)
        result = await agent.ainvoke(input_data, config=config)
        # Record success in circuit breaker for the active provider.
        # This makes /agent/llm-status show real success/failure stats.
        from core.circuit_breaker import get_provider_status
        provider_status = get_provider_status(model)
        provider_status.record_success()
    except (TimeoutError, ConnectionError, RuntimeError, ValueError) as e:
        # LLM calls can fail for many provider-specific reasons (rate limit,
        # auth, schema rejection, tool-call parse error). These are the
        # most common — anything else propagates so we can fix it.
        _llm_error = repr(e)
        _log.error("LLM call failed user=%s thread=%s error=%s", user_id, thread_id, e, exc_info=True)
        # Record failure in circuit breaker for the active provider.
        # After 3 consecutive failures the circuit opens, /agent/llm-status
        # shows the state, and the operator can see the provider is degraded.
        from core.circuit_breaker import get_provider_status
        provider_status = get_provider_status(model)
        provider_status.record_failure()
        # Record failure for cost/latency tracking
        _llm_collector.record_llm_usage(
            thread_id=thread_id,
            user_id=user_id,
            user_role=user_role,
            provider_used=provider,
            model_used=model,
            tokens_input=0,
            tokens_output=0,
            latency_ms=(_time.perf_counter() - _llm_started) * 1000,
            fallback_triggered=False,
            cost_usd=0.0,
            error=_llm_error,
        )
        raise
    finally:
        sem.release()

    # ── Record success metrics ────────────────────────────────────────────
    elapsed_ms = (_time.perf_counter() - _llm_started) * 1000
    tokens_in, tokens_out = _extract_usage(result)
    cost = _calc_cost(model, tokens_in, tokens_out)
    _llm_collector.record_llm_usage(
        thread_id=thread_id,
        user_id=user_id,
        user_role=user_role,
        provider_used=provider,
        model_used=model,
        tokens_input=tokens_in,
        tokens_output=tokens_out,
        latency_ms=elapsed_ms,
        fallback_triggered=_fallback_was_used(),
        cost_usd=cost,
        error="",
    )
    _log.info(
        "LLM call complete user=%s thread=%s tokens_in=%d tokens_out=%d cost=%.6f latency=%.0fms",
        user_id, thread_id, tokens_in, tokens_out, cost, elapsed_ms,
    )

    # ── Detect graph interruption (human-in-the-loop) ──────────────────────
    # When interrupt_before=["tools"] is active, LangGraph pauses after the
    # LLM emits tool_calls but before the tools node executes.
    # state.next is non-empty when the graph is waiting for a human to resume it.
    graph_interrupted = False
    try:
        state = await agent.aget_state(config)
        if state.next:
            graph_interrupted = True
    except (psycopg.Error, ConnectionError, TimeoutError, RuntimeError) as _state_err:
        # Best-effort: if the checkpointer is unreachable, fall through to
        # the normal text-response path. The caller will see an empty reply
        # instead of pending_actions, which is the safe degraded state.
        _log.debug("Could not check graph state for interruption: %s", _state_err)

    if graph_interrupted:
        pending = _extract_pending_actions(result)
        reply = _pending_reply_text(result, pending)
        _log.info(
            "Graph interrupted user=%s thread=%s pending=%d",
            user_id, thread_id, len(pending),
        )
        return {"reply": reply, "status": "pending_actions", "pending_actions": pending}

    # ── Invalidate creator context cache when create_ticket succeeds ──────
    # So the next message reflects the newly created ticket in the user's history.
    if user_role == "creador":
        from langchain_core.messages import ToolMessage as _TMsg
        import json as _json
        for msg in result.get("messages", []):
            if isinstance(msg, _TMsg) and getattr(msg, "name", None) == "create_ticket":
                try:
                    payload = _json.loads(msg.content) if isinstance(msg.content, str) else msg.content
                    if isinstance(payload, dict) and payload.get("success"):
                        invalidate_creator_context(thread_id)
                except (json.JSONDecodeError, TypeError, AttributeError):
                    # Tool returned non-JSON or unexpected format — skip
                    # cache invalidation. The next call will re-fetch.
                    pass
                break

    # ── Normal path: find the last AIMessage with text content ────────────
    for msg in reversed(result.get("messages", [])):
        if (
            isinstance(msg, AIMessage)
            and msg.content
            and not getattr(msg, "tool_calls", None)
        ):
            # Security Capa 5: redact PII in LLM output before returning
            from core.pii_redaction import redact_pii
            redacted, redaction_count = redact_pii(msg.content)
            if redaction_count > 0:
                _log.info(
                    "pii_redacted user=%s thread=%s count=%d",
                    user_id, thread_id, redaction_count,
                )
            return {"reply": redacted, "status": "ok", "pending_actions": []}

    return {
        "reply": (
            "No pude procesar tu solicitud en este momento. "
            "Por favor intenta de nuevo."
        ),
        "status": "ok",
        "pending_actions": [],
    }


# ── Graph resume (human-in-the-loop confirmation) ────────────────────────────


def _build_tool_registry() -> dict:
    """
    Lazy-built mapping of tool_name → async callable.

    Used by ``_execute_tool_by_name()`` for granular confirmation where
    we need to manually execute individual tools instead of letting the
    graph's ToolNode run them all.

    Built lazily (not at import time) to avoid circular dependency issues
    with tools/* modules that import from core/*.
    """
    registry = {
        # Creator tools (ticket_tools)
        "create_ticket":          create_ticket,
        "get_my_created_tickets": get_my_created_tickets,
        # Resolver tools (ticket_tools)
        "get_my_assigned_tickets": get_my_assigned_tickets,
        "resolve_ticket":         resolve_ticket,
        # Shared ticket tools
        "get_ticket_detail":      get_ticket_detail,
        "update_ticket":          update_ticket,
        # Supervisor tools (ticket_tools)
        "get_all_tickets":        get_all_tickets,
        "assign_ticket":          assign_ticket,
        "reopen_ticket":          reopen_ticket,
        "approve_ticket":         approve_ticket,
        "reject_ticket":          reject_ticket,
        # Catalog tools (user_tools)
        "get_ticket_types":       get_ticket_types,
        "get_categories":         get_categories,
        "get_urgency_levels":     get_urgency_levels,
        "get_impact_levels":      get_impact_levels,
        "get_priority_levels":    get_priority_levels,
        "get_resolvers":          get_resolvers,
        "get_agent_groups":       get_agent_groups,
        "get_stages":             get_stages,
        # RAG tools
        "suggest_solution":       suggest_solution,
    }
    return registry


async def _execute_tool_by_name(tool_name: str, args: dict) -> dict:
    """
    Execute a single tool by name and return its result.

    Used by ``resume_agent()`` for granular confirmation: when only a
    subset of tool calls are confirmed, we execute those manually and
    send their results as ToolMessages to the graph.

    Returns:
        dict: The tool's return value (usually {"success": bool, ...}).

    Raises:
        ValueError: If the tool name is unknown.
    """
    registry = _build_tool_registry()
    tool_fn = registry.get(tool_name)
    if tool_fn is None:
        raise ValueError(
            f"Unknown tool '{tool_name}' — cannot execute for granular "
            f"confirmation. Known tools: {list(registry.keys())}"
        )
    # All tool functions are async; call them directly in the event loop.
    return await tool_fn(**args)


async def resume_agent(agent, thread_id: str, user_id: int, confirm_action_ids: list = None) -> dict:
    """
    Resume a graph that was interrupted at the tools node.

    When the agent is compiled with ``interrupt_before=["tools"]`` and the
    LLM emits tool_calls, the graph pauses. The user confirms the actions
    and this function re-enters the graph so the tools execute and the LLM
    generates the final response.

    After resume, the graph may complete (status="ok") or interrupt AGAIN
    (status="pending_actions") if the LLM emits more tool_calls that also
    need confirmation.

    Returns the same dict shape as :func:`get_response`::
        {"reply": str, "status": str, "pending_actions": list}

    Raises:
        RuntimeError: If the graph is not in an interrupted state.

    Args:
        agent: The compiled LangGraph agent.
        thread_id: The conversation thread to resume (must match the
            thread that was interrupted).
        user_id: The authenticated user (required for context injection
            inside tools like create_ticket).
    """
    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 30}

    # ── Verify the graph is actually interrupted ───────────────────────────
    try:
        state = await agent.aget_state(config)
    except (psycopg.Error, ConnectionError, TimeoutError) as _state_err:
        raise RuntimeError(
            f"No se pudo verificar el estado del thread {thread_id}: {_state_err}"
        ) from _state_err

    if not state.next:
        raise RuntimeError(
            f"Thread {thread_id} no está esperando confirmación — "
            "nada que confirmar."
        )

    # ── Inject user_id into context for tool authorisation ─────────────────
    from core.context import current_user_id as _uid_var
    _uid_var.set(user_id)

    # ── Semaphore (same rate-limiting as get_response) ─────────────────────
    sem = _get_llm_semaphore()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=settings.llm_semaphore_timeout)
    except asyncio.TimeoutError:
        return {
            "reply": "El sistema está muy ocupado. Intenta confirmar en unos segundos.",
            "status": "ok",
            "pending_actions": [],
        }

    # ── LLM usage tracking ────────────────────────────────────────────────
    import time as _time
    from feedback.collector import FeedbackCollector
    _llm_started = _time.perf_counter()
    _llm_collector = FeedbackCollector()
    provider = settings.llm_provider
    model = (
        settings.ai_gateway_model
        if provider == "vercel"
        else settings.llm_model
    )
    result = None

    try:
        _log.info("Graph resume started user=%s thread=%s", user_id, thread_id)

        if confirm_action_ids is not None and len(confirm_action_ids) > 0:
            # ── Granular confirmation ────────────────────────────────────
            # User confirmed only a subset of pending tool calls.
            # Execute confirmed tools manually and send results + rejections
            # as ToolMessages so LangGraph doesn't run the ToolNode.
            from langchain_core.messages import ToolMessage as _TMsg

            all_pending = _extract_pending_actions_from_state(state)
            confirm_set = set(confirm_action_ids)

            tool_messages = []
            for action in all_pending:
                if action["tool_call_id"] in confirm_set:
                    # Execute the tool manually and wrap result
                    try:
                        tool_result = await _execute_tool_by_name(
                            action["tool_name"], action["arguments"],
                        )
                    except Exception as _exec_err:
                        tool_result = {
                            "success": False,
                            "error": f"Error ejecutando tool: {_exec_err}",
                        }
                    tool_messages.append(_TMsg(
                        content=json.dumps(tool_result),
                        tool_call_id=action["tool_call_id"],
                        name=action["tool_name"],
                    ))
                    _log.debug(
                        "Granular confirm: executed %s for thread=%s",
                        action["tool_name"], thread_id,
                    )
                else:
                    # Reject non-confirmed tool calls
                    tool_messages.append(_TMsg(
                        content=json.dumps({
                            "rejected": True,
                            "reason": "El usuario no confirmó esta acción",
                        }),
                        tool_call_id=action["tool_call_id"],
                        name=action["tool_name"],
                    ))
                    _log.debug(
                        "Granular confirm: rejected %s for thread=%s",
                        action["tool_name"], thread_id,
                    )

            _log.info(
                "Granular confirm user=%s thread=%s confirmed=%d/%d",
                user_id, thread_id,
                len(confirm_set), len(all_pending),
            )

            # Send ToolMessages as input — LangGraph uses them as
            # pre-computed tool results instead of executing the ToolNode.
            result = await agent.ainvoke({"messages": tool_messages}, config=config)
        else:
            # ── Full confirmation (current behaviour) ───────────────────
            # Passing None tells LangGraph to continue from the checkpoint
            # and execute all pending tools via the ToolNode.
            result = await agent.ainvoke(None, config=config)

        from core.circuit_breaker import get_provider_status
        provider_status = get_provider_status(model)
        provider_status.record_success()
    except (TimeoutError, ConnectionError, RuntimeError, ValueError) as e:
        _llm_error = repr(e)
        _log.error("Graph resume failed user=%s thread=%s error=%s", user_id, thread_id, e, exc_info=True)
        from core.circuit_breaker import get_provider_status
        provider_status = get_provider_status(model)
        provider_status.record_failure()
        _llm_collector.record_llm_usage(
            thread_id=thread_id,
            user_id=user_id,
            user_role="",
            provider_used=provider,
            model_used=model,
            tokens_input=0,
            tokens_output=0,
            latency_ms=(_time.perf_counter() - _llm_started) * 1000,
            fallback_triggered=False,
            cost_usd=0.0,
            error=_llm_error,
        )
        raise
    finally:
        sem.release()

    # ── Record success metrics ────────────────────────────────────────────
    elapsed_ms = (_time.perf_counter() - _llm_started) * 1000
    tokens_in, tokens_out = _extract_usage(result)
    cost = _calc_cost(model, tokens_in, tokens_out)
    _llm_collector.record_llm_usage(
        thread_id=thread_id,
        user_id=user_id,
        user_role="",
        provider_used=provider,
        model_used=model,
        tokens_input=tokens_in,
        tokens_output=tokens_out,
        latency_ms=elapsed_ms,
        fallback_triggered=_fallback_was_used(),
        cost_usd=cost,
        error="",
    )
    _log.info(
        "Graph resume complete user=%s thread=%s tokens_in=%d tokens_out=%d latency=%.0fms",
        user_id, thread_id, tokens_in, tokens_out, elapsed_ms,
    )

    # ── After resume: check if graph is interrupted AGAIN ─────────────────
    # The LLM may have emitted more tool_calls that also need confirmation.
    # This is the recursive case: confirm → tools execute → LLM emits more
    # tool_calls → graph interrupts again.
    try:
        state = await agent.aget_state(config)
        if state.next:
            pending = _extract_pending_actions(result)
            reply = _pending_reply_text(result, pending)
            _log.info(
                "Graph interrupted again user=%s thread=%s pending=%d",
                user_id, thread_id, len(pending),
            )
            return {"reply": reply, "status": "pending_actions", "pending_actions": pending}
    except Exception:
        pass  # Best-effort; fall through to final text

    # ── Final text response ───────────────────────────────────────────────
    for msg in reversed(result.get("messages", [])):
        if (
            isinstance(msg, AIMessage)
            and msg.content
            and not getattr(msg, "tool_calls", None)
        ):
            from core.pii_redaction import redact_pii
            redacted, _ = redact_pii(msg.content)
            return {"reply": redacted, "status": "ok", "pending_actions": []}

    return {"reply": "Acción completada.", "status": "ok", "pending_actions": []}


# ── Graph reject (human-in-the-loop cancellation) ─────────────────────────────


async def reject_agent(agent, thread_id: str, user_id: int, reason: str = "") -> dict:
    """
    Reject all pending tool calls for an interrupted graph.

    Instead of executing the tools, this sends ToolMessages with rejection
    content. LangGraph treats these as pre-computed tool results and feeds
    them to the LLM, which can then respond to the user appropriately
    (e.g. *"Entendido, cancelé la operación. ¿En qué más puedo ayudarte?"*).

    Returns the same dict shape as :func:`get_response`::
        {"reply": str, "status": str, "pending_actions": list}

    Raises:
        RuntimeError: If the graph is not in an interrupted state or has
            no pending tool calls.

    Args:
        agent: The compiled LangGraph agent.
        thread_id: The conversation thread to reject.
        user_id: The authenticated user.
        reason: Optional human-readable rejection reason (for logging).
    """
    from langchain_core.messages import ToolMessage

    config = {"configurable": {"thread_id": thread_id}, "recursion_limit": 30}

    # ── Verify the graph is actually interrupted ───────────────────────────
    try:
        state = await agent.aget_state(config)
    except (psycopg.Error, ConnectionError, TimeoutError) as _state_err:
        raise RuntimeError(
            f"No se pudo verificar el estado del thread {thread_id}: {_state_err}"
        ) from _state_err

    if not state.next:
        raise RuntimeError(
            f"Thread {thread_id} no está esperando confirmación — "
            "nada que rechazar."
        )

    # ── Extract pending tool calls ─────────────────────────────────────────
    pending = _extract_pending_actions_from_state(state)
    if not pending:
        raise RuntimeError(
            f"Thread {thread_id} está interrumpido pero no tiene "
            "acciones pendientes para rechazar."
        )

    _log.info(
        "Graph reject started user=%s thread=%s pending=%d reason=%s",
        user_id, thread_id, len(pending), reason or "(none)",
    )

    # ── Inject user_id into context ────────────────────────────────────────
    from core.context import current_user_id as _uid_var
    _uid_var.set(user_id)

    # ── Build rejection ToolMessages ───────────────────────────────────────
    # Each ToolMessage matches a pending tool_call_id, so LangGraph
    # routes it as a pre-computed result instead of executing the tool.
    rejection_content = {"rejected": True}
    if reason:
        rejection_content["reason"] = reason
    rejection_messages = [
        ToolMessage(
            content=json.dumps(rejection_content),
            tool_call_id=action["tool_call_id"],
            name=action["tool_name"],
        )
        for action in pending
    ]

    # ── Semaphore ──────────────────────────────────────────────────────────
    sem = _get_llm_semaphore()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=settings.llm_semaphore_timeout)
    except asyncio.TimeoutError:
        return {
            "reply": "El sistema está muy ocupado. Intenta rechazar en unos segundos.",
            "status": "ok",
            "pending_actions": [],
        }

    # ── LLM usage tracking ────────────────────────────────────────────────
    import time as _time
    from feedback.collector import FeedbackCollector
    _llm_started = _time.perf_counter()
    _llm_collector = FeedbackCollector()
    provider = settings.llm_provider
    model = (
        settings.ai_gateway_model
        if provider == "vercel"
        else settings.llm_model
    )
    result = None

    try:
        _log.info("LLM reject call started user=%s thread=%s", user_id, thread_id)
        # Send rejection ToolMessages as input — LangGraph won't execute
        # the tools, it will feed these results to the LLM directly.
        result = await agent.ainvoke({"messages": rejection_messages}, config=config)
        from core.circuit_breaker import get_provider_status
        provider_status = get_provider_status(model)
        provider_status.record_success()
    except (TimeoutError, ConnectionError, RuntimeError, ValueError) as e:
        _llm_error = repr(e)
        _log.error("LLM reject failed user=%s thread=%s error=%s", user_id, thread_id, e, exc_info=True)
        from core.circuit_breaker import get_provider_status
        provider_status = get_provider_status(model)
        provider_status.record_failure()
        _llm_collector.record_llm_usage(
            thread_id=thread_id,
            user_id=user_id,
            user_role="",
            provider_used=provider,
            model_used=model,
            tokens_input=0,
            tokens_output=0,
            latency_ms=(_time.perf_counter() - _llm_started) * 1000,
            fallback_triggered=False,
            cost_usd=0.0,
            error=_llm_error,
        )
        raise
    finally:
        sem.release()

    # ── Record success metrics ────────────────────────────────────────────
    elapsed_ms = (_time.perf_counter() - _llm_started) * 1000
    tokens_in, tokens_out = _extract_usage(result)
    cost = _calc_cost(model, tokens_in, tokens_out)
    _llm_collector.record_llm_usage(
        thread_id=thread_id,
        user_id=user_id,
        user_role="",
        provider_used=provider,
        model_used=model,
        tokens_input=tokens_in,
        tokens_output=tokens_out,
        latency_ms=elapsed_ms,
        fallback_triggered=_fallback_was_used(),
        cost_usd=cost,
        error="",
    )
    _log.info(
        "Graph reject complete user=%s thread=%s tokens_in=%d tokens_out=%d latency=%.0fms",
        user_id, thread_id, tokens_in, tokens_out, elapsed_ms,
    )

    # ── Final text response (rejection → LLM should respond, not tool call) ──
    for msg in reversed(result.get("messages", [])):
        if (
            isinstance(msg, AIMessage)
            and msg.content
            and not getattr(msg, "tool_calls", None)
        ):
            from core.pii_redaction import redact_pii
            redacted, _ = redact_pii(msg.content)
            return {"reply": redacted, "status": "ok", "pending_actions": []}

    return {"reply": "Acciones rechazadas. ¿En qué más puedo ayudarte?", "status": "ok", "pending_actions": []}


# ── Streaming response ────────────────────────────────────────────────────────

async def stream_response(
    agent,
    user_message: str,
    thread_id: str,
    user_id: int,
    user_role: str,
    auto_confirm: bool = False,
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

    Args:
        auto_confirm: When True, the agent executes tools immediately without
            asking for confirmation.
    """
    input_data, config = await _prepare_invocation(
        agent, user_message, thread_id, user_id, user_role, auto_confirm,
    )

    from core.context import current_user_id as _uid_var
    _uid_var.set(user_id)

    sem = _get_llm_semaphore()
    try:
        await asyncio.wait_for(sem.acquire(), timeout=settings.llm_semaphore_timeout)
    except asyncio.TimeoutError:
        _log.warning(
            "llm_semaphore_timeout",
            extra={"timeout": settings.llm_semaphore_timeout, "thread_id": thread_id})
        yield f"data: {json.dumps({'t': 'token', 'v': 'El sistema está muy ocupado. Intenta de nuevo en unos segundos.'})}\n\n"
        yield f"data: {json.dumps({'t': 'done'})}\n\n"
        return

    # ── LLM usage tracking (Phase 3) ──────────────────────────────────────
    import time as _time
    from feedback.collector import FeedbackCollector
    _llm_started = _time.perf_counter()
    _llm_collector = FeedbackCollector()
    provider = settings.llm_provider
    model = (
        settings.ai_gateway_model
        if provider == "vercel"
        else settings.llm_model
    )
    _stream_error = ""
    # We accumulate the final AIMessage from the last 'on_chat_model_end' event
    # to extract usage_metadata — the streaming path doesn't return a result dict.
    _stream_last_ai_msg = None

    try:
        _log.info("LLM stream started user=%s thread=%s", user_id, thread_id)
        async for event in agent.astream_events(input_data, config, version="v2"):
            kind = event["event"]

            # ── Text token from LLM ──────────────────────────────────────────
            if kind == "on_chat_model_stream":
                chunk = event["data"]["chunk"]
                # Skip tool_call_chunks — only stream final text tokens
                if chunk.content and not getattr(chunk, "tool_call_chunks", None):
                    # Security Capa 5: best-effort PII redaction per chunk.
                    # Note: streaming means PII may be split across chunks
                    # (e.g. "user@" then "example.com"). The complete redaction
                    # happens in get_response() for the non-streaming endpoint.
                    from core.pii_redaction import redact_pii
                    redacted, _ = redact_pii(chunk.content)
                    yield f"data: {json.dumps({'t': 'token', 'v': redacted})}\n\n"

            # ── Tool execution started — send UX hint ────────────────────────
            elif kind == "on_tool_start":
                tool_name = event.get("name", "tool")
                yield f"data: {json.dumps({'t': 'tool', 'v': tool_name})}\n\n"

            # ── Tool finished — invalidate creator cache on create_ticket ────
            elif kind == "on_tool_end" and user_role == "creador":
                if event.get("name") == "create_ticket":
                    try:
                        output = event.get("data", {}).get("output")
                        if isinstance(output, str):
                            output = json.loads(output)
                        if isinstance(output, dict) and output.get("success"):
                            invalidate_creator_context(thread_id)
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        # Tool returned non-JSON or unexpected format — skip
                        # cache invalidation. The next call will re-fetch.
                        pass

            # ── LLM finished — capture the final AIMessage for usage ────────
            elif kind == "on_chat_model_end":
                output = event.get("data", {}).get("output")
                if output is not None:
                    _stream_last_ai_msg = output

        # ── After stream: detect graph interruption ────────────────────────
        # When interrupt_before=["tools"] pauses the graph, astream_events
        # yields the LLM's text/tool_call_chunks but never reaches
        # on_tool_start. We detect the paused state and emit pending_actions
        # so the client can render a confirmation UI.
        try:
            state = await agent.aget_state(config)
            if state.next:
                pending = _extract_pending_actions_from_state(state)
                if pending:
                    _log.info(
                        "Stream interrupted user=%s thread=%s pending=%d",
                        user_id, thread_id, len(pending),
                    )
                    yield f"data: {json.dumps({'t': 'pending_actions', 'v': pending})}\n\n"
        except (psycopg.Error, ConnectionError, TimeoutError, RuntimeError) as _state_err:
            _log.debug("Could not check stream interruption: %s", _state_err)

        yield f"data: {json.dumps({'t': 'done'})}\n\n"

    except Exception as exc:
        # Stream generator boundary: catch ALL exceptions and emit them as
        # SSE error events so the client can render a graceful error message
        # instead of seeing a broken stream. This is the right place to
        # catch broadly — we are the API edge.
        _stream_error = repr(exc)
        _log.exception("stream_response error thread=%s user=%s", thread_id, user_id)
        yield f"data: {json.dumps({'t': 'error', 'v': str(exc)})}\n\n"
    finally:
        sem.release()
        # ── Record LLM usage (Phase 3) ─────────────────────────────────────
        # The streaming path doesn't return a result dict — we build one
        # from the last AIMessage we captured in on_chat_model_end.
        elapsed_ms = (_time.perf_counter() - _llm_started) * 1000
        if _stream_last_ai_msg is not None:
            fake_result = {"messages": [_stream_last_ai_msg]}
            tokens_in, tokens_out = _extract_usage(fake_result)
        else:
            tokens_in, tokens_out = 0, 0
        cost = _calc_cost(model, tokens_in, tokens_out)
        _llm_collector.record_llm_usage(
            thread_id=thread_id,
            user_id=user_id,
            user_role=user_role,
            provider_used=provider,
            model_used=model,
            tokens_input=tokens_in,
            tokens_output=tokens_out,
            latency_ms=elapsed_ms,
            fallback_triggered=_fallback_was_used(),
            cost_usd=cost,
            error=_stream_error,
        )
        _log.debug("LLM stream finished user=%s thread=%s", user_id, thread_id)
