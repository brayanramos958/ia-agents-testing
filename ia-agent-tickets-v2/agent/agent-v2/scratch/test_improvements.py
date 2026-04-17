"""
Tests para las 4 mejoras implementadas en agent-v2.
No requieren Odoo, Groq ni ChromaDB — todo mockeado.

Ejecutar desde agent-v2/:
    python3 scratch/test_improvements.py
"""

import sys
import os
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch, call

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

PASS = "  PASS"
FAIL = "  FAIL"

results = []


def ok(name):
    results.append((True, name))
    print(f"{PASS}  {name}")


def fail(name, reason):
    results.append((False, name))
    print(f"{FAIL}  {name}")
    print(f"        → {reason}")


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 1 — Imports: los 6 archivos modificados deben importar sin error
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 1: imports ────────────────────────────────────────────────")


def test_imports():
    modules = [
        ("ports.rag_port",        "ports/rag_port.py"),
        ("rag.store",             "rag/store.py"),
        ("tools.ticket_tools",    "tools/ticket_tools.py"),
        ("tools.rag_tools",       "tools/rag_tools.py"),
        ("adapters.odoo_adapter", "adapters/odoo_adapter.py"),
    ]
    for mod, label in modules:
        try:
            __import__(mod)
            ok(f"import {label}")
        except Exception as e:
            fail(f"import {label}", str(e))

    # core.agent requires LangGraph internals — test only that its source parses
    import ast
    try:
        with open("core/agent.py") as f:
            ast.parse(f.read())
        ok("parse core/agent.py (skips LangGraph import)")
    except Exception as e:
        fail("parse core/agent.py", str(e))


test_imports()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 2 — #2 causa_raiz: interfaces y contratos
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 2: causa_raiz en interfaces ──────────────────────────────")


def test_solution_item_has_causa_raiz():
    from ports.rag_port import SolutionItem
    import dataclasses
    fields = {f.name for f in dataclasses.fields(SolutionItem)}
    if "causa_raiz" in fields:
        ok("SolutionItem tiene campo causa_raiz")
    else:
        fail("SolutionItem tiene campo causa_raiz", f"Campos actuales: {fields}")


def test_solution_item_causa_raiz_default():
    from ports.rag_port import SolutionItem
    s = SolutionItem(
        ticket_name="TCK-0001", ticket_id=1, category="Hardware",
        ticket_type="Incidente", description="Mouse roto",
        motivo_resolucion="Se reemplazó el mouse", score=0.85,
    )
    if s.causa_raiz == "":
        ok("SolutionItem.causa_raiz tiene default vacío (no rompe código existente)")
    else:
        fail("SolutionItem.causa_raiz default", f"Valor inesperado: {s.causa_raiz!r}")


def test_iragport_add_resolved_ticket_signature():
    import inspect
    from ports.rag_port import IRAGPort
    sig = inspect.signature(IRAGPort.add_resolved_ticket)
    params = list(sig.parameters.keys())
    if "causa_raiz" in params:
        ok("IRAGPort.add_resolved_ticket acepta causa_raiz")
    else:
        fail("IRAGPort.add_resolved_ticket acepta causa_raiz", f"Params actuales: {params}")


def test_iragport_causa_raiz_has_default():
    import inspect
    from ports.rag_port import IRAGPort
    sig = inspect.signature(IRAGPort.add_resolved_ticket)
    param = sig.parameters.get("causa_raiz")
    if param and param.default == "":
        ok("IRAGPort.add_resolved_ticket causa_raiz tiene default='' (backwards compat)")
    else:
        fail("IRAGPort.add_resolved_ticket causa_raiz default", f"Default: {param.default if param else 'MISSING'!r}")


test_solution_item_has_causa_raiz()
test_solution_item_causa_raiz_default()
test_iragport_add_resolved_ticket_signature()
test_iragport_causa_raiz_has_default()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 3 — #2 causa_raiz: ChromaRAGStore embebe causa_raiz en document_text
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 3: causa_raiz en RAG store ───────────────────────────────")


