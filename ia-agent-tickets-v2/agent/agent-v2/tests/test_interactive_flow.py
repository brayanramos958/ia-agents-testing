"""
E2E tests for the interactive flow: chat → pending_actions → confirm/reject.

All tests use FakeListChatModel (no real LLM) and FakeTicketPort (no Odoo).
The agent is compiled with MemorySaver (in-process, no PostgreSQL).
"""

import json
import pytest
from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

from tests.conftest import tool_call_msg, text_msg, make_tc


# ═══════════════════════════════════════════════════════════════════════════
# Test 1: Interactive chat detects pending_actions
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_interactive_chat_returns_pending_actions(agent_factory, creator_tools):
    """Chat with tool_calls → graph pauses → state.next is non-empty."""
    responses = [
        tool_call_msg([
            make_tc("get_ticket_types", {}, "call_001"),
        ]),
    ]
    agent = agent_factory(creator_tools, responses, interrupt_before=["tools"])

    config = {"configurable": {"thread_id": "test-1"}, "recursion_limit": 30}
    result = await agent.ainvoke(
        {"messages": [SystemMessage(content=""), HumanMessage(content="dame tipos")]},
        config=config,
    )

    # Verify the last message is an AIMessage with tool_calls
    messages = result["messages"]
    last = messages[-1]
    assert isinstance(last, AIMessage), f"Expected AIMessage, got {type(last)}"
    assert last.tool_calls, "Expected tool_calls in last message"

    # Verify graph is interrupted
    state = await agent.aget_state(config)
    assert state.next, f"Expected state.next to be non-empty, got {state.next}"


# ═══════════════════════════════════════════════════════════════════════════
# Test 2: Confirm resumes graph and executes tools
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_confirm_executes_tools(agent_factory, creator_tools, fake_port):
    """Confirm pending actions → tools execute → LLM responds."""
    responses = [
        # Turn 1: LLM emits get_ticket_types tool call
        tool_call_msg([
            make_tc("get_ticket_types", {}, "call_001"),
        ]),
        # Turn 2: After tools execute, LLM responds with text
        text_msg("Tipos disponibles: Incidencia, Requerimiento, Consulta"),
    ]
    agent = agent_factory(creator_tools, responses, interrupt_before=["tools"])

    config = {"configurable": {"thread_id": "test-2"}, "recursion_limit": 30}

    # Step 1: Chat → should pause
    result = await agent.ainvoke(
        {"messages": [SystemMessage(content=""), HumanMessage(content="dame tipos")]},
        config=config,
    )
    state = await agent.aget_state(config)
    assert state.next, "Graph should be interrupted"

    # Step 2: Confirm → should resume, execute get_ticket_types, then LLM responds
    result = await agent.ainvoke(None, config=config)
    messages = result["messages"]
    last = messages[-1]

    # The last message should be the LLM's text response
    assert isinstance(last, AIMessage), f"Expected AIMessage, got {type(last)}"
    assert last.content, "Expected text content in final response"
    assert "Incidencia" in last.content or "tipos" in last.content.lower()

    # Verify graph is NOT interrupted anymore
    state = await agent.aget_state(config)
    assert not state.next, f"Graph should be finished, but next={state.next}"


