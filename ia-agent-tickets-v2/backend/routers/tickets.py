from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
import crud
import schemas
import database

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


@router.post("", response_model=schemas.TicketResponse)
def create_ticket(ticket: schemas.TicketCreate, db: Session = Depends(database.get_db)):
    return crud.create_ticket(db=db, ticket=ticket)


@router.get("", response_model=List[schemas.TicketResponse])
def list_tickets(
    skip: int = 0,
    limit: int = 100,
    created_by: Optional[str] = None,
    asignado_a: Optional[str] = None,
    estado: Optional[str] = None,
    approval_status: Optional[str] = None,
    db: Session = Depends(database.get_db),
):
    return crud.get_tickets(
        db,
        skip=skip,
        limit=limit,
        created_by=created_by,
        asignado_a=asignado_a,
        estado=estado,
        approval_status=approval_status,
    )


@router.get("/{ticket_id}", response_model=schemas.TicketResponse)
def get_ticket(ticket_id: int, db: Session = Depends(database.get_db)):
    db_ticket = crud.get_ticket(db, ticket_id=ticket_id)
    if db_ticket is None:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return db_ticket


@router.put("/{ticket_id}", response_model=schemas.TicketResponse)
def update_ticket(
    ticket_id: int,
    ticket: schemas.TicketUpdate,
    db: Session = Depends(database.get_db),
):
    db_ticket = crud.update_ticket(db, ticket_id=ticket_id, ticket_update=ticket)
    if db_ticket is None:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return db_ticket


@router.put("/{ticket_id}/resolve", response_model=schemas.TicketResponse)
def resolve_ticket(
    ticket_id: int,
    body: schemas.ResolveRequest,
    db: Session = Depends(database.get_db),
):
    db_ticket = crud.resolve_ticket(db, ticket_id=ticket_id, resolucion=body.resolucion)
    if db_ticket is None:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return db_ticket


@router.put("/{ticket_id}/assign", response_model=schemas.TicketResponse)
def assign_ticket(
    ticket_id: int,
    body: schemas.AssignRequest,
    db: Session = Depends(database.get_db),
):
    db_ticket = crud.assign_ticket(
        db,
        ticket_id=ticket_id,
        asignado_a=body.asignado_a,
        agent_group_id=body.agent_group_id,
    )
    if db_ticket is None:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return db_ticket


@router.put("/{ticket_id}/reopen", response_model=schemas.TicketResponse)
def reopen_ticket(
    ticket_id: int,
    body: schemas.ReopenRequest,
    db: Session = Depends(database.get_db),
):
    db_ticket = crud.reopen_ticket(db, ticket_id=ticket_id, motivo=body.motivo)
    if db_ticket is None:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return db_ticket


@router.delete("/{ticket_id}")
def delete_ticket(ticket_id: int, db: Session = Depends(database.get_db)):
    deleted = crud.delete_ticket(db, ticket_id=ticket_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Ticket no encontrado")
    return {"ok": True, "ticket_id": ticket_id}
