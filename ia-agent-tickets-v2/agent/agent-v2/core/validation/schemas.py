"""
Pydantic v2 schemas for tool argument validation.

Each tool has one schema that validates:
- Types: strings, integers, dicts (catches LLM hallucinations)
- Ranges: positive IDs, non-empty strings, string lengths
- Required vs optional fields

When validation fails, the ``@validate_tool`` decorator returns a
structured error dict that LangGraph sends to the LLM as a ToolMessage.
The LLM can then correct its arguments and retry.

Design notes:
- Fields use ``Field()`` with ``gt=0`` for IDs, ``min_length`` for strings.
- Custom validators in ``core/validation/validators`` handle edge cases
  (e.g. stripping 'INC-' prefix from ticket_id).
- Schemas are intentionally separate from the tool functions so they can
  be tested in isolation without Odoo/LLM dependencies.
"""

from pydantic import BaseModel, Field, field_validator, ConfigDict
from typing import Optional, Any

from core.validation.validators import (
    ensure_positive_int,
    ensure_non_empty_str,
    ensure_dict,
    ensure_optional_str,
    ensure_ticket_id,
)


# ── Creator tool schemas ──────────────────────────────────────────────────────


class CreateTicketSchema(BaseModel):
    """Validates arguments for ``create_ticket``."""
    model_config = ConfigDict(extra="forbid")

    asunto: str = Field(..., min_length=3, max_length=200)
    ticket_type_id: Any = Field(..., description="ID del tipo de ticket (entero positivo)")
    category_id: Any = Field(..., description="ID de categoría L1 (entero positivo)")
    urgency_id: Any = Field(..., description="ID de urgencia (entero positivo)")
    impact_id: Any = Field(..., description="ID de impacto (entero positivo)")
    priority_id: Any = Field(..., description="ID de prioridad (entero positivo)")
    user_id: Any = Field(..., description="ID del usuario")
    descripcion: str = Field(default="", max_length=2000)
    subcategory_id: Optional[Any] = Field(default=None)
    element_id: Optional[Any] = Field(default=None)
    system_equipment: Optional[str] = Field(default="", max_length=100)

    @field_validator("ticket_type_id", "category_id", "urgency_id",
                     "impact_id", "priority_id", "user_id")
    @classmethod
    def validate_positive_ids(cls, v: Any, info) -> int:
        return ensure_positive_int(v, field_name=str(info.field_name))

    @field_validator("subcategory_id", "element_id")
    @classmethod
    def validate_optional_ids(cls, v: Any, info) -> int | None:
        if v is None:
            return None
        return ensure_positive_int(v, field_name=str(info.field_name))

    @field_validator("asunto")
    @classmethod
    def validate_asunto(cls, v: Any) -> str:
        return ensure_non_empty_str(v, field_name="asunto", min_len=3)


# ── Shared tool schemas ───────────────────────────────────────────────────────


class UpdateTicketSchema(BaseModel):
    """Validates arguments for ``update_ticket``."""
    model_config = ConfigDict(extra="forbid")

    ticket_id: Any = Field(..., description="ID numérico del ticket")
    fields: Any = Field(..., description="Diccionario con campos a actualizar")
    user_id: Any = Field(..., description="ID del usuario")

    @field_validator("ticket_id")
    @classmethod
    def validate_ticket_id(cls, v: Any) -> int:
        return ensure_ticket_id(v)

    @field_validator("fields")
    @classmethod
    def validate_fields(cls, v: Any) -> dict:
        return ensure_dict(v, field_name="fields")

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: Any) -> int:
        return ensure_positive_int(v, field_name="user_id")


class GetTicketDetailSchema(BaseModel):
    """Validates arguments for ``get_ticket_detail``."""
    model_config = ConfigDict(extra="forbid")

    ticket_id: Any = Field(..., description="ID numérico del ticket")
    user_id: Any = Field(..., description="ID del usuario")
    user_role: str = Field(default="creador", min_length=1)

    @field_validator("ticket_id")
    @classmethod
    def validate_ticket_id(cls, v: Any) -> int:
        return ensure_ticket_id(v)

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: Any) -> int:
        return ensure_positive_int(v, field_name="user_id")


# ── Supervisor tool schemas ───────────────────────────────────────────────────


