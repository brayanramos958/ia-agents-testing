"""
Ticket operation tools for the LangGraph agent.

Tools delegate to ITicketPort — they never call any HTTP endpoint directly.
Each role gets a different subset via get_*_tools() functions.

Delete is implemented here but EXCLUDED from all tool lists.

ARCHITECTURE NOTE (Fase 8 — async migration):
    All tools are ``async def`` so LangGraph 1.1+ can execute them directly
    in the event loop without ``run_in_executor`` (no thread pool bottleneck).
    The backing ``ITicketPort`` methods are also ``async def``.

    Catalog resolution helpers (``_resolve_id``) are also async because they
    call ``_port.get_*_catalogs()`` which is now async.
"""

import json
import logging
from typing import Optional, Union

from langchain_core.tools import tool
from tenacity import retry, stop_after_attempt, wait_exponential

from core.context import current_thread_id as _thread_id_var
from core.events import emit
from core.security import frame_external_data
from ports.rag_port import IRAGPort
from ports.ticket_port import ITicketPort
from core.validation import (
    validate_tool,
    CreateTicketSchema,
    UpdateTicketSchema,
    GetTicketDetailSchema,
    AssignTicketSchema,
    ApproveTicketSchema,
    RejectTicketSchema,
    ReopenTicketSchema,
    ResolveTicketSchema,
)

logger = logging.getLogger(__name__)

# Patrón Resiliencia: Reintenta llamadas de red (Odoo/FastAPI) hasta 3 veces
# ante intermitencias. Espera de forma exponencial (2s, 4s, 8s).
backend_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)

# Injected at application startup via set_ticket_port()
_port: ITicketPort | None = None
_rag_port: IRAGPort | None = None