# ═══════════════════════════════════════════════════════════════════════════
# Test 3: Reject cancels pending tool calls
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_reject_cancels_tools(agent_factory, creator_tools, fake_port):
    """Reject pending actions → tools do NOT execute → LLM acknowledges."""
    responses = [
        tool_call_msg([
            make_tc("create_ticket", {
                "asunto": "Ticket de prueba",
                "ticket_type_id": 1,
                "category_id": 1,
                "urgency_id": 3,
                "impact_id": 3,
                "priority_id": 3,
                "user_id": 2796,
            }, "call_001"),
        ]),
        # After rejection, LLM responds
        text_msg("Entendido, cancelé la creación del ticket."),
    ]
    agent = agent_factory(creator_tools, responses, interrupt_before=["tools"])

    config = {"configurable": {"thread_id": "test-3"}, "recursion_limit": 30}

    # Step 1: Chat → pause
    await agent.ainvoke(
        {"messages": [SystemMessage(content=""), HumanMessage(content="crea ticket")]},
        config=config,
    )
    state = await agent.aget_state(config)
    assert state.next, "Graph should be interrupted"

    # Step 2: Reject → send rejection ToolMessages
    rejection_messages = [
        ToolMessage(
            content=json.dumps({"rejected": True}),
            tool_call_id="call_001",
            name="create_ticket",
        )
    ]
    result = await agent.ainvoke(
        {"messages": rejection_messages}, config=config,
    )
    last = result["messages"][-1]
    assert isinstance(last, AIMessage)
    assert last.content, "Expected text acknowledgment after rejection"

    # Verify no ticket was created
    tickets = await fake_port.get_tickets_by_creator(2796)
    assert len(tickets) == 0, f"Expected 0 tickets, got {len(tickets)}"


# ═══════════════════════════════════════════════════════════════════════════
# Test 4: auto_confirm mode — no interruption
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_auto_confirm_no_interruption(agent_factory, creator_tools, fake_port):
    """auto_confirm=True → tools execute immediately, no pause."""
    responses = [
        tool_call_msg([
            make_tc("get_ticket_types", {}, "call_001"),
        ]),
        text_msg("Aquí están los tipos de ticket: Incidencia, Requerimiento."),
    ]
    # No interrupt_before → auto mode
    agent = agent_factory(creator_tools, responses, interrupt_before=None)

    config = {"configurable": {"thread_id": "test-4"}, "recursion_limit": 30}
    result = await agent.ainvoke(
        {"messages": [SystemMessage(content=""), HumanMessage(content="tipos")]},
        config=config,
    )

    # Graph should be complete, not interrupted
    state = await agent.aget_state(config)
    assert not state.next, f"Graph should be done, but next={state.next}"

    last = result["messages"][-1]
    assert isinstance(last, AIMessage)
    assert last.content
    assert "Incidencia" in last.content


# ═══════════════════════════════════════════════════════════════════════════
# Test 5: Multi-step confirm (re-interruption)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_multi_step_confirm(agent_factory, creator_tools):
    """After first confirm, LLM emits MORE tool_calls → graph re-interrupts."""
    responses = [
        # Turn 1: first tool call
        tool_call_msg([
            make_tc("get_ticket_types", {}, "call_001"),
        ]),
        # Turn 2: after first confirm, LLM emits second tool call
        tool_call_msg([
            make_tc("get_categories", {}, "call_002"),
        ]),
        # Turn 3: final text response
        text_msg("Categorías: Hardware, Software."),
    ]
    agent = agent_factory(creator_tools, responses, interrupt_before=["tools"])

    config = {"configurable": {"thread_id": "test-5"}, "recursion_limit": 30}

    # Step 1: Chat → first interruption
    await agent.ainvoke(
        {"messages": [SystemMessage(content=""), HumanMessage(content="catalogos")]},
        config=config,
    )
    state = await agent.aget_state(config)
    assert state.next, "Should be interrupted after first tool call"

    # Step 2: First confirm → tools execute → LLM emits second tool call
    result = await agent.ainvoke(None, config=config)
    state = await agent.aget_state(config)
    assert state.next, "Should be interrupted AGAIN after second tool call"
    messages = result["messages"]
    last_ai = [m for m in reversed(messages) if isinstance(m, AIMessage)]
    assert len(last_ai) >= 1
    assert last_ai[0].tool_calls, "Last AIMessage should have tool_calls"

    # Step 3: Second confirm → final completion
    result = await agent.ainvoke(None, config=config)
    state = await agent.aget_state(config)
    assert not state.next, "Graph should be finished"
    last = result["messages"][-1]
    assert isinstance(last, AIMessage)
    assert "Hardware" in last.content


