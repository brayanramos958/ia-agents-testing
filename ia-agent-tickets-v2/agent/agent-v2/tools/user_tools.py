"""
User and catalog query tools.

Provides the LLM with valid options for FK fields so it can present
accurate choices to users instead of guessing or inventing values.

Injected port is the same ITicketPort used by ticket_tools.
"""

from langchain_core.tools import tool
from ports.ticket_port import ITicketPort
from typing import Optional, Union
from pydantic import BaseModel, field_validator

_port: ITicketPort = None


def set_user_port(port: ITicketPort) -> None:
    global _port
    _port = port


@tool
async def get_resolvers() -> list:
    """
    Returns all available resolver agents.
    Use this before assigning a ticket to show the supervisor valid options.
    Each item contains: id, name (and role info if available).
    """
    return await _port.get_resolvers()


@tool
async def get_agent_groups() -> list:
    """
    Returns all available agent groups (support teams/levels).
    Use this before assigning a ticket to a group.
    Each item contains: id, name.
    """
    return await _port.get_agent_groups()


@tool
async def get_ticket_types() -> list:
    """
    Returns all valid ticket types.
    Examples: Incidente, Solicitud, Problema, Cambio.
    Each item contains: id, name.
    Use the id when calling create_ticket (ticket_type_id field).
    """
    return await _port.get_ticket_types()


class _CategoriesInput(BaseModel):
    parent_id: Optional[Union[int, str]] = None

    @field_validator("parent_id", mode="before")
    @classmethod
    def _normalize(cls, v):
        if v is None:
            return None
        if isinstance(v, str) and v.lower() in ("null", "none", ""):
            return None
        if isinstance(v, str):
            try:
                return int(v)
            except ValueError:
                return None
        return v


@tool(args_schema=_CategoriesInput)
async def get_categories(parent_id: Optional[int] = None) -> list:
    """
    Returns categories from the 3-level hierarchy.

    Usage:
        get_categories()              → Level 1 categories (top level)
        get_categories(parent_id=1)   → Level 2 subcategories under category 1
        get_categories(parent_id=10)  → Level 3 elements under subcategory 10

    Always call without parent_id first, then drill down based on user selection.
    Each item contains: id, name, full_name, level.
    Use the id from the deepest available level when calling create_ticket.
    Pass null (not the string "null") to get top-level categories.
    """
    return await _port.get_categories(parent_id)


@tool
async def get_urgency_levels() -> list:
    """
    Returns all valid urgency levels for tickets.
    Each item contains: id, name.
    Use the id when calling create_ticket (urgency_id field).
    """
    return await _port.get_urgency_levels()


@tool
async def get_impact_levels() -> list:
    """
    Returns all valid impact levels for tickets.
    Each item contains: id, name.
    Use the id when calling create_ticket (impact_id field).
    """
    return await _port.get_impact_levels()


@tool
async def get_priority_levels() -> list:
    """
    Returns all valid priority levels for tickets.
    Each item contains: id, name.
    Priority is normally inferred from urgency × impact.
    Use the id when calling create_ticket (priority_id field).
    """
    return await _port.get_priority_levels()


@tool
async def get_stages() -> list:
    """
    Returns all workflow stages with their flags.
    Each item contains: id, name, is_start, is_resolve, is_close, is_pause.
    Useful for supervisors filtering tickets by stage.
    """
    return await _port.get_stages()


@tool
async def get_origins() -> list:
    """
    Returns all available ticket origins (FASE 3).
    Examples: Email, Teléfono, Web, Presencial, Bot SARA.
    Each item contains: id, name, description.
    Use the id when calling create_ticket (origin_id field, optional).
    """
    return await _port.get_origins()


def get_catalog_tools() -> list:
    """All catalog query tools — included in every role."""
    return [
        get_resolvers,
        get_agent_groups,
        get_ticket_types,
        get_categories,
        get_urgency_levels,
        get_impact_levels,
        get_priority_levels,
        get_stages,
        get_origins,  # FASE 3: catálogo de orígenes
    ]