async def _resolve_id(value: str, field: str, catalog_fn) -> int:
    """
    Resolve a catalog field value to a numeric ID.

    - If value is already numeric: converts and returns directly (zero overhead).
    - If value is a name string: searches the catalog by name (case-insensitive)
      and returns the matching ID without an extra LLM round-trip.
    - If the name is not found: raises ``ValueError`` with the available options.

    Args:
        value: Catalog value (numeric ID or name string).
        field: Field name for error messages.
        catalog_fn: Async function returning the catalog list.

    Returns:
        int: Resolved catalog ID.

    Raises:
        ValueError: If the value cannot be resolved.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        items = await catalog_fn()
        name_lower = str(value).lower().strip()
        match = next(
            (item for item in items if item.get("name", "").lower().strip() == name_lower),
            None,
        )
        if match:
            return match["id"]
        available = [item.get("name", "") for item in items]
        raise ValueError(
            f"'{field}': '{value}' no es un ID numérico ni coincide con ningún valor "
            f"del catálogo. Opciones disponibles: {available}"
        )


def _slim_ticket(t: dict) -> dict:
    """Return only key fields for list views — keeps tool responses compact."""
    stage = t.get("stage_id")
    return {
        "id": t.get("id"),
        "name": t.get("name"),
        "asunto": t.get("asunto"),
        "stage": stage[1] if isinstance(stage, list) and len(stage) > 1 else stage,
        "urgency": t.get("urgency_id"),
    }


def _safe_uid(llm_provided) -> int:
    """
    Return the authenticated user_id from the request context.

    Falls back to the LLM-provided value only in test environments where
    the context var was never set (default=0 signals no active request).
    This prevents a malicious prompt from making the LLM impersonate another user.

    Args:
        llm_provided: User ID from the LLM tool arguments.

    Returns:
        int: Authenticated user ID.
    """
    from core.context import current_user_id as _uid_var
    ctx = _uid_var.get()
    return ctx if ctx else int(llm_provided)


def set_ticket_port(port: ITicketPort) -> None:
    """Inject the ticket port at application startup."""
    global _port
    _port = port


def set_rag_port_for_tickets(rag_port: IRAGPort) -> None:
    """Provide RAG access so resolve_ticket can update the knowledge base."""
    global _rag_port
    _rag_port = rag_port


# ── Creator tools ─────────────────────────────────────────────────────────────

@tool
@backend_retry
@validate_tool(CreateTicketSchema)
async def create_ticket(
    asunto: str,
    ticket_type_id: Union[int, str],
    category_id: Union[int, str],
    urgency_id: Union[int, str],
    impact_id: Union[int, str],
    priority_id: Union[int, str],
    user_id: Union[int, str],
    descripcion: str = "",
    subcategory_id: Optional[Union[int, str]] = None,
    element_id: Optional[Union[int, str]] = None,
    system_equipment: str = "",
) -> dict:
    """
    Create a new support ticket.

    IMPORTANT: Always call ``suggest_solution`` BEFORE this tool.
    Only call this if the user confirmed no existing solution worked,
    or if no solution was found.

    Args:
        asunto: Short title of the ticket.
        descripcion: Full problem description.
        ticket_type_id: ID from ``get_ticket_types()``.
        category_id: L1 category ID from ``get_categories()``.
        urgency_id: ID from ``get_urgency_levels()``.
        impact_id: ID from ``get_impact_levels()``.
        priority_id: ID from ``get_priority_levels()``.
        user_id: Current user's ID.
        subcategory_id: L2 category ID (optional).
        element_id: L3 category ID (optional).
        system_equipment: Device or software name affected (optional).
    """
    # ── Fase 1.6: Emit creation_started event (decoupled from metrics) ────
    from core.context import current_user_id as _uid_var, current_user_role as _role_var
    uid_for_event = _uid_var.get() or _safe_uid(user_id)
    role_for_event = _role_var.get("creador")
    thread_for_event = _thread_id_var.get(None)

    # Metrics listens for "ticket.creation_started" and creates its own row.
    # We don't know the creation_event_id here — metrics generates it.
    emit(
        "ticket.creation_started",
        user_id=uid_for_event,
        user_role=role_for_event,
        thread_id=thread_for_event,
        session_id=thread_for_event,
    )

    payload = {
        "asunto": asunto,
        "descripcion": descripcion,
        "ticket_type_id": await _resolve_id(ticket_type_id, "ticket_type_id", _port.get_ticket_types),
        "category_id":    await _resolve_id(category_id,    "category_id",    _port.get_categories),
        "subcategory_id": await _resolve_id(subcategory_id, "subcategory_id", _port.get_categories) if subcategory_id else None,
        "element_id":     await _resolve_id(element_id,     "element_id",     _port.get_categories) if element_id     else None,
        "urgency_id":     await _resolve_id(urgency_id,     "urgency_id",     _port.get_urgency_levels),
        "impact_id":      await _resolve_id(impact_id,      "impact_id",      _port.get_impact_levels),
        "priority_id":    await _resolve_id(priority_id,    "priority_id",    _port.get_priority_levels),
        "system_equipment": system_equipment,
    }
    try:
        result = await _port.create_ticket(payload, _safe_uid(user_id))
    except Exception as exc:
        # ── Fase 1.6: Emit creation_abandoned event on exception ──────────────
        emit("ticket.creation_abandoned", user_id=uid_for_event, thread_id=thread_for_event)
        raise

    # ── Fase 1.6: Emit creation_completed event on success ──────────────────
    if isinstance(result, dict) and result.get("success"):
        ticket_id = result.get("ticket_id") or result.get("id")
        ticket_name = result.get("name") or result.get("ticket_name") or ""
        duplicate_of = result.get("duplicate_of_ticket_id")  # OdooAdapter may set this (UX-4)
        emit(
            "ticket.creation_completed",
            user_id=uid_for_event,
            ticket_id=int(ticket_id) if ticket_id else 0,
            ticket_name=str(ticket_name),
            duplicate_of_ticket_id=duplicate_of,
        )
    else:
        # success=False or unexpected shape — mark as abandoned
        emit("ticket.creation_abandoned", user_id=uid_for_event, thread_id=thread_for_event)

    return result


@tool
@backend_retry
async def get_my_created_tickets(user_id: Union[int, str]) -> list:
    """
    Return the most recent tickets created by the current user (up to 10).

    Shows: ticket name, subject, stage, urgency.
    For full details on a specific ticket, use ``get_ticket_detail``.
    """
    tickets = await _port.get_tickets_by_creator(_safe_uid(user_id))
    limited = tickets[-10:] if len(tickets) > 10 else tickets
    result = [_slim_ticket(t) for t in limited]
    if len(tickets) > 10:
        result.append({"_note": f"Showing last 10 of {len(tickets)} tickets."})
    return frame_external_data(result, "tickets (creador)")


# ── Resolver tools ────────────────────────────────────────────────────────────

@tool
@backend_retry
async def get_my_assigned_tickets(user_id: Union[int, str]) -> list:
    """
    Return tickets currently assigned to the current resolver (up to 10).

    Shows: ticket name, subject, stage, urgency.
    For full details on a specific ticket, use ``get_ticket_detail``.
    """
    tickets = await _port.get_tickets_by_assignee(_safe_uid(user_id))
    limited = tickets[-10:] if len(tickets) > 10 else tickets
    result = [_slim_ticket(t) for t in limited]
    if len(tickets) > 10:
        result.append({"_note": f"Showing last 10 of {len(tickets)} tickets."})
    return frame_external_data(result, "tickets (resueltor)")


@tool
@backend_retry
@validate_tool(ResolveTicketSchema)
async def resolve_ticket(
    ticket_id: Union[int, str],
    motivo_resolucion: str,
    causa_raiz: str,
    user_id: Union[int, str],
) -> dict:
    """
    Mark a ticket as resolved.

    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID.
        motivo_resolucion: Full description of how the problem was resolved.
        causa_raiz: Root cause explanation.
        user_id: Current resolver's user ID.
    """
    uid = _safe_uid(user_id)
    ticket_id_int = int(ticket_id)
    result = await _port.resolve_ticket(ticket_id_int, motivo_resolucion, causa_raiz, uid)

    # RAG update is best-effort — must never cause the tool to report failure
    # when the ticket was already resolved successfully in Odoo.
    if result.get("success") and _rag_port:
        try:
            ticket = await _port.get_ticket_detail(ticket_id_int, uid, "resueltor")
            await _rag_port.add_resolved_ticket(
                ticket_id=ticket_id_int,
                ticket_name=ticket.get("name") or f"TCK-{ticket_id_int:04d}",
            ticket_type=ticket.get("ticket_type") or ticket.get("tipo_requerimiento", ""),
            category=ticket.get("category") or ticket.get("categoria", ""),
            description=ticket.get("descripcion", ""),
            motivo_resolucion=motivo_resolucion,
            causa_raiz=causa_raiz,
        )
        except Exception as _rag_err:
            # RAG update is non-critical: the ticket was already resolved
            # successfully in Odoo. Log and continue.
            import logging
            _rag_log = logging.getLogger(__name__)
            _rag_log.warning(
                "resolve_ticket: RAG update failed (ticket=%s), continuing: %s",
                ticket_id_int, _rag_err,
            )

    return result


# ── Shared tools (all roles) ──────────────────────────────────────────────────

@tool
@backend_retry
@validate_tool(GetTicketDetailSchema)
async def get_ticket_detail(
    ticket_id: Union[int, str],
    user_id: Union[int, str],
    user_role: str,
) -> dict:
    """
    Return full details of a specific ticket.

    Includes: all fields, SLA status, deadline, stage, assignment info.
    After calling this, proactively call ``suggest_solution`` using the
    ticket's description and category.
    """
    return frame_external_data(
        await _port.get_ticket_detail(int(ticket_id), _safe_uid(user_id), user_role),
        "tickets (detalle)",
    )


@tool
@backend_retry
@validate_tool(UpdateTicketSchema)
async def update_ticket(
    ticket_id: Union[int, str],
    fields: dict,
    user_id: Union[int, str],
) -> dict:
    """
    Update specific fields of a ticket.

    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID.
        fields: Dict of fields to update using Odoo technical names.
                Example: ``{"asunto": "New title", "system_equipment": "Laptop HP"}``.
        user_id: Current user's ID.
    """
    if not isinstance(fields, dict):
        try:
            fields = json.loads(fields)
        except (json.JSONDecodeError, TypeError):
            return {"success": False, "error": "Invalid fields: must be a dict"}
    return await _port.update_ticket(int(ticket_id), fields, _safe_uid(user_id))


# ── Supervisor tools ──────────────────────────────────────────────────────────

@tool
@backend_retry
async def get_all_tickets(filters: Optional[dict] = None) -> list:
    """
    Return tickets in the system for supervisors (up to 15 most recent).

    Optional filters as a Python dict — LangChain handles JSON serialization.

    Examples of valid filter dicts:
        ``{"stage_id": 1}``                       # by stage
        ``{"approval_status": "pending"}``        # by approval status
        ``{"urgency_id": 3}``                     # by urgency
        ``{"asignado_a": None}``                  # unassigned
        ``{"stage_id": 1, "urgency_id": 3}``      # combined

    For full details on a specific ticket, use ``get_ticket_detail``.
    """
    if filters is None:
        filters = {}
    if not isinstance(filters, dict):
        # If the LLM passed a string, try to parse it; otherwise ignore.
        try:
            filters = json.loads(filters)
        except (json.JSONDecodeError, TypeError):
            filters = {}
    tickets = await _port.get_all_tickets(filters)
    limited = tickets[-15:] if len(tickets) > 15 else tickets
    result = [_slim_ticket(t) for t in limited]
    if len(tickets) > 15:
        result.append({"_note": f"Showing last 15 of {len(tickets)} tickets. Use filters to narrow results."})
    return frame_external_data(result, "tickets (supervisor)")


@tool
@backend_retry
@validate_tool(AssignTicketSchema)
async def assign_ticket(
    ticket_id: Union[int, str],
    assignee_id: Union[int, str],
    agent_group_id: Union[int, str],
    user_id: Union[int, str],
) -> dict:
    """
    Assign a ticket to a resolver agent.

    Args:
        ticket_id: Numeric ticket ID.
        assignee_id: ID of the resolver to assign (from ``get_resolvers``).
        agent_group_id: ID of the agent group (from ``get_agent_groups``).
        user_id: Current supervisor's user ID.
    """
    return await _port.assign_ticket(
        int(ticket_id), int(assignee_id), int(agent_group_id), _safe_uid(user_id),
    )


@tool
@backend_retry
@validate_tool(ReopenTicketSchema)
async def reopen_ticket(
    ticket_id: Union[int, str],
    reason: str,
    user_id: Union[int, str],
) -> dict:
    """
    Reopen a resolved or closed ticket.

    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID.
        reason: Reason for reopening the ticket.
        user_id: Current supervisor's user ID.
    """
    return await _port.reopen_ticket(int(ticket_id), reason, _safe_uid(user_id))


@tool
@backend_retry
@validate_tool(ApproveTicketSchema)
async def approve_ticket(
    ticket_id: Union[int, str],
    user_id: Union[int, str],
) -> dict:
    """
    Approve a pending ticket so the resolver can proceed with it.

    Only valid for tickets with ``approval_status: "pending"``.
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID.
        user_id: Current supervisor's user ID.
    """
    return await _port.approve_ticket(int(ticket_id), _safe_uid(user_id))


@tool
@backend_retry
@validate_tool(RejectTicketSchema)
async def reject_ticket(
    ticket_id: Union[int, str],
    reason: str,
    user_id: Union[int, str],
) -> dict:
    """
    Reject a pending ticket. The resolver will be notified it does not proceed.

    Only valid for tickets with ``approval_status: "pending"``.
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID.
        reason: Clear explanation of why the ticket is rejected.
        user_id: Current supervisor's user ID.
    """
    return await _port.reject_ticket(int(ticket_id), reason, _safe_uid(user_id))


# ── Delete — implemented but excluded from all tool lists ─────────────────────

async def delete_ticket(ticket_id: str, user_id: str) -> dict:
    """
    Permanently delete a ticket. Supervisor only.

    SECURITY: This function is intentionally excluded from all role tool
    lists (see :func:`get_supervisor_tools`). To enable deletion:
    1. Add the ``@tool`` decorator
    2. Include it in ``get_supervisor_tools()`` AFTER an authorization
       layer is implemented.
    """
    return await _port.delete_ticket(int(ticket_id), int(user_id))


# ── Role-keyed tool sets ──────────────────────────────────────────────────────

def get_creator_tools() -> list:
    """Tools available to users with role ``'creador'``."""
    return [
        create_ticket,
        get_my_created_tickets,
        get_ticket_detail,
        update_ticket,
    ]


def get_resolver_tools() -> list:
    """Tools available to users with role ``'resueltor'``."""
    return [
        get_my_assigned_tickets,
        get_ticket_detail,
        resolve_ticket,
        update_ticket,
    ]


def get_supervisor_tools() -> list:
    """
    Tools available to users with role ``'supervisor'``.

    Note: ``delete_ticket`` is NOT included — see SECURITY comment above.
    """
    return [
        get_all_tickets,
        get_ticket_detail,
        assign_ticket,
        reopen_ticket,
        approve_ticket,
        reject_ticket,
    ]
