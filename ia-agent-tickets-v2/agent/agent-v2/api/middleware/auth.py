"""
API Key authentication middleware.

Validates the X-Agent-Key header on all endpoints except /health, /docs, /openapi.json.

In production: also checks that requests originate from internal Docker networks.
SARA is NOT exposed to the public internet — only Odoo should call it.

To upgrade to OAuth2/JWT later:
  1. Remove this middleware
  2. Add a FastAPI dependency: oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
  3. Inject it into routes via Depends(oauth2_scheme)
  4. Business logic in routes stays unchanged — only the auth mechanism changes.
"""

import ipaddress
import logging

from fastapi import Request
from fastapi.responses import JSONResponse
from config.settings import settings

_log = logging.getLogger(__name__)

EXCLUDED_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

# Internal networks allowed to access SARA.
# When Odoo connects via Docker bridge, its IP will be in one of these ranges.
_ALLOWED_NETWORKS = [
    "127.0.0.0/8",        # localhost
    "10.0.0.0/8",         # private networks
    "172.16.0.0/12",      # Docker default and custom bridges
    "192.168.0.0/16",     # private networks
    "::1/128",            # IPv6 loopback
]


def _is_internal_ip(ip: str) -> bool:
    """Check if an IP belongs to a private/internal network."""
    try:
        addr = ipaddress.ip_address(ip)
        if addr.is_loopback or addr.is_private:
            return True
        # In Docker, container IPs often fall in 172.x range
        # which are already covered by is_private for 172.16.0.0/12
        return False
    except ValueError:
        _log.warning("Invalid client IP: %s", ip)
        return False


async def api_key_middleware(request: Request, call_next):
    # ── Skip auth for excluded paths ──────────────────────────────────────
    if request.url.path in EXCLUDED_PATHS:
        return await call_next(request)

    # ── IP check: only internal networks in production ────────────────────
    client_host = request.client.host if request.client else "unknown"
    if not _is_internal_ip(client_host):
        _log.warning(
            "Blocked external request from %s to %s",
            client_host, request.url.path,
        )
        return JSONResponse(
            status_code=403,
            content={
                "error": "Forbidden",
                "detail": "SARA solo es accesible desde la red interna. "
                          "Las requests deben venir desde Odoo.",
            },
        )

    # ── API Key check ─────────────────────────────────────────────────────
    api_key = request.headers.get("X-Agent-Key")
    if not api_key or api_key != settings.agent_api_key:
        return JSONResponse(
            status_code=401,
            content={
                "error": "Unauthorized",
                "detail": "Provide a valid X-Agent-Key header.",
            },
        )

    return await call_next(request)
