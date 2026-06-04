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

import asyncio
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()  # Must be first — settings reads .env at import time

# ── Structured logging — must run BEFORE uvicorn configures its handlers ───────
from core.logging import setup_structured_logging
setup_structured_logging()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from api.middleware.auth import api_key_middleware
from api.routes.chat import router as chat_router
from api.routes.invoke import router as invoke_router
from api.routes.stream import router as stream_router
from api.routes.metrics import router as metrics_router
from api.routes.alerts import router as alerts_router, set_scheduler as set_alerts_scheduler
from api.routes.templates import router as templates_router
from api.routes.llm_status import router as llm_status_router
from core.agent import initialize_ports
from core.graph import init_checkpointer
from core.scheduler import SARAScheduler


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


async def _build_rag_port(ticket_port):
    """Builds the pgvector RAG store and seeds it from the ticket API."""
    from rag.store import PGVectorRAGStore

    store = PGVectorRAGStore(
        postgres_dsn=settings.postgres_dsn,
        enabled=settings.rag_enabled,
    )

    if settings.rag_enabled:
        try:
            resolved = await ticket_port.get_resolved_tickets()
            count = await store.initialize_from_resolved_tickets(resolved)
            if count > 0:
                print(f"[RAG] Seeded {count} resolved tickets into vector store")
            else:
                existing = await store.count()
                if existing > 0:
                    print(f"[RAG] Vector store already has {existing} documents — skipping seed")
                else:
                    print("[RAG] No resolved tickets found to seed")
        except Exception as exc:
            print(f"[RAG] WARNING: Could not seed from backend ({exc}). Starting with existing store.")

        # Seed knowledge base articles into the same vector space
        try:
            kb_articles = await ticket_port.get_all_knowledge_articles()
            kb_count = await store.seed_knowledge_articles(kb_articles)
            if kb_count > 0:
                print(f"[RAG] Seeded {kb_count} knowledge base articles into vector store")
        except Exception as exc:
            print(f"[RAG] WARNING: Could not seed knowledge base ({exc}).")
            existing = await store.count()
            print(f"[RAG] Documents in store: {existing}")

    return store


_backend_status: dict = {"healthy": False, "detail": "not checked yet"}


# ── Health check: per-component probes ──────────────────────────────────────

def _check_backend_health(ticket_port=None) -> bool:
    """Probe the backend /health endpoint and update the global status flag."""
    global _backend_status
    import httpx
    url = f"{settings.backend_url}/health"
    try:
        r = httpx.get(url, timeout=5.0)
        r.raise_for_status()
        _backend_status = {"healthy": True, "detail": "ok", "url": settings.backend_url}
        print(f"[startup] Backend OK — {settings.backend_url}")
        return True
    except (httpx.ConnectError, httpx.ConnectTimeout):
        msg = f"No se puede conectar a {url}"
        _backend_status = {"healthy": False, "detail": msg, "url": settings.backend_url}
        print(f"\n{'='*60}")
        print(f"[startup] CRITICO: BACKEND NO DISPONIBLE")
        print(f"[startup]   URL intentada: {url}")
        print(f"[startup]   Las tool calls del agente fallarán hasta que el backend esté corriendo.")
        print(f"{'='*60}\n")
        return False
    except Exception as e:
        _backend_status = {"healthy": False, "detail": str(e), "url": settings.backend_url}
        print(f"[startup] Backend health check failed: {e}")
        return False


def _check_odoo_health() -> dict:
    """Verify Odoo connectivity via JSON-RPC authenticate + simple search."""
    import httpx
    try:
        # 1. Authenticate
        auth_resp = httpx.post(
            f"{settings.odoo_base_url}/web/session/authenticate",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "db": settings.odoo_database,
                    "login": settings.odoo_user,
                    "password": settings.odoo_password,
                },
                "id": 1,
            },
            timeout=8.0,
        )
        auth_data = auth_resp.json()
        uid = auth_data.get("result", {}).get("uid")
        if not uid:
            return {"healthy": False, "detail": f"Auth failed: {auth_data.get('error', {}).get('message', 'unknown')}"}

        # 2. Simple search to verify data access
        search_resp = httpx.post(
            f"{settings.odoo_base_url}/web/dataset/call_kw",
            json={
                "jsonrpc": "2.0",
                "method": "call",
                "params": {
                    "model": "helpdesk.ticket.base",
                    "method": "search_count",
                    "args": [[]],
                    "kwargs": {},
                },
                "id": 2,
            },
            timeout=5.0,
            cookies=auth_resp.cookies,
        )
        total = search_resp.json().get("result", -1)
        return {"healthy": True, "detail": f"ok (uid={uid}, {total} tickets)", "uid": uid, "tickets": total}

    except Exception as e:
        return {"healthy": False, "detail": str(e)}


