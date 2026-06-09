"""
Application bootstrap.

Startup sequence (inside lifespan):
  1. Build ticket port adapter (express | http | postgres)
  2. Build RAG store
  3. Seed RAG from resolved tickets via API (never SQLite)
  4. Inject ports into all tool modules
  5. FastAPI is ready to serve requests

Ports are initialized before any request can arrive thanks to
FastAPI's lifespan context manager.
"""

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()  # Must be first — settings reads .env at import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from api.middleware.auth import api_key_middleware
from api.middleware.request_context import RequestContextMiddleware
from api.middleware.jwt_auth import jwt_auth_middleware
from api.routes.chat import router as chat_router
from api.routes.invoke import router as invoke_router
from api.routes.stream import router as stream_router
from api.routes.auth import router as auth_router
from core.agent import initialize_ports
from core.graph import init_checkpointer
from core.logging import configure_logging, get_logger

_log = get_logger(__name__)

# ── Module-level references — set during lifespan, used by /health ──────────
_ticket_port = None
_rag_port = None
_startup_time: float | None = None


def _build_ticket_port():
    """Selects and instantiates the adapter based on BACKEND_ADAPTER env var."""
    adapter = settings.backend_adapter.lower()

    if adapter == "odoo":
        from adapters.odoo_adapter import OdooAdapter
        return OdooAdapter()

    if adapter == "http":
        # Legacy — deprecated. Use BACKEND_ADAPTER=odoo for production.
        from adapters.http_adapter import HttpAdapter
        return HttpAdapter()

    if adapter == "postgres":
        from adapters.postgres_adapter import PostgresAdapter
        raise NotImplementedError(
            "PostgresAdapter is not yet implemented. "
            "Use BACKEND_ADAPTER=express or BACKEND_ADAPTER=http."
        )

    # Default: express (dev)
    from adapters.express_adapter import ExpressAdapter
    return ExpressAdapter(settings.backend_url)


def _build_rag_port(ticket_port):
    """Builds the pgvector RAG store and seeds it from the ticket API."""
    from rag.store import PGVectorRAGStore

    store = PGVectorRAGStore(
        postgres_dsn=settings.postgres_dsn,
        enabled=settings.rag_enabled,
    )

    if settings.rag_enabled:
        try:
            resolved = ticket_port.get_resolved_tickets()
            count = store.initialize_from_resolved_tickets(resolved)
            if count > 0:
                _log.info("rag_seeded", extra={"count": count})
            else:
                existing = store.count()
                if existing > 0:
                    _log.info("rag_skip_seed", extra={"existing_documents": existing})
                else:
                    _log.info("rag_no_tickets_to_seed")
        except Exception as exc:
            _log.warning("rag_seed_failed", extra={"error": str(exc)})
            existing = store.count()
            _log.info("rag_existing_after_failed_seed", extra={"existing_documents": existing})

    return store


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _ticket_port, _rag_port, _startup_time
    # ── Startup ──────────────────────────────────────────────────────────────
    configure_logging()
    _log.info("agent_starting", extra={"adapter": settings.backend_adapter, "port": settings.port})
    _ticket_port = _build_ticket_port()
    _log.info("ticket_port_ready", extra={"adapter": settings.backend_adapter})

    _rag_port = _build_rag_port(_ticket_port)
    _log.info("rag_store_ready", extra={"documents": _rag_port.count() if _rag_port and _rag_port._enabled else 0})

    await init_checkpointer()
    _log.info("checkpointer_ready", extra={"backend": settings.checkpoint_backend})

    initialize_ports(_ticket_port, _rag_port)

    _startup_time = datetime.now(timezone.utc).timestamp()
    _log.info("agent_ready", extra={"uptime_start": _startup_time})
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────
    _ticket_port = None
    _rag_port = None
    _log.info("agent_stopping")


# ── FastAPI application ───────────────────────────────────────────────────────