def test_rag_store_add_embeds_causa_raiz():
    """add_resolved_ticket debe incluir causa_raiz en el texto del documento."""
    captured_docs = []

    mock_chroma = MagicMock()
    mock_chroma._collection.count.return_value = 0
    mock_chroma.add_documents.side_effect = lambda docs: captured_docs.extend(docs)

    with patch("rag.store.Chroma", return_value=mock_chroma), \
         patch("rag.store.get_embeddings", return_value=MagicMock()):
        from rag.store import ChromaRAGStore
        store = ChromaRAGStore(persist_path="/tmp/test_rag", enabled=True)
        store.add_resolved_ticket(
            ticket_id=1,
            ticket_name="TCK-0001",
            ticket_type="Incidente",
            category="Hardware",
            description="Mouse no funciona",
            motivo_resolucion="Se reemplazó el mouse",
            causa_raiz="Cable USB dañado por desgaste",
        )

    if not captured_docs:
        fail("add_resolved_ticket embeds causa_raiz", "No se llamó add_documents")
        return

    doc_text = captured_docs[0].page_content
    if "Cable USB dañado por desgaste" in doc_text:
        ok("add_resolved_ticket: causa_raiz aparece en page_content")
    else:
        fail("add_resolved_ticket: causa_raiz en page_content", f"Texto: {doc_text!r}")

    meta = captured_docs[0].metadata
    if meta.get("causa_raiz") == "Cable USB dañado por desgaste":
        ok("add_resolved_ticket: causa_raiz está en metadata")
    else:
        fail("add_resolved_ticket: causa_raiz en metadata", f"Metadata: {meta}")


def test_rag_store_add_without_causa_raiz():
    """Sin causa_raiz, el documento no debe incluir 'Root cause:'."""
    captured_docs = []
    mock_chroma = MagicMock()
    mock_chroma._collection.count.return_value = 0
    mock_chroma.add_documents.side_effect = lambda docs: captured_docs.extend(docs)

    with patch("rag.store.Chroma", return_value=mock_chroma), \
         patch("rag.store.get_embeddings", return_value=MagicMock()):
        from rag.store import ChromaRAGStore
        store = ChromaRAGStore(persist_path="/tmp/test_rag2", enabled=True)
        store.add_resolved_ticket(
            ticket_id=2,
            ticket_name="TCK-0002",
            ticket_type="Incidente",
            category="Software",
            description="No abre Excel",
            motivo_resolucion="Se reinstalaron las librerías de Office",
        )

    if not captured_docs:
        fail("add_resolved_ticket sin causa_raiz", "No se llamó add_documents")
        return

    doc_text = captured_docs[0].page_content
    if "Root cause:" not in doc_text:
        ok("add_resolved_ticket sin causa_raiz: no agrega 'Root cause:' vacío")
    else:
        fail("add_resolved_ticket sin causa_raiz", f"Texto inesperado: {doc_text!r}")


def test_rag_store_initialize_embeds_causa_raiz():
    """initialize_from_resolved_tickets debe incluir causa_raiz en los documentos."""
    captured_docs = []
    mock_chroma = MagicMock()
    mock_chroma._collection.count.return_value = 0  # vacío — debe sembrar
    mock_chroma.add_documents.side_effect = lambda docs: captured_docs.extend(docs)

    with patch("rag.store.Chroma", return_value=mock_chroma), \
         patch("rag.store.get_embeddings", return_value=MagicMock()):
        from rag.store import ChromaRAGStore
        store = ChromaRAGStore(persist_path="/tmp/test_rag3", enabled=True)
        store.initialize_from_resolved_tickets([
            {
                "ticket_id": 10,
                "ticket_name": "TCK-0010",
                "ticket_type": "Incidente",
                "category": "Red",
                "description": "No hay internet",
                "motivo_resolucion": "Se reinició el router",
                "causa_raiz": "Firmware desactualizado del router",
            }
        ])

    if not captured_docs:
        fail("initialize_from_resolved_tickets embeds causa_raiz", "No se llamó add_documents")
        return

    doc_text = captured_docs[0].page_content
    if "Firmware desactualizado del router" in doc_text:
        ok("initialize_from_resolved_tickets: causa_raiz aparece en page_content")
    else:
        fail("initialize_from_resolved_tickets: causa_raiz en page_content", f"Texto: {doc_text!r}")


test_rag_store_add_embeds_causa_raiz()
test_rag_store_add_without_causa_raiz()
test_rag_store_initialize_embeds_causa_raiz()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 4 — #2 causa_raiz: resolve_ticket pasa causa_raiz al RAG
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 4: causa_raiz fluye ticket_tools → RAG ───────────────────")


