"""
Tests para Bug-A y Bug-B — TDD: estos tests deben FALLAR antes del fix
y PASAR después.

Bug-A: _fetch_creator_context filtra por t.get("state","") que no existe
       en Odoo → todos los tickets aparecen "abiertos" incluyendo cerrados.

Bug-B: OdooAdapter.get_tickets_by_creator no tiene filtro de stage en el
       domain de Odoo → devuelve tickets cerrados/resueltos.
       (get_tickets_by_assignee sí tiene el filtro — inconsistencia).

Ejecutar desde agent-v2/:
    .venv/bin/python3 scratch/test_bugs_ab.py
"""

import sys
import os
import asyncio
from unittest.mock import MagicMock, patch

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
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_ticket(name, stage_id_tuple, is_close=False):
    """
    Simula el formato de un ticket que devuelve Odoo search_read.
    stage_id viene como [id, name] tuple — igual que Odoo JSON-RPC.
    """
    return {
        "name": name,
        "asunto": f"Problema: {name}",
        "stage_id": stage_id_tuple,
        "urgency_id": [1, "Media"],
        "ticket_type_id": [1, "Incidente"],
        "fecha_creacion": "2026-04-01 10:00:00",
        "partner_id": [10, "Juan Pérez"],
    }


TICKET_OPEN     = _make_ticket("TCK-0001", [2, "En proceso"])
TICKET_RESOLVED = _make_ticket("TCK-0002", [5, "Resuelto"])
TICKET_CLOSED   = _make_ticket("TCK-0003", [6, "Cerrado"])
TICKET_NEW      = _make_ticket("TCK-0004", [1, "Nuevo"])


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 1 — Bug-B: OdooAdapter.get_tickets_by_creator domain filter
# Estos tests verifican que el adapter excluye tickets cerrados desde Odoo.
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 1: Bug-B — OdooAdapter domain filter ──────────────────────")


def test_get_tickets_by_creator_sends_is_close_filter():
    """
    get_tickets_by_creator DEBE incluir ["stage_id.is_close","=",False]
    en el domain enviado a Odoo, igual que get_tickets_by_assignee.

    FALLA antes del fix: el domain solo tiene la condición de user_id.
    PASA después del fix: el domain también incluye el filtro de stage.
    """
    from adapters.odoo_adapter import OdooAdapter

    adapter = OdooAdapter.__new__(OdooAdapter)
    captured_domain = {}

    def fake_call_kw(model, method, args, kwargs=None):
        # args[0] es el domain en search_read
        if method == "search_read":
            captured_domain["domain"] = args[0]
        return []

    adapter._call_kw = fake_call_kw
    adapter.get_tickets_by_creator(user_id=42)

    domain = captured_domain.get("domain", [])
    # Aplanar el domain para buscar la condición
    domain_str = str(domain)

    if "is_close" in domain_str and "False" in domain_str:
        ok("get_tickets_by_creator: domain incluye ['stage_id.is_close','=',False]")
    else:
        fail(
            "get_tickets_by_creator: domain incluye ['stage_id.is_close','=',False]",
            f"Domain actual: {domain_str}"
        )


def test_get_tickets_by_creator_domain_consistent_with_assignee():
    """
    El domain de get_tickets_by_creator debe tener la misma restricción
    de stage que get_tickets_by_assignee.

    Comparamos los campos filtrados por stage en ambas queries.
    FALLA antes del fix: creator no tiene filtro de stage.
    PASA después del fix: ambos filtran por is_close=False.
    """
    from adapters.odoo_adapter import OdooAdapter

    adapter = OdooAdapter.__new__(OdooAdapter)
    creator_domain = {}
    assignee_domain = {}

    def fake_call_kw_creator(model, method, args, kwargs=None):
        if method == "search_read":
            creator_domain["domain"] = str(args[0])
        return []

    def fake_call_kw_assignee(model, method, args, kwargs=None):
        if method == "search_read":
            assignee_domain["domain"] = str(args[0])
        return []

    adapter._call_kw = fake_call_kw_creator
    adapter.get_tickets_by_creator(user_id=1)

    adapter._call_kw = fake_call_kw_assignee
    adapter.get_tickets_by_assignee(user_id=1)

    creator_has_filter  = "is_close" in creator_domain.get("domain", "")
    assignee_has_filter = "is_close" in assignee_domain.get("domain", "")

    if creator_has_filter and assignee_has_filter:
        ok("Ambos métodos filtran por is_close — consistencia garantizada")
    elif not creator_has_filter and assignee_has_filter:
        fail(
            "Consistencia entre creator y assignee",
            "get_tickets_by_creator NO filtra por is_close, get_tickets_by_assignee SÍ"
        )
    else:
        fail(
            "Consistencia entre creator y assignee",
            f"creator_has_filter={creator_has_filter}, assignee_has_filter={assignee_has_filter}"
        )


