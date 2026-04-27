"""
Ticket operation tools for the LangGraph agent.

Tools delegate to ITicketPort — they never call any HTTP endpoint directly.
Each role gets a different subset via get_*_tools() functions.

Delete is implemented here but EXCLUDED from all tool lists.
"""

import json
from typing import Optional, Union

from langchain_core.tools import tool
from tenacity import retry, stop_after_attempt, wait_exponential
from ports.ticket_port import ITicketPort
from ports.rag_port import IRAGPort

# Patrón Resiliencia: Reintenta llamadas de red (Odoo/FastAPI) hasta 3 veces 
# ante intermitencias. Espera de forma exponencial (2s, 4s, 8s).
backend_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True
)

# Injected at application startup via set_ticket_port()
_port: ITicketPort = None
_rag_port: IRAGPort = None


def _resolve_id(value: str, field: str, catalog_fn) -> int:
    """
    Resolves a catalog field value to a numeric ID.

    - If value is already numeric: converts and returns directly (zero overhead).
    - If value is a name string: searches the catalog by name (case-insensitive)
      and returns the matching ID without an extra LLM round-trip.
    - If the name is not found in the catalog: raises ValueError with the
      available options so the error is actionable.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        items = catalog_fn()
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
    """Returns only key fields for list views — keeps tool responses compact."""
    stage = t.get("stage_id")
    return {
        "id":      t.get("id"),
        "name":    t.get("name"),
        "asunto":  t.get("asunto"),
        "stage":   stage[1] if isinstance(stage, list) and len(stage) > 1 else stage,
        "urgency": t.get("urgency_id"),
    }


def set_ticket_port(port: ITicketPort) -> None:
    global _port
    _port = port


def set_rag_port_for_tickets(rag_port: IRAGPort) -> None:
    """Provides RAG access so resolve_ticket can update the knowledge base."""
    global _rag_port
    _rag_port = rag_port


# ── Creator tools ─────────────────────────────────────────────────────────────

@tool
@backend_retry
def create_ticket(
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
    Creates a new support ticket.
    IMPORTANT: Always call suggest_solution BEFORE this tool.
    Only call this if the user confirmed no existing solution worked,
    or if no solution was found.

    Args:
        asunto: Short title of the ticket (required)
        descripcion: Full problem description (required)
        ticket_type_id: ID from get_ticket_types() (required)
        category_id: L1 category ID from get_categories() (required)
        urgency_id: ID from get_urgency_levels() (required)
        impact_id: ID from get_impact_levels() (required)
        priority_id: ID from get_priority_levels() (required)
        user_id: Current user's ID (required)
        subcategory_id: L2 category ID (optional)
        element_id: L3 category ID (optional)
        system_equipment: Device or software name affected (optional).
                         The adapter appends this to descripcion — it is not
                         a standalone Odoo field.
    """
    payload = {
        "asunto": asunto,
        "descripcion": descripcion,
        "ticket_type_id": _resolve_id(ticket_type_id, "ticket_type_id", _port.get_ticket_types),
        "category_id":    _resolve_id(category_id,    "category_id",    _port.get_categories),
        "subcategory_id": _resolve_id(subcategory_id, "subcategory_id", _port.get_categories) if subcategory_id else None,
        "element_id":     _resolve_id(element_id,     "element_id",     _port.get_categories) if element_id     else None,
        "urgency_id":     _resolve_id(urgency_id,     "urgency_id",     _port.get_urgency_levels),
        "impact_id":      _resolve_id(impact_id,      "impact_id",      _port.get_impact_levels),
        "priority_id":    _resolve_id(priority_id,    "priority_id",    _port.get_priority_levels),
        "system_equipment": system_equipment,
    }
    return _port.create_ticket(payload, int(user_id))


@tool
@backend_retry
def get_my_created_tickets(user_id: Union[int, str]) -> list:
    """
    Returns the most recent tickets created by the current user (up to 10).
    Shows: ticket name, subject, stage, urgency.
    For full details on a specific ticket, use get_ticket_detail.
    """
    tickets = _port.get_tickets_by_creator(int(user_id))
    limited = tickets[-10:] if len(tickets) > 10 else tickets
    result = [_slim_ticket(t) for t in limited]
    if len(tickets) > 10:
        result.append({"_note": f"Showing last 10 of {len(tickets)} tickets."})
    return result


# ── Resolver tools ────────────────────────────────────────────────────────────

@tool
@backend_retry
def get_my_assigned_tickets(user_id: Union[int, str]) -> list:
    """
    Returns tickets currently assigned to the current resolver (up to 10).
    Shows: ticket name, subject, stage, urgency.
    For full details on a specific ticket, use get_ticket_detail.
    """
    tickets = _port.get_tickets_by_assignee(int(user_id))
    limited = tickets[-10:] if len(tickets) > 10 else tickets
    result = [_slim_ticket(t) for t in limited]
    if len(tickets) > 10:
        result.append({"_note": f"Showing last 10 of {len(tickets)} tickets."})
    return result


@tool
@backend_retry
def resolve_ticket(
    ticket_id: Union[int, str],
    motivo_resolucion: str,
    causa_raiz: str,
    user_id: Union[int, str],
) -> dict:
    """
    Marks a ticket as resolved.
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID
        motivo_resolucion: Full description of how the problem was resolved
        causa_raiz: Root cause explanation (what caused the problem)
        user_id: Current resolver's user ID
    """
    result = _port.resolve_ticket(int(ticket_id), motivo_resolucion, causa_raiz, int(user_id))

    # Update the knowledge base in real time so future tickets benefit immediately.
    # causa_raiz is passed so root-cause patterns are also searchable via RAG.
    if result.get("success") and _rag_port:
        ticket = _port.get_ticket_detail(int(ticket_id), int(user_id), "resueltor")
        _rag_port.add_resolved_ticket(
            ticket_id=int(ticket_id),
            ticket_name=ticket.get("name") or f"TCK-{int(ticket_id):04d}",
            ticket_type=ticket.get("ticket_type") or ticket.get("tipo_requerimiento", ""),
            category=ticket.get("category") or ticket.get("categoria", ""),
            description=ticket.get("descripcion", ""),
            motivo_resolucion=motivo_resolucion,
            causa_raiz=causa_raiz,
        )

    return result