def test_resolve_ticket_passes_causa_raiz_to_rag():
    """resolve_ticket debe pasar causa_raiz a add_resolved_ticket."""
    from tools import ticket_tools

    mock_port = MagicMock()
    mock_port.resolve_ticket.return_value = {"success": True, "ticket_id": 5}
    mock_port.get_ticket_detail.return_value = {
        "name": "TCK-0005",
        "ticket_type": "Incidente",
        "category": "Hardware",
        "descripcion": "Teclado no responde",
    }

    mock_rag = MagicMock()
    mock_rag.add_resolved_ticket.return_value = True

    ticket_tools._port = mock_port
    ticket_tools._rag_port = mock_rag

    ticket_tools.resolve_ticket.invoke({
        "ticket_id": "5",
        "motivo_resolucion": "Se reemplazó el teclado",
        "causa_raiz": "Derrame de líquido dañó los contactos",
        "user_id": "42",
    })

    if not mock_rag.add_resolved_ticket.called:
        fail("resolve_ticket llama add_resolved_ticket", "No se llamó")
        return

    kwargs = mock_rag.add_resolved_ticket.call_args.kwargs
    positional = mock_rag.add_resolved_ticket.call_args.args

    # causa_raiz puede llegar como kwarg o posicional
    causa_passed = kwargs.get("causa_raiz") or (positional[6] if len(positional) > 6 else None)

    if causa_passed == "Derrame de líquido dañó los contactos":
        ok("resolve_ticket pasa causa_raiz a add_resolved_ticket")
    else:
        fail("resolve_ticket pasa causa_raiz", f"Valor recibido: {causa_passed!r} | kwargs={kwargs} | args={positional}")


def test_rag_tools_exposes_causa_raiz():
    """suggest_solution_before_ticket debe incluir causa_raiz en el output."""
    from tools import rag_tools
    from ports.rag_port import SuggestionResult, SolutionItem

    mock_rag = MagicMock()
    mock_rag.search_similar.return_value = SuggestionResult(
        solutions_found=True,
        confidence=0.85,
        solutions=[
            SolutionItem(
                ticket_name="TCK-0001",
                ticket_id=1,
                category="Hardware",
                ticket_type="Incidente",
                description="Mouse roto",
                motivo_resolucion="Se reemplazó el mouse",
                causa_raiz="Cable interno fracturado",
                score=0.85,
            )
        ],
    )
    rag_tools._rag_port = mock_rag

    result = rag_tools.suggest_solution_before_ticket.invoke({
        "description": "No me funciona el mouse",
        "category": "Hardware",
    })

    solutions = result.get("solutions", [])
    if not solutions:
        fail("suggest_solution_before_ticket expone causa_raiz", "No hay soluciones en resultado")
        return

    if "causa_raiz" in solutions[0]:
        if solutions[0]["causa_raiz"] == "Cable interno fracturado":
            ok("suggest_solution_before_ticket: causa_raiz presente en output al LLM")
        else:
            fail("suggest_solution_before_ticket: valor causa_raiz", f"Valor: {solutions[0]['causa_raiz']!r}")
    else:
        fail("suggest_solution_before_ticket: campo causa_raiz ausente", f"Keys: {list(solutions[0].keys())}")


test_resolve_ticket_passes_causa_raiz_to_rag()
test_rag_tools_exposes_causa_raiz()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 5 — #2 causa_raiz: OdooAdapter incluye causa_raiz en get_resolved_tickets
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 5: causa_raiz en OdooAdapter ─────────────────────────────")


