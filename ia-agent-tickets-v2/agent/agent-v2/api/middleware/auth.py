"""
API Key authentication middleware.

Validates the X-Agent-Key header on all endpoints except /health.

To upgrade to OAuth2/JWT later:
  1. Remove this middleware
  2. Add a FastAPI dependency: oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")
  3. Inject it into routes via Depends(oauth2_scheme)
  4. Business logic in routes stays unchanged — only the auth mechanism changes.

The /health endpoint is intentionally excluded so load balancers and
container orchestrators can check liveness without credentials.
"""

from fastapi import Request
from fastapi.responses import JSONResponse
from config.settings import settings

EXCLUDED_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}


async def api_key_middleware(request: Request, call_next):
    if request.url.path in EXCLUDED_PATHS:
        return await call_next(request)

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