# ── Shared tools (all roles) ──────────────────────────────────────────────────

@tool
@backend_retry
def get_ticket_detail(ticket_id: Union[int, str], user_id: Union[int, str], user_role: str) -> dict:
    """
    Returns full details of a specific ticket.
    Includes: all fields, SLA status, deadline, stage, assignment info.

    After calling this, proactively call suggest_solution
    using the ticket's description and category.
    """
    return _port.get_ticket_detail(int(ticket_id), int(user_id), user_role)


@tool
@backend_retry
def update_ticket(ticket_id: Union[int, str], fields_json: str, user_id: Union[int, str]) -> dict:
    """
    Updates specific fields of a ticket.
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID
        fields_json: JSON string of fields to update using Odoo technical names.
                     Example: '{"asunto": "New title", "system_equipment": "Laptop HP"}'
        user_id: Current user's ID
    """
    try:
        fields = json.loads(fields_json)
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON in fields_json: {e}"}
    return _port.update_ticket(int(ticket_id), fields, int(user_id))


# ── Supervisor tools ──────────────────────────────────────────────────────────

@tool
@backend_retry
def get_all_tickets(filters_json: str = "{}") -> list:
    """
    Returns tickets in the system for supervisors (up to 15 most recent).
    Optional filters as JSON string. Example: '{"stage_id": 1}' to filter by stage.
    For full details on a specific ticket, use get_ticket_detail.
    """
    try:
        filters = json.loads(filters_json)
    except json.JSONDecodeError:
        filters = {}
    tickets = _port.get_all_tickets(filters)
    limited = tickets[-15:] if len(tickets) > 15 else tickets
    result = [_slim_ticket(t) for t in limited]
    if len(tickets) > 15:
        result.append({"_note": f"Showing last 15 of {len(tickets)} tickets. Use filters to narrow results."})
    return result


@tool
@backend_retry
def assign_ticket(
    ticket_id: Union[int, str],
    assignee_id: Union[int, str],
    agent_group_id: Union[int, str],
    user_id: Union[int, str],
) -> dict:
    """
    Assigns a ticket to a resolver agent.
    Always show the list of resolvers (get_resolvers) before calling this.
    Confirm with the user before assigning.

    Args:
        ticket_id: Numeric ticket ID
        assignee_id: ID of the resolver to assign (from get_resolvers)
        agent_group_id: ID of the agent group (from get_agent_groups)
        user_id: Current supervisor's user ID
    """
    return _port.assign_ticket(int(ticket_id), int(assignee_id), int(agent_group_id), int(user_id))


@tool
@backend_retry
def reopen_ticket(ticket_id: Union[int, str], reason: str, user_id: Union[int, str]) -> dict:
    """
    Reopens a resolved or closed ticket.
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID
        reason: Reason for reopening the ticket
        user_id: Current supervisor's user ID
    """
    return _port.reopen_ticket(int(ticket_id), reason, int(user_id))


@tool
@backend_retry
def approve_ticket(ticket_id: Union[int, str], user_id: Union[int, str]) -> dict:
    """
    Approves a pending ticket so the resolver can proceed with it.
    Only valid for tickets with approval_status: "pending".
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID
        user_id: Current supervisor's user ID
    """
    return _port.approve_ticket(int(ticket_id), int(user_id))


@tool
@backend_retry
def reject_ticket(
    ticket_id: Union[int, str],
    reason: str,
    user_id: Union[int, str],
) -> dict:
    """
    Rejects a pending ticket. The resolver will be notified it does not proceed.
    Only valid for tickets with approval_status: "pending".
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID
        reason: Clear explanation of why the ticket is rejected
        user_id: Current supervisor's user ID
    """
    return _port.reject_ticket(int(ticket_id), reason, int(user_id))


# ── Delete — implemented but excluded from all tool lists ─────────────────────

@backend_retry
def delete_ticket(ticket_id: str, user_id: str) -> dict:
    """Permanently deletes a ticket. Supervisor only."""
    return _port.delete_ticket(int(ticket_id), int(user_id))

# SECURITY: delete_ticket is implemented above but intentionally excluded from
# all role tool lists (get_creator_tools, get_resolver_tools, get_supervisor_tools).
# To enable deletion: add the @tool decorator to delete_ticket and include it
# in get_supervisor_tools() AFTER an authorization layer is implemented.


# ── Role-keyed tool sets ──────────────────────────────────────────────────────

def get_creator_tools() -> list:
    """Tools available to users with role 'creador'."""
    return [
        create_ticket,
        get_my_created_tickets,
        get_ticket_detail,
        update_ticket,
    ]


def get_resolver_tools() -> list:
    """Tools available to users with role 'resueltor'."""
    return [
        get_my_assigned_tickets,
        get_ticket_detail,
        resolve_ticket,
        update_ticket,
    ]


def get_supervisor_tools() -> list:
    """
    Tools available to users with role 'supervisor'.
    Note: delete_ticket is NOT included — see SECURITY comment above.
    """
    return [
        get_all_tickets,
        get_ticket_detail,
        assign_ticket,
        reopen_ticket,
        approve_ticket,
        reject_ticket,
    ]
