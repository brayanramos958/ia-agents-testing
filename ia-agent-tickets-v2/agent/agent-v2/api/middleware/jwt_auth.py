"""
JWT authentication middleware — validates Bearer tokens.

Replaces X-Agent-Key for production auth. Tokens are issued by
/auth/login after Odoo credential validation.

Sets ContextVars:
  - current_user_id → uid from JWT sub claim
  - current_user_role → rol from JWT claim

Unprotected paths (no JWT required):
  - /health, /docs, /openapi.json, /redoc, /auth/login
"""

from __future__ import annotations

import json
import time
import hmac
import hashlib
import base64
import logging
from fastapi import Request, HTTPException
from starlette.responses import JSONResponse

from config.settings import settings
from core.context import current_user_id, current_user_role

_log = logging.getLogger("sara.auth")

# Paths that don't require JWT
# /metrics-plus is the dashboard HTML + static assets. Public so the user
# can open it from Odoo; the JS sends X-Agent-Key on each /agent/metrics fetch.
_PUBLIC_PATHS = {"/health", "/docs", "/openapi.json", "/redoc", "/auth/login", "/metrics-plus"}


def _is_public(path: str) -> bool:
    # Use exact match for short paths, prefix match for the dashboard.
    for p in _PUBLIC_PATHS:
        if p == "/metrics-plus":
            # Only match the dashboard and its static assets, not /agent/metrics
            if path == "/metrics-plus" or path.startswith("/metrics-plus/"):
                return True
            continue
        if path == p or path.startswith(p):
            return True
    return False


def _decode_jwt(token: str) -> dict:
    """Decode and verify a JWT token. Returns payload or raises."""
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("token malformado")

    header_b64, payload_b64, sig_b64 = parts

    # Verify signature
    secret = settings.jwt_secret.encode()
    signing_input = f"{header_b64}.{payload_b64}"
    expected_sig = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    try:
        actual_sig = base64.urlsafe_b64decode(sig_b64 + "==")
    except Exception:
        raise ValueError("firma inválida")

    if not hmac.compare_digest(expected_sig, actual_sig):
        raise ValueError("firma inválida")

    # Decode payload
    try:
        payload_b53 = base64.urlsafe_b64decode(payload_b64 + "==")
        payload = json.loads(payload_b53)
    except Exception:
        raise ValueError("payload inválido")

    # Check expiration
    exp = payload.get("exp", 0)
    if exp and time.time() > exp:
        raise ValueError("token expirado")

    return payload


def _encode_jwt(payload: dict) -> str:
    """Create a JWT token from payload dict."""
    secret = settings.jwt_secret.encode()
    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = base64.urlsafe_b64encode(json.dumps(header).encode()).rstrip(b"=").decode()
    payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b"=").decode()

    signing_input = f"{header_b64}.{payload_b64}"
    sig = hmac.new(secret, signing_input.encode(), hashlib.sha256).digest()
    sig_b64 = base64.urlsafe_b64encode(sig).rstrip(b"=").decode()

    return f"{header_b64}.{payload_b64}.{sig_b64}"


async def jwt_auth_middleware(request: Request, call_next):
    """
    FastAPI middleware: validates JWT on protected paths.

    For public paths (/health, /docs, /auth/login): pass through.
    For protected paths: require Authorization: Bearer <token> header.
    Sets current_user_id and current_user_role on success.
    """
    path = request.url.path.rstrip("/")

    if _is_public(path):
        response = await call_next(request)
        return response

    auth_header = request.headers.get("Authorization", "")

    # Fallback: X-Agent-Key for dev (backward compat)
    if not auth_header:
        agent_key = request.headers.get("X-Agent-Key", "")
        if agent_key == settings.agent_api_key:
            # Dev mode — allow without JWT
            response = await call_next(request)
            return response
        return JSONResponse(status_code=401, content={"detail": "Autenticación requerida"})

    # Validate Bearer token
    if not auth_header.startswith("Bearer "):
        return JSONResponse(status_code=401, content={"detail": "Formato de token inválido"})

    token = auth_header[7:]  # strip "Bearer "
    try:
        payload = _decode_jwt(token)
    except Exception as exc:
        return JSONResponse(status_code=401, content={"detail": f"Token inválido: {str(exc)}"})

    uid = payload.get("sub")
    role = payload.get("rol", "")
    if not uid:
        return JSONResponse(status_code=401, content={"detail": "Token sin user_id"})

    current_user_id.set(int(uid))
    current_user_role.set(role)

    response = await call_next(request)
    return response


def create_token(uid: int, role: str, name: str = "") -> str:
    """
    Create a JWT token for a user.
    
    Args:
        uid: Odoo user ID
        role: one of "creador", "resueltor", "supervisor"
        name: user display name (optional)
    
    Returns:
        JWT string
    """
    now = int(time.time())
    exp = now + (settings.jwt_expiration_hours * 3600) if settings.jwt_expiration_hours else 0

    payload = {
        "sub": uid,
        "rol": role,
        "name": name,
        "iat": now,
    }
    if exp:
        payload["exp"] = exp

    return _encode_jwt(payload)
