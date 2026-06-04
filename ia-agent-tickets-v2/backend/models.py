from sqlalchemy import Column, Integer, String, Text, DateTime
from datetime import datetime
from database import Base


class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, index=True)

    # Descripción principal
    asunto = Column(String, index=True, nullable=True)
    descripcion = Column(Text)

    # Clasificación — aligned con express_adapter y campos-modulo-helpdesk
    tipo_requerimiento = Column(String, default="Incidente")   # Incidente | Solicitud | Problema
    categoria = Column(String, nullable=True)                   # categoria L1 (string para dev)
    urgencia = Column(String, default="media")                  # baja | media | alta | critica
    impacto = Column(String, default="medio")                   # bajo | medio | alto
    prioridad = Column(String, default="media")                 # baja | media | alta | urgente

    # Workflow
    stage_id = Column(String, default="Abierto")               # Abierto | Asignado | Resuelto | Cerrado

    # Actores
    creado_por = Column(String)                                 # user_id como string
    asignado_a = Column(String, nullable=True)                  # user_id del resueltor
    agent_group_id = Column(String, nullable=True)              # nombre del grupo

    # Aprobación
    approval_status = Column(String, nullable=True)             # pending | approved | rejected
    rejection_reason = Column(Text, nullable=True)

    # Resolución
    resolucion = Column(Text, nullable=True)                    # texto libre de resolución
    causa_raiz = Column(Text, nullable=True)

    # Timestamps
    fecha_creacion = Column(DateTime, default=datetime.utcnow)
    fecha_cierre = Column(DateTime, nullable=True)
    ultima_modificacion = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    email = Column(String, nullable=True)
    rol = Column(String)                                        # creador | resueltor | supervisor
