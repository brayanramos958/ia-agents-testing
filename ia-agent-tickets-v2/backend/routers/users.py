from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from typing import List, Optional
import crud
import schemas
import database

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=List[schemas.UserResponse])
def list_users(
    rol: Optional[str] = None,
    db: Session = Depends(database.get_db),
):
    return crud.get_users(db, rol=rol)