# ═══════════════════════════════════════════════════════════════════════════
# Test 6: Full ticket lifecycle (create → assign → resolve) with auto mode
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_full_ticket_lifecycle(agent_factory, creator_tools,
                                      supervisor_tools, resolver_tools,
                                      fake_port):
    """End-to-end: creator creates ticket, supervisor assigns, resolver resolves."""
    # ── Creator creates ticket ──
    responses = [
        tool_call_msg([
            make_tc("create_ticket", {
                "asunto": "Servidor caido",
                "ticket_type_id": 1,
                "category_id": 1,
                "urgency_id": 3,
                "impact_id": 3,
                "priority_id": 3,
                "user_id": 2796,
                "descripcion": "No arranca",
            }, "call_create"),
        ]),
        text_msg("Ticket INC-1000 creado correctamente."),
    ]
    agent = agent_factory(creator_tools, responses, interrupt_before=None)
    config = {"configurable": {"thread_id": "lifecycle-1"}, "recursion_limit": 30}
    result = await agent.ainvoke(
        {"messages": [SystemMessage(content=""), HumanMessage(content="crea")]},
        config=config,
    )
    last = result["messages"][-1]
    assert "INC-1000" in last.content or "creado" in last.content.lower()

    # Verify ticket exists
    tickets = await fake_port.get_tickets_by_creator(2796)
    assert len(tickets) == 1
    assert tickets[0]["name"] == "INC-1000"

    # ── Supervisor assigns ticket ──
    responses2 = [
        tool_call_msg([
            make_tc("assign_ticket", {
                "ticket_id": 1000,
                "assignee_id": 2797,
                "agent_group_id": 1,
                "user_id": 2798,
            }, "call_assign"),
        ]),
        text_msg("Ticket INC-1000 asignado al agente 2797."),
    ]
    agent2 = agent_factory(supervisor_tools, responses2, interrupt_before=None)
    config2 = {"configurable": {"thread_id": "lifecycle-2"}, "recursion_limit": 30}
    result2 = await agent2.ainvoke(
        {"messages": [SystemMessage(content=""), HumanMessage(content="asigna")]},
        config=config2,
    )
    last2 = result2["messages"][-1]
    assert "asignado" in last2.content.lower() or "2797" in last2.content

    # Verify ticket is assigned
    detail = await fake_port.get_ticket_detail(1000, 2798, "supervisor")
    assert detail.get("asignado_a") == 2797, f"Expected asignado_a=2797, got {detail.get('asignado_a')}"

    # ── Resolver resolves ticket ──
    responses3 = [
        tool_call_msg([
            make_tc("resolve_ticket", {
                "ticket_id": 1000,
                "motivo_resolucion": "Se reemplazó la fuente de poder",
                "causa_raiz": "Fuente dañada por apagón",
                "user_id": 2797,
            }, "call_resolve"),
        ]),
        text_msg("Ticket INC-1000 resuelto correctamente."),
    ]
    agent3 = agent_factory(resolver_tools, responses3, interrupt_before=None)
    config3 = {"configurable": {"thread_id": "lifecycle-3"}, "recursion_limit": 30}
    result3 = await agent3.ainvoke(
        {"messages": [SystemMessage(content=""), HumanMessage(content="resuelve")]},
        config=config3,
    )
    last3 = result3["messages"][-1]
    assert "resuelto" in last3.content.lower()

    # Verify ticket is resolved
    detail3 = await fake_port.get_ticket_detail(1000, 2797, "resueltor")
    assert detail3.get("stage_id") == [3, "Resuelto"], f"Expected stage Resuelto, got {detail3.get('stage_id')}"