def test_get_tickets_by_creator_only_returns_open_tickets_from_odoo():
    """
    Si Odoo devuelve solo tickets abiertos (el filter funciona en el servidor),
    el adapter debe retornarlos tal cual.
    Solo TCK-0001 y TCK-0004 son abiertos — el mock simula que Odoo ya filtró.

    PASA con o sin el fix (verifica el contrato de retorno, no el filtrado).
    """
    from adapters.odoo_adapter import OdooAdapter

    odoo_response = [TICKET_OPEN, TICKET_NEW]  # Odoo ya filtró los cerrados

    adapter = OdooAdapter.__new__(OdooAdapter)
    adapter._call_kw = MagicMock(return_value=odoo_response)

    result = adapter.get_tickets_by_creator(user_id=42)

    if len(result) == 2 and all(t["name"] in {"TCK-0001", "TCK-0004"} for t in result):
        ok("get_tickets_by_creator: retorna los tickets que Odoo devuelve (contrato de retorno)")
    else:
        fail("get_tickets_by_creator: contrato de retorno", f"Resultado: {[t['name'] for t in result]}")


test_get_tickets_by_creator_sends_is_close_filter()
test_get_tickets_by_creator_domain_consistent_with_assignee()
test_get_tickets_by_creator_only_returns_open_tickets_from_odoo()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 2 — Bug-A: _fetch_creator_context filtra incorrectamente
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 2: Bug-A — _fetch_creator_context filtrado de stage ───────")


def _run_fetch_context(tickets_from_odoo):
    """Helper: ejecuta _fetch_creator_context con un mock port que devuelve tickets_from_odoo."""
    import core.agent as agent_module
    agent_module._creator_context_cache.clear()

    mock_port = MagicMock()
    mock_port.get_tickets_by_creator.return_value = tickets_from_odoo

    async def run():
        import tools.ticket_tools as tt
        original = tt._port
        tt._port = mock_port
        try:
            return await agent_module._fetch_creator_context(user_id=1, thread_id="test-thread-bugs")
        finally:
            tt._port = original
            agent_module._creator_context_cache.clear()

    return asyncio.run(run())


def test_fetch_context_excludes_resolved_tickets():
    """
    Si Odoo devuelve tickets resueltos (stage_id=[5,"Resuelto"]),
    _fetch_creator_context NO debe incluirlos en el historial del system prompt.

    FALLA antes del fix: filtra por `state` (no existe) → todos pasan → Resuelto aparece.
    PASA después del fix: filtra por stage_id correctamente → Resuelto no aparece.
    """
    result = _run_fetch_context([TICKET_OPEN, TICKET_RESOLVED])

    if "TCK-0002" not in result:
        ok("_fetch_creator_context: excluye ticket Resuelto (stage_id=[5,'Resuelto'])")
    else:
        fail(
            "_fetch_creator_context: excluye ticket Resuelto",
            f"TCK-0002 (Resuelto) aparece en el contexto: ...{result[result.find('TCK-0002')-10:result.find('TCK-0002')+40]}..."
            if "TCK-0002" in result else "TCK-0002 no encontrado pero el test falló por otra razón"
        )


def test_fetch_context_excludes_closed_tickets():
    """
    Si Odoo devuelve tickets cerrados (stage_id=[6,"Cerrado"]),
    _fetch_creator_context NO debe incluirlos.

    FALLA antes del fix: filtra por `state` → todos pasan → Cerrado aparece.
    PASA después del fix: filtra por stage_id → Cerrado no aparece.
    """
    result = _run_fetch_context([TICKET_OPEN, TICKET_CLOSED])

    if "TCK-0003" not in result:
        ok("_fetch_creator_context: excluye ticket Cerrado (stage_id=[6,'Cerrado'])")
    else:
        fail(
            "_fetch_creator_context: excluye ticket Cerrado",
            "TCK-0003 (Cerrado) aparece en el contexto inyectado al LLM"
        )


def test_fetch_context_includes_open_tickets():
    """
    Tickets en stages abiertos deben aparecer en el historial.

    PASA con o sin el fix (verifica que los abiertos sí aparecen).
    """
    result = _run_fetch_context([TICKET_OPEN, TICKET_NEW])

    if "TCK-0001" in result and "TCK-0004" in result:
        ok("_fetch_creator_context: incluye tickets abiertos (En proceso, Nuevo)")
    else:
        fail(
            "_fetch_creator_context: incluye tickets abiertos",
            f"Contexto generado: {result!r}"
        )