def test_odoo_adapter_get_resolved_tickets_includes_causa_raiz():
    """get_resolved_tickets debe incluir causa_raiz en cada ticket del resultado."""
    from adapters.odoo_adapter import OdooAdapter

    odoo_raw = [
        {
            "id": 1,
            "name": "TCK-0001",
            "ticket_type_id": [1, "Incidente"],
            "category_id": [2, "Hardware"],
            "descripcion": "<p>Mouse roto</p>",
            "motivo_resolucion": "<p>Se reemplazó el mouse</p>",
            "causa_raiz": "<p>Cable dañado</p>",
        }
    ]

    adapter = OdooAdapter.__new__(OdooAdapter)
    adapter._call_kw = MagicMock(return_value=odoo_raw)

    result = adapter.get_resolved_tickets()

    if not result:
        fail("get_resolved_tickets incluye causa_raiz", "Resultado vacío")
        return

    ticket = result[0]
    if "causa_raiz" in ticket:
        ok("get_resolved_tickets: campo causa_raiz presente en resultado")
    else:
        fail("get_resolved_tickets: campo causa_raiz", f"Keys: {list(ticket.keys())}")

    if ticket["causa_raiz"] == "<p>Cable dañado</p>":
        ok("get_resolved_tickets: valor causa_raiz correcto")
    else:
        fail("get_resolved_tickets: valor causa_raiz", f"Valor: {ticket['causa_raiz']!r}")


def test_odoo_adapter_fetches_causa_raiz_field():
    """_call_kw debe recibir 'causa_raiz' en la lista de fields."""
    from adapters.odoo_adapter import OdooAdapter

    adapter = OdooAdapter.__new__(OdooAdapter)
    captured_kwargs = {}

    def fake_call_kw(model, method, args, kwargs=None):
        captured_kwargs.update(kwargs or {})
        return []  # vacío — no hay tickets resueltos

    adapter._call_kw = fake_call_kw
    adapter.get_resolved_tickets()

    fields_requested = captured_kwargs.get("fields", [])
    if "causa_raiz" in fields_requested:
        ok("get_resolved_tickets: 'causa_raiz' está en los fields solicitados a Odoo")
    else:
        fail("get_resolved_tickets: fields solicitados", f"Fields: {fields_requested}")


test_odoo_adapter_get_resolved_tickets_includes_causa_raiz()
test_odoo_adapter_fetches_causa_raiz_field()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 6 — #3 _trim_hook: solo conserva el SystemMessage más reciente
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 6: _trim_hook conserva solo el último SystemMessage ───────")


def _run_trim_hook(msgs):
    """
    Replica exacta de la lógica del _trim_hook de create_agent().
    Se prueba la lógica directamente porque el hook es una closure.
    """
    from langchain_core.messages import SystemMessage as _SM, AIMessage as _AI, ToolMessage as _TM, HumanMessage as _HM

    all_system = [m for m in msgs if isinstance(m, _SM)]
    system = [all_system[-1]] if all_system else []
    non_system = [m for m in msgs if not isinstance(m, _SM)]

    window = non_system[-12:] if len(non_system) > 12 else non_system

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

    sanitized = []
    for m in window:
        if isinstance(m, _TM) and not m.content:
            m = m.model_copy(update={"content": "[sin resultado]"})
        sanitized.append(m)

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

    return {"messages": system + clean}


def test_trim_hook_keeps_only_last_system_message():
    """Con N SystemMessages acumulados, solo debe quedar el último."""
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

    state = {
        "messages": [
            SystemMessage(content="System turno 1"),
            HumanMessage(content="Hola"),
            AIMessage(content="Hola, ¿en qué te ayudo?"),
            SystemMessage(content="System turno 2"),
            HumanMessage(content="Quiero crear un ticket"),
            AIMessage(content="Claro, ¿qué problema tienes?"),
            SystemMessage(content="System turno 3 — EL ACTUAL"),
            HumanMessage(content="Mi mouse no funciona"),
        ]
    }

    result = _run_trim_hook(state["messages"])
    system_msgs = [m for m in result["messages"] if hasattr(m, "content") and "System" in type(m).__name__]

    from langchain_core.messages import SystemMessage as SM
    system_msgs = [m for m in result["messages"] if isinstance(m, SM)]

    if len(system_msgs) == 1:
        ok("_trim_hook: con 3 SystemMessages acumulados, solo queda 1")
    else:
        fail("_trim_hook: cantidad SystemMessages", f"Quedaron {len(system_msgs)} en lugar de 1")

    if system_msgs and system_msgs[0].content == "System turno 3 — EL ACTUAL":
        ok("_trim_hook: el SystemMessage conservado es el MÁS RECIENTE")
    else:
        fail("_trim_hook: SystemMessage incorrecto", f"Contenido: {system_msgs[0].content if system_msgs else 'NINGUNO'!r}")