class AssignTicketSchema(BaseModel):
    """Validates arguments for ``assign_ticket``."""
    model_config = ConfigDict(extra="forbid")

    ticket_id: Any = Field(..., description="ID numérico del ticket")
    assignee_id: Any = Field(..., description="ID del agente asignado")
    agent_group_id: Any = Field(..., description="ID del grupo de agentes")
    user_id: Any = Field(..., description="ID del supervisor")

    @field_validator("ticket_id")
    @classmethod
    def validate_ticket_id(cls, v: Any) -> int:
        return ensure_ticket_id(v)

    @field_validator("assignee_id", "agent_group_id", "user_id")
    @classmethod
    def validate_positive_ids(cls, v: Any, info) -> int:
        return ensure_positive_int(v, field_name=str(info.field_name))


class ApproveTicketSchema(BaseModel):
    """Validates arguments for ``approve_ticket``."""
    model_config = ConfigDict(extra="forbid")

    ticket_id: Any = Field(..., description="ID numérico del ticket")
    user_id: Any = Field(..., description="ID del supervisor")

    @field_validator("ticket_id")
    @classmethod
    def validate_ticket_id(cls, v: Any) -> int:
        return ensure_ticket_id(v)

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: Any) -> int:
        return ensure_positive_int(v, field_name="user_id")


class RejectTicketSchema(BaseModel):
    """Validates arguments for ``reject_ticket`` (supervisor rejection)."""
    model_config = ConfigDict(extra="forbid")

    ticket_id: Any = Field(..., description="ID numérico del ticket")
    reason: str = Field(..., min_length=1, max_length=1000)
    user_id: Any = Field(..., description="ID del supervisor")

    @field_validator("ticket_id")
    @classmethod
    def validate_ticket_id(cls, v: Any) -> int:
        return ensure_ticket_id(v)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: Any) -> str:
        return ensure_non_empty_str(v, field_name="reason", min_len=1)

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: Any) -> int:
        return ensure_positive_int(v, field_name="user_id")


class ReopenTicketSchema(BaseModel):
    """Validates arguments for ``reopen_ticket``."""
    model_config = ConfigDict(extra="forbid")

    ticket_id: Any = Field(..., description="ID numérico del ticket")
    reason: str = Field(..., min_length=1, max_length=1000)
    user_id: Any = Field(..., description="ID del supervisor")

    @field_validator("ticket_id")
    @classmethod
    def validate_ticket_id(cls, v: Any) -> int:
        return ensure_ticket_id(v)

    @field_validator("reason")
    @classmethod
    def validate_reason(cls, v: Any) -> str:
        return ensure_non_empty_str(v, field_name="reason", min_len=1)

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: Any) -> int:
        return ensure_positive_int(v, field_name="user_id")


# ── Resolver tool schemas ─────────────────────────────────────────────────────


class ResolveTicketSchema(BaseModel):
    """Validates arguments for ``resolve_ticket``."""
    model_config = ConfigDict(extra="forbid")

    ticket_id: Any = Field(..., description="ID numérico del ticket")
    motivo_resolucion: str = Field(..., min_length=3, max_length=2000)
    causa_raiz: str = Field(..., min_length=3, max_length=2000)
    user_id: Any = Field(..., description="ID del resolver")

    @field_validator("ticket_id")
    @classmethod
    def validate_ticket_id(cls, v: Any) -> int:
        return ensure_ticket_id(v)

    @field_validator("motivo_resolucion")
    @classmethod
    def validate_motivo(cls, v: Any) -> str:
        return ensure_non_empty_str(v, field_name="motivo_resolucion", min_len=3)

    @field_validator("causa_raiz")
    @classmethod
    def validate_causa(cls, v: Any) -> str:
        return ensure_non_empty_str(v, field_name="causa_raiz", min_len=3)

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, v: Any) -> int:
        return ensure_positive_int(v, field_name="user_id")


# ── Schema registry (used by @validate_tool decorator) ───────────────────────


# Maps tool function name → Pydantic schema.
# Add entries here when a tool gets validation.
TOOL_SCHEMAS: dict[str, type[BaseModel]] = {
    "create_ticket": CreateTicketSchema,
    "update_ticket": UpdateTicketSchema,
    "get_ticket_detail": GetTicketDetailSchema,
    "assign_ticket": AssignTicketSchema,
    "approve_ticket": ApproveTicketSchema,
    "reject_ticket": RejectTicketSchema,
    "reopen_ticket": ReopenTicketSchema,
    "resolve_ticket": ResolveTicketSchema,
}