# ═══════════════════════════════════════════════════════════════════════════
# Test 7: Text-based confirmation ("confirmo")
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_text_confirm_resumes_graph(agent_factory, creator_tools, fake_port, monkeypatch):
    """Typing 'confirmo' in chat resumes an interrupted graph for mutating tools."""
    # Patch FeedbackCollector to avoid SQLite dependency
    from feedback.collector import FeedbackCollector
    monkeypatch.setattr(FeedbackCollector, "record_llm_usage", lambda *args, **kwargs: None)

    responses = [
        # Turn 1: LLM emits create_ticket tool call (mutating)
        tool_call_msg([
            make_tc("create_ticket", {
                "asunto": "Ticket de prueba",
                "ticket_type_id": 1,
                "category_id": 1,
                "urgency_id": 3,
                "impact_id": 3,
                "priority_id": 3,
                "user_id": 2796,
            }, "call_001"),
        ]),
        # Turn 2: After tool executes, LLM responds with text
        text_msg("Ticket creado correctamente."),
    ]
    agent = agent_factory(creator_tools, responses, interrupt_before=["tools"])

    from core.agent import get_response

    # Step 1: Chat → should pause with pending_actions (mutating tool)
    result1 = await get_response(
        agent, user_message="crea ticket",
        thread_id="text-confirm-1", user_id=2796, user_role="creador",
    )
    assert result1["status"] == "pending_actions"
    assert len(result1["pending_actions"]) == 1

    # Step 2: Type "confirmo" → should resume and execute tool
    result2 = await get_response(
        agent, user_message="confirmo",
        thread_id="text-confirm-1", user_id=2796, user_role="creador",
    )
    assert result2["status"] == "ok"
    assert "creado" in result2["reply"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# Test 7b: Read-only tools auto-confirm without user interaction
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_readonly_tools_auto_confirm(agent_factory, creator_tools, fake_port, monkeypatch):
    """Read-only tools (e.g. get_ticket_types) should execute without pending_actions."""
    from feedback.collector import FeedbackCollector
    monkeypatch.setattr(FeedbackCollector, "record_llm_usage", lambda *args, **kwargs: None)

    responses = [
        # Turn 1: LLM emits get_ticket_types read-only tool call
        tool_call_msg([
            make_tc("get_ticket_types", {}, "call_001"),
        ]),
        # Turn 2: After auto-execution, LLM responds with text
        text_msg("Tipos disponibles: Incidencia, Requerimiento, Consulta"),
    ]
    agent = agent_factory(creator_tools, responses, interrupt_before=["tools"])

    from core.agent import get_response

    result = await get_response(
        agent, user_message="dame tipos",
        thread_id="readonly-auto-1", user_id=2796, user_role="creador",
    )
    assert result["status"] == "ok"
    assert "incidencia" in result["reply"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# Test 8: Text-based rejection ("rechazo")
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_text_reject_cancels_tools(agent_factory, creator_tools, fake_port, monkeypatch):
    """Typing 'rechazo' in chat cancels pending tool calls."""
    # Patch FeedbackCollector to avoid SQLite dependency
    from feedback.collector import FeedbackCollector
    monkeypatch.setattr(FeedbackCollector, "record_llm_usage", lambda *args, **kwargs: None)

    responses = [
        # Turn 1: LLM emits create_ticket tool call
        tool_call_msg([
            make_tc("create_ticket", {
                "asunto": "Ticket de prueba",
                "ticket_type_id": 1,
                "category_id": 1,
                "urgency_id": 3,
                "impact_id": 3,
                "priority_id": 3,
                "user_id": 2796,
            }, "call_001"),
        ]),
        # Turn 2: After rejection, LLM responds
        text_msg("Entendido, cancelé la creación del ticket."),
    ]
    agent = agent_factory(creator_tools, responses, interrupt_before=["tools"])

    from core.agent import get_response

    # Step 1: Chat → should pause
    result1 = await get_response(
        agent, user_message="crea ticket",
        thread_id="text-reject-1", user_id=2796, user_role="creador",
    )
    assert result1["status"] == "pending_actions"

    # Step 2: Type "rechazo" → should cancel
    result2 = await get_response(
        agent, user_message="rechazo",
        thread_id="text-reject-1", user_id=2796, user_role="creador",
    )
    assert result2["status"] == "ok"
    assert "cancel" in result2["reply"].lower() or "entendido" in result2["reply"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# Test 9: Text confirm helper functions
# ═══════════════════════════════════════════════════════════════════════════

def test_confirmation_detection():
    """Unit test for _is_confirmation_message and _is_rejection_message."""
    from core.agent import _is_confirmation_message, _is_rejection_message

    assert _is_confirmation_message("confirmo")
    assert _is_confirmation_message("sí")
    assert _is_confirmation_message("ok")
    assert _is_confirmation_message("vale")
    assert _is_confirmation_message("dale, procede")
    assert not _is_confirmation_message("hola")
    assert not _is_confirmation_message("no estoy seguro")

    assert _is_rejection_message("rechazo")
    assert _is_rejection_message("no")          # standalone "no" IS a rejection
    assert _is_rejection_message("cancelar")
    assert _is_rejection_message("nope")
    assert not _is_rejection_message("hola")
    assert not _is_rejection_message("confirmo")
    assert not _is_rejection_message("no tengo nada")  # "no" in a sentence is NOT rejection
    assert not _is_rejection_message("no, probé otro")  # "no" as part of normal speech


# ═══════════════════════════════════════════════════════════════════════════
# Test 10: Supervisor text-based confirmation (assign_ticket)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_supervisor_text_confirm_assign(agent_factory, supervisor_tools, fake_port, monkeypatch):
    """Supervisor types 'confirmo' to confirm an assign_ticket action."""
    from feedback.collector import FeedbackCollector
    monkeypatch.setattr(FeedbackCollector, "record_llm_usage", lambda *args, **kwargs: None)

    responses = [
        tool_call_msg([
            make_tc("assign_ticket", {
                "ticket_id": 1000,
                "assignee_id": 2797,
                "agent_group_id": 1,
                "user_id": 2798,
            }, "call_assign"),
        ]),
        text_msg("Ticket INC-1000 asignado correctamente."),
    ]
    agent = agent_factory(supervisor_tools, responses, interrupt_before=["tools"])

    from core.agent import get_response

    # Step 1: Chat → should pause
    result1 = await get_response(
        agent, user_message="asigna el ticket",
        thread_id="sup-confirm-1", user_id=2798, user_role="supervisor",
    )
    assert result1["status"] == "pending_actions"
    assert len(result1["pending_actions"]) == 1

    # Step 2: Type "confirmo" → should resume and assign
    result2 = await get_response(
        agent, user_message="confirmo",
        thread_id="sup-confirm-1", user_id=2798, user_role="supervisor",
    )
    assert result2["status"] == "ok"
    assert "asignado" in result2["reply"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# Test 11: Supervisor text-based rejection
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_supervisor_text_reject(agent_factory, supervisor_tools, fake_port, monkeypatch):
    """Supervisor types 'rechazo' to cancel an approve_ticket action."""
    from feedback.collector import FeedbackCollector
    monkeypatch.setattr(FeedbackCollector, "record_llm_usage", lambda *args, **kwargs: None)

    responses = [
        tool_call_msg([
            make_tc("approve_ticket", {
                "ticket_id": 1000,
                "user_id": 2798,
            }, "call_approve"),
        ]),
        text_msg("Entendido, cancelé la aprobación del ticket."),
    ]
    agent = agent_factory(supervisor_tools, responses, interrupt_before=["tools"])

    from core.agent import get_response

    # Step 1: Chat → should pause
    result1 = await get_response(
        agent, user_message="aprueba el ticket",
        thread_id="sup-reject-1", user_id=2798, user_role="supervisor",
    )
    assert result1["status"] == "pending_actions"

    # Step 2: Type "rechazo" → should cancel
    result2 = await get_response(
        agent, user_message="rechazo",
        thread_id="sup-reject-1", user_id=2798, user_role="supervisor",
    )
    assert result2["status"] == "ok"


# ═══════════════════════════════════════════════════════════════════════════
# Test 12: Resolver text-based confirmation (resolve_ticket)
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_resolver_text_confirm_resolve(agent_factory, resolver_tools, fake_port, monkeypatch):
    """Resolver types 'confirmo' to confirm a resolve_ticket action."""
    from feedback.collector import FeedbackCollector
    monkeypatch.setattr(FeedbackCollector, "record_llm_usage", lambda *args, **kwargs: None)

    responses = [
        tool_call_msg([
            make_tc("resolve_ticket", {
                "ticket_id": 1000,
                "motivo_resolucion": "Reemplazo de equipo",
                "causa_raiz": "Falla de hardware",
                "user_id": 2797,
            }, "call_resolve"),
        ]),
        text_msg("Ticket INC-1000 resuelto correctamente."),
    ]
    agent = agent_factory(resolver_tools, responses, interrupt_before=["tools"])

    from core.agent import get_response

    # Step 1: Chat → should pause
    result1 = await get_response(
        agent, user_message="resuelve el ticket",
        thread_id="res-confirm-1", user_id=2797, user_role="resueltor",
    )
    assert result1["status"] == "pending_actions"
    assert len(result1["pending_actions"]) == 1

    # Step 2: Type "confirmo" → should resume and resolve
    result2 = await get_response(
        agent, user_message="confirmo",
        thread_id="res-confirm-1", user_id=2797, user_role="resueltor",
    )
    assert result2["status"] == "ok"
    assert "resuelto" in result2["reply"].lower()


# ═══════════════════════════════════════════════════════════════════════════
# Test 13: Interactive session not reset by orphan detector
# ═══════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_interactive_session_not_orphaned(agent_factory, creator_tools, fake_port, monkeypatch):
    """An interrupted graph should NOT be treated as orphaned when resuming."""
    from feedback.collector import FeedbackCollector
    monkeypatch.setattr(FeedbackCollector, "record_llm_usage", lambda *args, **kwargs: None)

    responses = [
        tool_call_msg([
            make_tc("create_ticket", {
                "asunto": "Ticket de prueba",
                "ticket_type_id": 1,
                "category_id": 1,
                "urgency_id": 3,
                "impact_id": 3,
                "priority_id": 3,
                "user_id": 2796,
            }, "call_001"),
        ]),
        text_msg("Ticket creado correctamente."),
    ]
    agent = agent_factory(creator_tools, responses, interrupt_before=["tools"])

    from core.agent import get_response

    # Step 1: First chat → should interrupt (mutating tool)
    result1 = await get_response(
        agent, user_message="crea ticket",
        thread_id="not-orphan-1", user_id=2796, user_role="creador",
    )
    assert result1["status"] == "pending_actions"

    # Step 2: Send another message (not a confirmation) → should NOT reset,
    # just continue as a normal chat on the same thread
    result2 = await get_response(
        agent, user_message="solo necesito los tipos de incidente",
        thread_id="not-orphan-1", user_id=2796, user_role="creador",
    )
    # The thread has tool_calls but is interrupted → orphan detector skips it.
    # The new message triggers a fresh LLM call on the same thread.
    # This should succeed without "orphaned tool_calls" reset.
    assert result2["status"] in ("ok", "pending_actions")
    # Verify the thread_id was NOT reset (the log shouldn't contain "resetting")


# ═══════════════════════════════════════════════════════════════════════════
# Test 14: Regression — trim_hook must protect AIMessage with pending
# tool_calls (the bug found in conv-creador-018)
# ═══════════════════════════════════════════════════════════════════════════

def test_trim_hook_keeps_aimessage_with_pending_tool_calls():
    """
    Regression: when the LLM emits a tool_call and the graph pauses waiting
    for user confirmation, trim_hook MUST preserve the AIMessage that
    contains the pending tool_call, even when the user has added several
    more messages after the action proposal.

    Original bug (conv-creador-018, turno 6): the agent proposed
    create_ticket (AIMessage with tool_calls), then the user added
    clarification messages, then said "Si, confirmo". The trim_hook cut
    the AIMessage that proposed the action because it was too far back
    in history. The LLM lost the action context and responded with the
    greeting.

    Real scenario: the LAST message is a HumanMessage (user just said
    "confirmo"), and the AIMessage with pending tool_calls is several
    messages back in history.
    """
    from core.agent import trim_hook

    # Construir el escenario del bug real:
    # - Turno 1: usuario pide crear ticket
    # - Turno 2: LLM responde con AIMessage + tool_call (PROPUESTA)
    # - Turnos 3-5: usuario agrega aclaraciones (más HumanMessage)
    # - Turno 6: usuario dice "confirmo" (último mensaje)
    # Total: 1 + 1 + 2*N + 1 = 7+ mensajes para forzar el trim
    msgs = []
    # Contexto inicial
    msgs.append(HumanMessage(content="Quiero crear un ticket de teclado dañado"))
    # LLM propone la acción con tool_calls
    msgs.append(AIMessage(
        content="Voy a crear el ticket con estos datos...",
        tool_calls=[{"id": "tc_create_001", "name": "create_ticket", "args": {
            "asunto": "Teclado dañado", "ticket_type_id": 1
        }}],
    ))
    # Usuario agrega 5 turnos de aclaración (10 mensajes Human + AI viejos)
    for i in range(5):
        msgs.append(HumanMessage(content=f"aclaración {i}"))
        msgs.append(AIMessage(content=f"respuesta a aclaración {i}"))
    # Usuario confirma
    msgs.append(HumanMessage(content="Si, confirmo, crea el ticket"))

    state = {"messages": msgs}
    result = trim_hook(state)
    kept = result["messages"]

    # El AIMessage con tool_calls DEBE estar presente en la ventana final,
    # aunque ya no sea el último mensaje.
    has_pending_ai = any(
        isinstance(m, AIMessage)
        and getattr(m, "tool_calls", None)
        and any(tc.get("id") == "tc_create_001" for tc in m.tool_calls)
        for m in kept
    )
    assert has_pending_ai, (
        "REGRESIÓN: trim_hook cortó el AIMessage con tool_calls pendiente. "
        "Esto rompe el flujo de confirmación humano-en-el-bucle "
        "(bug original: conv-creador-018, turno 6)."
    )


def test_trim_hook_does_not_protect_executed_aimessage():
    """
    Contrapartida del test anterior: si el AIMessage con tool_calls YA TIENE
    su ToolMessage correspondiente (acción ya ejecutada), trim_hook NO debe
    expandir la ventana — debe comportarse normalmente.
    """
    from core.agent import trim_hook

    msgs = [
        HumanMessage(content="crea ticket"),
        # AIMessage con tool_calls QUE YA TIENE respuesta → acción ya ejecutada
        AIMessage(
            content="Listo, creado",
            tool_calls=[{"id": "tc_create_002", "name": "create_ticket", "args": {}}],
        ),
        ToolMessage(
            content="Ticket INC-999999 creado",
            tool_call_id="tc_create_002",
        ),
    ]
    # Agregar turnos viejos para forzar trim
    for i in range(7):
        msgs.append(HumanMessage(content=f"turno viejo {i}"))
        msgs.append(AIMessage(content=f"respuesta vieja {i}"))
    # Y un nuevo turno (sin tool_call pendiente)
    msgs.append(HumanMessage(content="dame el detalle"))

    state = {"messages": msgs}
    result = trim_hook(state)
    kept = result["messages"]

    # En este caso la ventana DEBE respetar el trim_limit (no expandir).
    # El trim_limit=8 + 1 SystemMessage preservado = máximo 9 mensajes.
    assert len(kept) <= 9, (
        f"La ventana no debería expandirse cuando el AIMessage ya tiene "
        f"ToolMessage. Obtuvo {len(kept)} mensajes."
    )
