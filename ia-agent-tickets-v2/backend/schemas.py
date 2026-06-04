from pydantic import BaseModel
from typing import Optional
from datetime import datetime


# ── Ticket ────────────────────────────────────────────────────────────────────

class TicketCreate(BaseModel):
    """Body que envía express_adapter al crear un ticket."""
    tipo_requerimiento: str = "Incidente"
    categoria: Optional[str] = None
    descripcion: str
    urgencia: str = "media"
    impacto: str = "medio"
    prioridad: str = "media"
    created_by: int                         # user_id del solicitante


class TicketUpdate(BaseModel):
    """Actualización parcial de campos editables."""
    asunto: Optional[str] = None
    descripcion: Optional[str] = None
    tipo_requerimiento: Optional[str] = None
    categoria: Optional[str] = None
    urgencia: Optional[str] = None
    impacto: Optional[str] = None
    prioridad: Optional[str] = None
    stage_id: Optional[str] = None
    asignado_a: Optional[str] = None
    agent_group_id: Optional[str] = None
    approval_status: Optional[str] = None
    rejection_reason: Optional[str] = None


class ResolveRequest(BaseModel):
    """Body para PUT /api/tickets/{id}/resolve."""
    resolucion: str


class AssignRequest(BaseModel):
    """Body para PUT /api/tickets/{id}/assign."""
    asignado_a: int
    agent_group_id: Optional[int] = None


class ReopenRequest(BaseModel):
    """Body para PUT /api/tickets/{id}/reopen."""
    motivo: str


class TicketResponse(BaseModel):
    """Respuesta canónica del ticket — incluye todos los campos que el adapter lee."""
    id: int
    name: str
    asunto: Optional[str] = None
    descripcion: str
    tipo_requerimiento: str
    categoria: Optional[str] = None
    urgencia: str
    impacto: str
    prioridad: str
    stage_id: str
    creado_por: str
    asignado_a: Optional[str] = None
    agent_group_id: Optional[str] = None
    approval_status: Optional[str] = None
    rejection_reason: Optional[str] = None
    resolucion: Optional[str] = None
    causa_raiz: Optional[str] = None
    fecha_creacion: datetime
    fecha_cierre: Optional[datetime] = None
    ultima_modificacion: Optional[datetime] = None

    class Config:
        from_attributes = True


# ── User ──────────────────────────────────────────────────────────────────────

class UserResponse(BaseModel):
    id: int
    name: str
    email: Optional[str] = None
    rol: str

    class Config:
        from_attributes = True
