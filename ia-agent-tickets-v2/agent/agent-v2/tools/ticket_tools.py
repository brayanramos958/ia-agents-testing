"""
Ticket operation tools for the LangGraph agent.

Tools delegate to ITicketPort — they never call any HTTP endpoint directly.
Each role gets a different subset via get_*_tools() functions.

Delete is implemented here but EXCLUDED from all tool lists.
"""

import json
from langchain_core.tools import tool
from ports.ticket_port import ITicketPort
from ports.rag_port import IRAGPort

# Injected at application startup via set_ticket_port()
_port: ITicketPort = None
_rag_port: IRAGPort = None


def set_ticket_port(port: ITicketPort) -> None:
    global _port
    _port = port


def set_rag_port_for_tickets(rag_port: IRAGPort) -> None:
    """Provides RAG access so resolve_ticket can update the knowledge base."""
    global _rag_port
    _rag_port = rag_port


# ── Creator tools ─────────────────────────────────────────────────────────────

@tool
def create_ticket(
    asunto: str,
    descripcion: str,
    ticket_type_id: str,
    category_id: str,
    urgency_id: str,
    impact_id: str,
    priority_id: str,
    user_id: str,
    subcategory_id: str = None,
    element_id: str = None,
    system_equipment: str = "",
) -> dict:
    """
    Creates a new support ticket.
    IMPORTANT: Always call suggest_solution_before_ticket BEFORE this tool.
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
        system_equipment: Device or software name (optional)
    """
    payload = {
        "asunto": asunto,
        "descripcion": descripcion,
        "ticket_type_id": int(ticket_type_id),
        "category_id": int(category_id),
        "subcategory_id": int(subcategory_id) if subcategory_id else None,
        "element_id": int(element_id) if element_id else None,
        "urgency_id": int(urgency_id),
        "impact_id": int(impact_id),
        "priority_id": int(priority_id),
        "system_equipment": system_equipment,
    }
    return _port.create_ticket(payload, int(user_id))


@tool
def get_my_created_tickets(user_id: str) -> list:
    """
    Returns all tickets created by the current user.
    Shows: ticket name, subject, stage, urgency, creation date.
    """
    return _port.get_tickets_by_creator(int(user_id))


# ── Resolver tools ────────────────────────────────────────────────────────────

@tool
def get_my_assigned_tickets(user_id: str) -> list:
    """
    Returns all tickets currently assigned to the current resolver.
    Shows: ticket name, subject, stage, urgency, requestor, creation date.
    """
    return _port.get_tickets_by_assignee(int(user_id))


@tool
def resolve_ticket(
    ticket_id: str,
    motivo_resolucion: str,
    causa_raiz: str,
    user_id: str,
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

    # Update the knowledge base in real time so future tickets benefit immediately
    if result.get("success") and _rag_port:
        ticket = _port.get_ticket_detail(int(ticket_id), int(user_id), "resueltor")
        _rag_port.add_resolved_ticket(
            ticket_id=int(ticket_id),
            ticket_name=ticket.get("name", f"TCK-{ticket_id:04d}"),
            ticket_type=ticket.get("ticket_type", ""),
            category=ticket.get("category", ""),
            description=ticket.get("descripcion", ""),
            motivo_resolucion=motivo_resolucion,
        )

    return result


# ── Shared tools (all roles) ──────────────────────────────────────────────────

@tool
def get_ticket_detail(ticket_id: str, user_id: str, user_role: str) -> dict:
    """
    Returns full details of a specific ticket.
    Includes: all fields, SLA status, deadline, stage, assignment info.

    After calling this, proactively call suggest_solution_before_ticket
    using the ticket's description and category.
    """
    return _port.get_ticket_detail(int(ticket_id), int(user_id), user_role)


@tool
def update_ticket(ticket_id: str, fields_json: str, user_id: str) -> dict:
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
def get_all_tickets(filters_json: str = "{}") -> list:
    """
    Returns all tickets in the system. For supervisors only.
    Optional filters as JSON string.
    Example: '{"stage_id": 1}' to filter by stage.
    """
    try:
        filters = json.loads(filters_json)
    except json.JSONDecodeError:
        filters = {}
    return _port.get_all_tickets(filters)


@tool
def assign_ticket(
    ticket_id: str,
    assignee_id: str,
    agent_group_id: str,
    user_id: str,
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
def reopen_ticket(ticket_id: str, reason: str, user_id: str) -> dict:
    """
    Reopens a resolved or closed ticket.
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID
        reason: Reason for reopening the ticket
        user_id: Current supervisor's user ID
    """
    return _port.reopen_ticket(int(ticket_id), reason, int(user_id))


# ── Delete — implemented but excluded from all tool lists ─────────────────────

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
    ]
