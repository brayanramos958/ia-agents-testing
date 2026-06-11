"""
User and catalog query tools.

Provides the LLM with valid options for FK fields so it can present
accurate choices to users instead of guessing or inventing values.

Injected port is the same ITicketPort used by ticket_tools.

ARCHITECTURE NOTE (Fase 8 — async migration):
    All tools are ``async def`` and delegate to the async ``ITicketPort``.
"""

from typing import Optional, Union

from langchain_core.tools import tool
from pydantic import BaseModel, field_validator

from ports.ticket_port import ITicketPort

_port: ITicketPort | None = None


def set_user_port(port: ITicketPort) -> None:
    """Inject the ticket port at application startup."""
    global _port
    _port = port


@tool
async def get_resolvers() -> list:
    """
    Return all available resolver agents.

    Use this before assigning a ticket to show the supervisor valid options.
    Each item contains: ``id``, ``name`` (and role info if available).
    """
    return await _port.get_resolvers()


@tool
async def get_agent_groups() -> list:
    """
    Return all available agent groups (support teams/levels).

    Use this before assigning a ticket to a group.
    Each item contains: ``id``, ``name``.
    """
    return await _port.get_agent_groups()


@tool
async def get_ticket_types() -> list:
    """
    Return all valid ticket types.

    Examples: Incidente, Solicitud, Problema, Cambio.
    Each item contains: ``id``, ``name``.
    Use the ``id`` when calling ``create_ticket`` (``ticket_type_id`` field).
    """
    return await _port.get_ticket_types()


class _CategoriesInput(BaseModel):
    """Pydantic schema for ``get_categories`` tool argument."""
    parent_id: Optional[Union[int, str]] = None

    @field_validator("parent_id", mode="before")
    @classmethod
    def _normalize(cls, v):
        """
        Normalize the ``parent_id`` argument.

        - ``None`` and the strings ``"null"``, ``"none"``, ``""`` → ``None``
        - Numeric strings → ``int``
        - Other strings → ``None`` (we do not support name-based lookup here)
        """
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
    Return categories from the 3-level hierarchy.

    Usage:
        ``get_categories()``              → Level 1 categories (top level)
        ``get_categories(parent_id=1)``   → Level 2 subcategories under category 1
        ``get_categories(parent_id=10)``  → Level 3 elements under subcategory 10

    Always call without ``parent_id`` first, then drill down based on user selection.
    Each item contains: ``id``, ``name``, ``full_name``, ``level``.
    Use the ``id`` from the deepest available level when calling ``create_ticket``.
    Pass ``null`` (not the string ``"null"``) to get top-level categories.
    """
    return await _port.get_categories(parent_id)


@tool
async def get_urgency_levels() -> list:
    """
    Return all valid urgency levels for tickets.

    Each item contains: ``id``, ``name``.
    Use the ``id`` when calling ``create_ticket`` (``urgency_id`` field).
    """
    return await _port.get_urgency_levels()


@tool
async def get_impact_levels() -> list:
    """
    Return all valid impact levels for tickets.

    Each item contains: ``id``, ``name``.
    Use the ``id`` when calling ``create_ticket`` (``impact_id`` field).
    """
    return await _port.get_impact_levels()


@tool
async def get_priority_levels() -> list:
    """
    Return all valid priority levels for tickets.

    Each item contains: ``id``, ``name``.
    Priority is normally inferred from urgency × impact.
    Use the ``id`` when calling ``create_ticket`` (``priority_id`` field).
    """
    return await _port.get_priority_levels()


@tool
async def get_stages() -> list:
    """
    Return all workflow stages with their flags.

    Each item contains: ``id``, ``name``, ``is_start``, ``is_resolve``,
    ``is_close``, ``is_pause``.
    Useful for supervisors filtering tickets by stage.
    """
    return await _port.get_stages()


def get_catalog_tools() -> list:
    """Return all catalog query tools — included in every role."""
    return [
        get_resolvers,
        get_agent_groups,
        get_ticket_types,
        get_categories,
        get_urgency_levels,
        get_impact_levels,
        get_priority_levels,
        get_stages,
    ]