def test_trim_hook_no_system_messages():
    """Si no hay SystemMessages, el resultado no debe romper."""
    from langchain_core.messages import HumanMessage, AIMessage

    state = {
        "messages": [
            HumanMessage(content="Hola"),
            AIMessage(content="Hola"),
        ]
    }
    try:
        result = _run_trim_hook(state["messages"])
        from langchain_core.messages import SystemMessage as SM
        system_msgs = [m for m in result["messages"] if isinstance(m, SM)]
        if len(system_msgs) == 0:
            ok("_trim_hook: sin SystemMessages no rompe")
        else:
            fail("_trim_hook sin SystemMessages", f"Apareció 1 inesperado")
    except Exception as e:
        fail("_trim_hook sin SystemMessages lanza excepción", str(e))


def test_trim_hook_single_system_message():
    """Con un solo SystemMessage (caso normal), debe conservarlo."""
    from langchain_core.messages import SystemMessage, HumanMessage, AIMessage

    state = {
        "messages": [
            SystemMessage(content="System único"),
            HumanMessage(content="Hola"),
        ]
    }
    result = _run_trim_hook(state["messages"])
    from langchain_core.messages import SystemMessage as SM
    system_msgs = [m for m in result["messages"] if isinstance(m, SM)]

    if len(system_msgs) == 1 and system_msgs[0].content == "System único":
        ok("_trim_hook: con 1 SystemMessage, lo conserva correctamente")
    else:
        fail("_trim_hook: caso único", f"System msgs: {[m.content for m in system_msgs]}")


test_trim_hook_keeps_only_last_system_message()
test_trim_hook_no_system_messages()
test_trim_hook_single_system_message()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 7 — #1 Cache de creator context
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 7: cache de creator context ──────────────────────────────")


def test_creator_context_cached_after_first_call():
    """El segundo llamado con el mismo thread_id NO debe llamar a Odoo."""
    # Importar y limpiar el cache antes del test
    import core.agent as agent_module
    # Parchamos _fetch_creator_context directamente probando el cache del módulo

    agent_module._creator_context_cache.clear()

    mock_port = MagicMock()
    mock_port.get_tickets_by_creator.return_value = []

    async def run():
        with patch.dict("sys.modules", {}):
            # Inyectamos el mock_port en ticket_tools
            import tools.ticket_tools as tt
            original_port = tt._port
            tt._port = mock_port
            try:
                # Primera llamada — debe llamar a Odoo
                r1 = await agent_module._fetch_creator_context(user_id=1, thread_id="thread-abc")
                # Segunda llamada — debe usar cache
                r2 = await agent_module._fetch_creator_context(user_id=1, thread_id="thread-abc")
            finally:
                tt._port = original_port
        return r1, r2

    r1, r2 = asyncio.run(run())

    call_count = mock_port.get_tickets_by_creator.call_count
    if call_count == 1:
        ok("_fetch_creator_context: Odoo llamado UNA SOLA VEZ para el mismo thread_id")
    else:
        fail("_fetch_creator_context: Odoo llamado más de una vez", f"Llamadas: {call_count}")

    if r1 == r2:
        ok("_fetch_creator_context: resultado consistente entre llamadas")
    else:
        fail("_fetch_creator_context: resultados difieren", f"r1={r1!r} r2={r2!r}")


def test_creator_context_different_threads_call_odoo():
    """Dos thread_ids distintos deben hacer llamadas independientes a Odoo."""
    import core.agent as agent_module
    agent_module._creator_context_cache.clear()

    mock_port = MagicMock()
    mock_port.get_tickets_by_creator.return_value = []

    async def run():
        import tools.ticket_tools as tt
        original = tt._port
        tt._port = mock_port
        try:
            await agent_module._fetch_creator_context(user_id=1, thread_id="thread-X")
            await agent_module._fetch_creator_context(user_id=2, thread_id="thread-Y")
        finally:
            tt._port = original

    asyncio.run(run())

    call_count = mock_port.get_tickets_by_creator.call_count
    if call_count == 2:
        ok("_fetch_creator_context: threads distintos hacen llamadas independientes a Odoo")
    else:
        fail("_fetch_creator_context: llamadas para threads distintos", f"Esperaba 2, recibió {call_count}")


