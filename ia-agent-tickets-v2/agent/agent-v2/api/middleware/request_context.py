"""
Request context middleware — injects tracking IDs into ContextVars.

Sets current_thread_id and current_request_id for the duration of each
HTTP request so structured logging can include them automatically.
"""

from __future__ import annotations

import uuid
from datetime import date
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from core.context import current_thread_id, current_request_id


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Middleware that sets ContextVars for every incoming request."""

    async def dispatch(self, request: Request, call_next) -> Response:
        # Generate unique request ID
        rid = f"req-{uuid.uuid4().hex[:12]}"
        current_request_id.set(rid)

        # Try to extract thread_id from the request body (if JSON with thread_id field)
        # For chat/stream endpoints, thread_id is set in the route handler.
        # For other endpoints (health, docs), use a default.
        tid = request.url.path.rstrip("/")
        if tid.endswith("/chat") or tid.endswith("/stream") or tid.endswith("/invoke"):
            # Will be set by the route handler — use placeholder
            tid = f"{date.today().isoformat()}"
        current_thread_id.set(tid)

        # Inject request_id into response headers for client-side tracing
        response: Response = await call_next(request)
        response.headers["X-Request-ID"] = rid
        return response