def _check_postgres_health() -> dict:
    """Verify PostgreSQL connectivity via simple query."""
    import psycopg
    try:
        with psycopg.connect(settings.postgres_dsn, connect_timeout=5) as conn:
            result = conn.execute("SELECT 1").fetchone()
            return {"healthy": True, "detail": "ok" if result else "no result"}
    except Exception as e:
        return {"healthy": False, "detail": str(e)}


def _check_llm_health() -> dict:
    """Verify LLM provider is configured (key present, no live call)."""
    if settings.llm_provider == "groq":
        key_ok = bool(settings.groq_api_key)
        return {
            "healthy": key_ok,
            "provider": "groq",
            "model": settings.llm_model,
            "detail": "api key configured" if key_ok else "GROQ_API_KEY not set",
        }
    elif settings.llm_provider == "vercel":
        key_ok = bool(settings.ai_gateway_api_key)
        return {
            "healthy": key_ok,
            "provider": "vercel",
            "model": settings.ai_gateway_model,
            "detail": "api key configured" if key_ok else "AI_GATEWAY_API_KEY not set",
        }
    elif settings.llm_provider == "anthropic":
        key_ok = bool(settings.anthropic_api_key)
        return {
            "healthy": key_ok,
            "provider": "anthropic",
            "model": settings.anthropic_model,
            "detail": "api key configured" if key_ok else "ANTHROPIC_API_KEY not set",
        }
    elif settings.llm_provider == "ollama":
        return {"healthy": True, "provider": "ollama", "model": settings.ollama_model, "detail": "local — not probed"}
    return {"healthy": False, "provider": settings.llm_provider, "detail": "unknown provider"}


def _build_full_health(ticket_port=None) -> dict:
    """Aggregate all health checks into a single response."""
    odoo = _check_odoo_health()
    pg = _check_postgres_health()
    llm = _check_llm_health()

    all_ok = odoo.get("healthy") and pg.get("healthy") and llm.get("healthy")

    return {
        "status": "healthy" if all_ok else "degraded",
        "service": "ia-helpdesk-agent",
        "version": "2.0.0",
        "adapter": settings.backend_adapter,
        "components": {
            "odoo": odoo,
            "postgres": pg,
            "llm": llm,
        },
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    print(f"[startup] Building ticket port ({settings.backend_adapter})...")
    ticket_port = _build_ticket_port()

    print("[startup] Checking backend connectivity...")
    _check_backend_health(ticket_port)

    print("[startup] Building RAG store...")
    rag_port = await _build_rag_port(ticket_port)

    print("[startup] Initializing checkpointer...")
    await init_checkpointer()

    print("[startup] Injecting ports into tools...")
    initialize_ports(ticket_port, rag_port)

    # ── Background scheduler (SLA alerts, escalation reminders) ──────────────
    scheduler = SARAScheduler(ticket_port, interval_min=5)
    set_alerts_scheduler(scheduler)
    await scheduler.start()

    print(f"[startup] Agent v2 ready on port {settings.port}")
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────
    print("[shutdown] Graceful shutdown initiated...")
    try:
        await asyncio.wait_for(scheduler.stop(), timeout=10.0)
        print("[shutdown] Scheduler stopped cleanly.")
    except asyncio.TimeoutError:
        print("[shutdown] WARNING: Scheduler stop timed out (10s). Forcing exit.")
    print("[shutdown] Agent v2 stopped")


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

app.middleware("http")(api_key_middleware)

app.include_router(chat_router)
app.include_router(invoke_router)
app.include_router(stream_router)
app.include_router(metrics_router)
app.include_router(alerts_router)
app.include_router(templates_router)
app.include_router(llm_status_router)


@app.get("/health", tags=["health"])
def health():
    return _build_full_health()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