def test_invalidate_creator_context():
    """invalidate_creator_context debe limpiar la entrada del cache."""
    import core.agent as agent_module
    agent_module._creator_context_cache.clear()
    agent_module._creator_context_cache["thread-del"] = "contexto guardado"

    agent_module.invalidate_creator_context("thread-del")

    if "thread-del" not in agent_module._creator_context_cache:
        ok("invalidate_creator_context: limpia la entrada del cache correctamente")
    else:
        fail("invalidate_creator_context", "La entrada sigue en cache después de invalidar")

    # Invalidar un thread inexistente no debe romper
    try:
        agent_module.invalidate_creator_context("thread-inexistente")
        ok("invalidate_creator_context: no rompe con thread inexistente")
    except Exception as e:
        fail("invalidate_creator_context con thread inexistente", str(e))


test_creator_context_cached_after_first_call()
test_creator_context_different_threads_call_odoo()
test_invalidate_creator_context()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 8 — Regresión: test de resiliencia original sigue pasando
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 8: regresión — resiliencia original ───────────────────────")


def test_resilience_success_after_retries():
    from tools.ticket_tools import create_ticket, set_ticket_port

    mock_port = MagicMock()
    mock_port.create_ticket.side_effect = [
        Exception("Error de red 1"),
        Exception("Error de red 2"),
        {"success": True, "ticket_name": "TCK-0099", "ticket_id": 99},
    ]
    mock_port.get_ticket_types.return_value = [{"id": 1, "name": "Incidente"}]
    mock_port.get_categories.return_value = [{"id": 1, "name": "Hardware"}]
    mock_port.get_urgency_levels.return_value = [{"id": 1, "name": "Alta"}]
    mock_port.get_impact_levels.return_value = [{"id": 1, "name": "Alto"}]
    mock_port.get_priority_levels.return_value = [{"id": 1, "name": "Alta"}]

    set_ticket_port(mock_port)

    try:
        result = create_ticket.invoke({
            "asunto": "Test", "descripcion": "Test",
            "ticket_type_id": "1", "category_id": "1",
            "urgency_id": "1", "impact_id": "1",
            "priority_id": "1", "user_id": "1",
        })
        if result.get("success") and mock_port.create_ticket.call_count == 3:
            ok("Resiliencia: éxito tras 2 fallos (3 intentos)")
        else:
            fail("Resiliencia: éxito tras fallos", f"result={result}, calls={mock_port.create_ticket.call_count}")
    except Exception as e:
        fail("Resiliencia: excepción inesperada", str(e))


def test_resilience_failure_after_max_retries():
    from tools.ticket_tools import create_ticket, set_ticket_port

    mock_port = MagicMock()
    mock_port.create_ticket.side_effect = Exception("Odoo caído")
    mock_port.get_ticket_types.return_value = [{"id": 1, "name": "Incidente"}]
    mock_port.get_categories.return_value = [{"id": 1, "name": "Hardware"}]
    mock_port.get_urgency_levels.return_value = [{"id": 1, "name": "Alta"}]
    mock_port.get_impact_levels.return_value = [{"id": 1, "name": "Alto"}]
    mock_port.get_priority_levels.return_value = [{"id": 1, "name": "Alta"}]

    set_ticket_port(mock_port)

    try:
        create_ticket.invoke({
            "asunto": "Test", "descripcion": "Test",
            "ticket_type_id": "1", "category_id": "1",
            "urgency_id": "1", "impact_id": "1",
            "priority_id": "1", "user_id": "1",
        })
        fail("Resiliencia: debe fallar tras 3 intentos", "No lanzó excepción")
    except Exception:
        if mock_port.create_ticket.call_count == 3:
            ok("Resiliencia: falla exactamente tras 3 intentos")
        else:
            fail("Resiliencia: conteo de reintentos", f"Llamadas: {mock_port.create_ticket.call_count}")


test_resilience_success_after_retries()
test_resilience_failure_after_max_retries()


# ─────────────────────────────────────────────────────────────────────────────
# Resumen final
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
passed = sum(1 for ok, _ in results if ok)
failed = sum(1 for ok, _ in results if not ok)
total = len(results)
print(f"  Resultado: {passed}/{total} pasaron  |  {failed} fallaron")
if failed == 0:
    print("  Todo OK — ningún cambio rompió comportamiento existente.")
else:
    print("  ATENCIÓN: hay fallos que revisar.")
print("─" * 60)

sys.exit(0 if failed == 0 else 1)
