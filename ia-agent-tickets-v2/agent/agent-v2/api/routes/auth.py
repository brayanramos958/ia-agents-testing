"""
POST /auth/login — authenticate against Odoo, return JWT.

JWT payload:
  { "sub": uid, "rol": "creador", "name": "Juan Perez", "iat": 1700000000, "exp": 1700028800 }

Token is used in subsequent requests via Authorization: Bearer <token> header.
Verified by api/middleware/jwt_auth.py which sets current_user_id and current_user_role.
"""

from __future__ import annotations

import logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.middleware.jwt_auth import create_token

_log = logging.getLogger(__name__)
router = APIRouter()


class LoginRequest(BaseModel):
    username: str   # Odoo login (email or username)
    password: str   # Odoo password


class LoginResponse(BaseModel):
    token: str
    uid: int
    role: str
    name: str
    expires_in: int  # seconds until expiration


class UserInfoResponse(BaseModel):
    uid: int
    role: str
    name: str
    is_authenticated: bool


@router.post("/auth/login", response_model=LoginResponse)
def login(request: LoginRequest):
    """
    Authenticate against Odoo and return a JWT token.

    Token must be sent in subsequent requests as:
      Authorization: Bearer <token>
    """
    from core.context import current_user_id, current_user_role

    try:
        from adapters.odoo_adapter import OdooAdapter
        adapter = OdooAdapter()
        user = adapter.authenticate_user(request.username, request.password)
    except ValueError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except Exception as exc:
        _log.warning("auth_login_error", extra={"username": request.username, "error": str(exc)})
        raise HTTPException(status_code=500, detail="Error de autenticación")

    uid = user["uid"]
    role = user["role"]
    name = user["name"]

    # Create JWT
    token = create_token(uid, role, name)

    # Set ContextVars for the current request (so /auth/me works)
    current_user_id.set(uid)
    current_user_role.set(role)

    from config.settings import settings
    expires_in = settings.jwt_expiration_hours * 3600 if settings.jwt_expiration_hours else 0

    return LoginResponse(
        token=token,
        uid=uid,
        role=role,
        name=name,
        expires_in=expires_in,
    )


@router.get("/auth/me", response_model=UserInfoResponse)
def me():
    """
    Returns info about the currently authenticated user.
    Requires valid JWT in Authorization header.
    """
    from core.context import current_user_id, current_user_role

    uid = current_user_id.get(0)
    role = current_user_role.get("")
    return UserInfoResponse(
        uid=uid,
        role=role,
        name="",
        is_authenticated=uid > 0,
    )
