from sqlalchemy.orm import Session
from datetime import datetime
import models
import schemas


# ── Tickets ───────────────────────────────────────────────────────────────────

def get_ticket(db: Session, ticket_id: int):
    return db.query(models.Ticket).filter(models.Ticket.id == ticket_id).first()


def get_tickets(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    created_by: str = None,
    asignado_a: str = None,
    estado: str = None,
    approval_status: str = None,
):
    query = db.query(models.Ticket)

    if created_by:
        query = query.filter(models.Ticket.creado_por == str(created_by))
    if asignado_a:
        query = query.filter(models.Ticket.asignado_a == str(asignado_a))
    if estado:
        # Normaliza "resuelto" → "Resuelto", "abierto" → "Abierto", etc.
        query = query.filter(
            models.Ticket.stage_id.ilike(estado)
        )
    if approval_status:
        query = query.filter(models.Ticket.approval_status == approval_status)

    return query.offset(skip).limit(limit).all()


def create_ticket(db: Session, ticket: schemas.TicketCreate):
    db_ticket = models.Ticket(
        descripcion=ticket.descripcion,
        tipo_requerimiento=ticket.tipo_requerimiento,
        categoria=ticket.categoria,
        urgencia=ticket.urgencia,
        impacto=ticket.impacto,
        prioridad=ticket.prioridad,
        creado_por=str(ticket.created_by),
        stage_id="Abierto",
    )
    db.add(db_ticket)
    db.commit()
    db.refresh(db_ticket)

    # Nombre serial: TCK-0001
    db_ticket.name = f"TCK-{db_ticket.id:04d}"
    db_ticket.asunto = ticket.descripcion[:80]  # primer fragmento como asunto
    db.commit()
    db.refresh(db_ticket)
    return db_ticket


def update_ticket(db: Session, ticket_id: int, ticket_update: schemas.TicketUpdate):
    db_ticket = get_ticket(db, ticket_id)
    if not db_ticket:
        return None

    update_data = ticket_update.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(db_ticket, key, value)

    if ticket_update.stage_id == "Cerrado":
        db_ticket.fecha_cierre = datetime.utcnow()

    db_ticket.ultima_modificacion = datetime.utcnow()
    db.commit()
    db.refresh(db_ticket)
    return db_ticket


def resolve_ticket(db: Session, ticket_id: int, resolucion: str):
    db_ticket = get_ticket(db, ticket_id)
    if not db_ticket:
        return None

    db_ticket.resolucion = resolucion
    db_ticket.stage_id = "Resuelto"
    db_ticket.fecha_cierre = datetime.utcnow()
    db_ticket.ultima_modificacion = datetime.utcnow()
    db.commit()
    db.refresh(db_ticket)
    return db_ticket


def assign_ticket(db: Session, ticket_id: int, asignado_a: int, agent_group_id: int = None):
    db_ticket = get_ticket(db, ticket_id)
    if not db_ticket:
        return None

    db_ticket.asignado_a = str(asignado_a)
    if agent_group_id is not None:
        db_ticket.agent_group_id = str(agent_group_id)
    db_ticket.stage_id = "Asignado"
    db_ticket.ultima_modificacion = datetime.utcnow()
    db.commit()
    db.refresh(db_ticket)
    return db_ticket


def reopen_ticket(db: Session, ticket_id: int, motivo: str):
    db_ticket = get_ticket(db, ticket_id)
    if not db_ticket:
        return None

    db_ticket.stage_id = "Abierto"
    db_ticket.fecha_cierre = None
    db_ticket.resolucion = None
    # Agrega el motivo al final de la descripción como nota de reapertura
    db_ticket.descripcion = (db_ticket.descripcion or "") + f"\n\n[Reabierto]: {motivo}"
    db_ticket.ultima_modificacion = datetime.utcnow()
    db.commit()
    db.refresh(db_ticket)
    return db_ticket


def delete_ticket(db: Session, ticket_id: int):
    db_ticket = get_ticket(db, ticket_id)
    if not db_ticket:
        return False
    db.delete(db_ticket)
    db.commit()
    return True


# ── Users ─────────────────────────────────────────────────────────────────────

def get_users(db: Session, rol: str = None):
    query = db.query(models.User)
    if rol:
        query = query.filter(models.User.rol == rol)
    return query.all()
