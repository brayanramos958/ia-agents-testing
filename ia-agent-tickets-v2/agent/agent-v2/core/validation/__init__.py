"""
Pre-execution tool argument validation layer.

Provides Pydantic schemas, reusable validators, and a ``@validate_tool``
decorator that catches LLM argument errors before they reach Odoo.

Usage::

    from core.validation import validate_tool, CreateTicketSchema

    @tool
    @validate_tool(CreateTicketSchema)
    async def create_ticket(asunto, ...) -> dict:
        ...
"""

from core.validation.validators import (
    ensure_positive_int,
    ensure_non_empty_str,
    ensure_dict,
    ensure_ticket_id,
)
from core.validation.schemas import (
    CreateTicketSchema,
    UpdateTicketSchema,
    GetTicketDetailSchema,
    AssignTicketSchema,
    ApproveTicketSchema,
    RejectTicketSchema,
    ReopenTicketSchema,
    ResolveTicketSchema,
    TOOL_SCHEMAS,
)
from core.validation.decorator import validate_tool

__all__ = [
    "validate_tool",
    "ensure_positive_int",
    "ensure_non_empty_str",
    "ensure_dict",
    "ensure_ticket_id",
    "CreateTicketSchema",
    "UpdateTicketSchema",
    "GetTicketDetailSchema",
    "AssignTicketSchema",
    "ApproveTicketSchema",
    "RejectTicketSchema",
    "ReopenTicketSchema",
    "ResolveTicketSchema",
    "TOOL_SCHEMAS",
]