app = FastAPI(
    title="IA Helpdesk Agent v2",
    description="Pluggable AI agent for enterprise ticket systems",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request context: injects request_id, thread_id into ContextVars for logging
app.add_middleware(RequestContextMiddleware)

# JWT auth: validates Bearer tokens, sets current_user_id/current_user_role
# Must come BEFORE api_key_middleware so public paths are handled first
app.middleware("http")(jwt_auth_middleware)

app.middleware("http")(api_key_middleware)

app.include_router(chat_router)
app.include_router(invoke_router)
app.include_router(stream_router)
app.include_router(auth_router)


# ── Health check (REAL — verifies ALL components) ────────────────────────────

@app.get("/health", tags=["health"])
async def health():
    """
    Production health check — verifies every dependency.

    Returns 200 when all critical components pass, 503 when any fails.
    Load balancers and Docker HEALTHCHECK use this to detect failures.
    Auth: EXCLUDED from API key requirement (see middleware auth.py).
    """
    import time as _time
    import asyncio as _asyncio

    now = _time.time()
    components = {}
    degraded = False

    # ── PostgreSQL ─────────────────────────────────────────────────────────
    pg_start = _time.time()
    try:
        import psycopg
        dsn = settings.postgres_dsn
        if dsn:
            async with await psycopg.AsyncConnection.connect(dsn) as conn:
                async with conn.cursor() as cur:
                    await cur.execute("SELECT 1")
            components["postgres"] = {
                "healthy": True,
                "latency_ms": round((_time.time() - pg_start) * 1000, 1),
                "description": "Checkpointer + RAG database",
            }
        else:
            components["postgres"] = {"healthy": False, "error": "POSTGRES_DSN not configured"}
            degraded = True
    except _asyncio.TimeoutError:
        components["postgres"] = {"healthy": False, "error": "Connection timeout (2s)"}
        degraded = True
    except Exception as exc:
        components["postgres"] = {"healthy": False, "error": str(exc)}
        degraded = True

    # ── LLM (config check + circuit breaker) ───────────────────────────────
    try:
        from core.graph import build_llm
        llm = build_llm()
        # build_llm() raises if API key missing — reaching here means config OK
        provider = settings.llm_provider
        model = settings.ai_gateway_model if provider == "vercel" else settings.llm_model

        llm_data = {
            "healthy": True,
            "provider": provider,
            "model": model,
        }
        # Include circuit breaker status for the active provider
        try:
            from core.circuit_breaker import get_all_status
            cb_status = get_all_status()
            if cb_status:
                llm_data["circuit_breaker"] = cb_status
        except Exception:
            pass
        components["llm"] = llm_data
    except Exception as exc:
        components["llm"] = {"healthy": False, "error": str(exc)}
        degraded = True

    # ── Backend adapter ────────────────────────────────────────────────────
    be_start = _time.time()
    try:
        if _ticket_port is not None:
            # Minimal operation: try to get an empty list (doesn't need real data)
            import asyncio as aio
            result = await aio.wait_for(
                aio.to_thread(_ticket_port.get_resolvers),
                timeout=3.0,
            )
            components["backend"] = {
                "healthy": True,
                "adapter": settings.backend_adapter,
                "latency_ms": round((_time.time() - be_start) * 1000, 1),
                "description": "Ticket backend API",
            }
        else:
            components["backend"] = {"healthy": False, "error": "Ticket port not initialized"}
            degraded = True
    except _asyncio.TimeoutError:
        components["backend"] = {"healthy": False, "error": "Request timeout (3s)"}
        degraded = True
    except Exception as exc:
        components["backend"] = {"healthy": False, "error": str(exc)}
        degraded = True

    # ── RAG store ──────────────────────────────────────────────────────────
    try:
        if _rag_port is not None and _rag_port._enabled:
            doc_count = _rag_port.count()
            components["rag_store"] = {
                "healthy": True,
                "documents": doc_count,
                "description": "pgvector vector store",
            }
        elif _rag_port is not None and not _rag_port._enabled:
            components["rag_store"] = {"healthy": True, "documents": 0, "description": "RAG disabled"}
        else:
            components["rag_store"] = {"healthy": False, "error": "RAG port not initialized"}
            degraded = True
    except Exception as exc:
        components["rag_store"] = {"healthy": False, "error": str(exc)}
        degraded = True

    # ── Checkpointer ───────────────────────────────────────────────────────
    try:
        from core.graph import build_checkpointer
        cp = build_checkpointer()
        components["checkpointer"] = {
            "healthy": True,
            "backend": settings.checkpoint_backend,
            "description": "LangGraph conversation persistence",
        }
    except Exception as exc:
        components["checkpointer"] = {"healthy": False, "error": str(exc)}
        degraded = True

    # ── Assemble response ──────────────────────────────────────────────────
    status_code = 503 if degraded else 200
    uptime = round(now - _startup_time) if _startup_time else 0
    from fastapi.responses import JSONResponse
    return JSONResponse(
        content={
            "status": "degraded" if degraded else "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": "2.1.0",
            "uptime_seconds": uptime,
            "components": components,
        },
        status_code=status_code,
    )


if __name__ == "__main__":
    import uvicorn
    cert_file = "/app/certs/cert.pem"
    key_file = "/app/certs/key.pem"
    import os
    if os.path.exists(cert_file) and os.path.exists(key_file):
        uvicorn.run(app, host="0.0.0.0", port=8443,
                    ssl_keyfile=key_file, ssl_certfile=cert_file)
    else:
        uvicorn.run(app, host="0.0.0.0", port=settings.port)