def test_fetch_context_all_closed_shows_no_open_tickets():
    """
    Si todos los tickets están cerrados/resueltos, el mensaje debe decir
    'Sin tickets abiertos actualmente', no listar ninguno.

    FALLA antes del fix: todos pasan el filtro de `state` → los lista.
    PASA después del fix: todos son filtrados → muestra mensaje vacío.
    """
    result = _run_fetch_context([TICKET_RESOLVED, TICKET_CLOSED])

    # Después del fix: no debe haber tickets listados
    has_open_listed = "TCK-0002" in result or "TCK-0003" in result
    has_empty_msg   = "Sin tickets abiertos" in result or "Sin tickets registrados" in result

    if not has_open_listed and has_empty_msg:
        ok("_fetch_creator_context: todos cerrados → muestra 'Sin tickets abiertos'")
    elif has_open_listed:
        fail(
            "_fetch_creator_context: todos cerrados → sin listado",
            f"Tickets cerrados aparecen en el contexto: {'TCK-0002' if 'TCK-0002' in result else ''} {'TCK-0003' if 'TCK-0003' in result else ''}"
        )
    else:
        fail(
            "_fetch_creator_context: todos cerrados → mensaje correcto",
            f"Contexto inesperado: {result!r}"
        )


def test_fetch_context_stage_false_treated_as_open():
    """
    Si stage_id es False (ticket sin stage asignado), no debe ser filtrado
    como cerrado — se asume abierto hasta saber más.
    """
    ticket_no_stage = dict(TICKET_OPEN)
    ticket_no_stage["name"] = "TCK-0099"
    ticket_no_stage["stage_id"] = False  # Sin stage asignado

    result = _run_fetch_context([ticket_no_stage])

    if "TCK-0099" in result:
        ok("_fetch_creator_context: stage_id=False se trata como abierto")
    else:
        fail(
            "_fetch_creator_context: stage_id=False tratado como abierto",
            f"Ticket sin stage fue filtrado. Contexto: {result!r}"
        )


test_fetch_context_excludes_resolved_tickets()
test_fetch_context_excludes_closed_tickets()
test_fetch_context_includes_open_tickets()
test_fetch_context_all_closed_shows_no_open_tickets()
test_fetch_context_stage_false_treated_as_open()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 3 — Verificar comportamiento actual (documentar el bug)
# Estos tests confirman que el bug EXISTE en el código actual.
# Después del fix estos tests quedarán obsoletos y se pueden eliminar.
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 3: Confirmación del bug actual (deben FALLAR pre-fix) ─────")


def test_confirm_bug_b_missing_filter():
    """
    Confirma que el bug existe: get_tickets_by_creator actualmente NO
    incluye is_close en el domain.
    Este test debe FALLAR después del fix (lo que confirma que se corrigió).
    """
    from adapters.odoo_adapter import OdooAdapter

    adapter = OdooAdapter.__new__(OdooAdapter)
    captured = {}

    def fake_call_kw(model, method, args, kwargs=None):
        if method == "search_read":
            captured["domain"] = str(args[0])
        return []

    adapter._call_kw = fake_call_kw
    adapter.get_tickets_by_creator(user_id=1)

    domain_str = captured.get("domain", "")
    bug_exists = "is_close" not in domain_str

    if bug_exists:
        # El bug existe — esto es lo esperado ANTES del fix
        print(f"  INFO  Bug-B confirmado: is_close ausente en domain de get_tickets_by_creator")
        print(f"        Domain actual: {domain_str[:120]}")
    else:
        # El fix ya fue aplicado
        print(f"  INFO  Bug-B ya fue corregido (is_close presente en domain)")

    # No marcamos pass/fail aquí — es solo informativo
    results.append((True, "Bug-B documentado (informativo)"))


test_confirm_bug_b_missing_filter()


# ─────────────────────────────────────────────────────────────────────────────
# Resumen final
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
passed = sum(1 for ok_, _ in results if ok_)
failed = sum(1 for ok_, _ in results if not ok_)
total = len(results)
print(f"  Resultado: {passed}/{total} pasaron  |  {failed} fallaron")
if failed == 0:
    print("  ✓ Los bugs fueron corregidos — todos los tests pasan.")
else:
    print(f"  ✗ {failed} tests fallan — los bugs aún existen o hay una regresión.")
print("─" * 60)

sys.exit(0 if failed == 0 else 1)
