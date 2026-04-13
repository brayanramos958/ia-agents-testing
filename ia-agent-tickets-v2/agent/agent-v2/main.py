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
from dotenv import load_dotenv

load_dotenv()  # Must be first — settings reads .env at import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from config.settings import settings
from api.middleware.auth import api_key_middleware
from api.routes.chat import router as chat_router
from api.routes.invoke import router as invoke_router
from core.agent import initialize_ports


def _build_ticket_port():
    """Selects and instantiates the adapter based on BACKEND_ADAPTER env var."""
    adapter = settings.backend_adapter.lower()

    if adapter == "http":
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
    """Builds the RAG store and seeds it from the ticket API."""
    from rag.store import ChromaRAGStore

    store = ChromaRAGStore(
        persist_path=settings.vector_store_path,
        enabled=settings.rag_enabled,
    )

    if settings.rag_enabled:
        try:
            resolved = ticket_port.get_resolved_tickets()
            count = store.initialize_from_resolved_tickets(resolved)
            if count > 0:
                print(f"[RAG] Seeded {count} resolved tickets into vector store")
            else:
                existing = store.count()
                if existing > 0:
                    print(f"[RAG] Vector store already has {existing} documents — skipping seed")
                else:
                    print("[RAG] No resolved tickets found to seed")
        except Exception as exc:
            print(f"[RAG] WARNING: Could not seed from backend ({exc}). Starting with existing store.")
            existing = store.count()
            print(f"[RAG] Documents in store: {existing}")

    return store


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    print(f"[startup] Building ticket port ({settings.backend_adapter})...")
    ticket_port = _build_ticket_port()

    print("[startup] Building RAG store...")
    rag_port = _build_rag_port(ticket_port)

    print("[startup] Injecting ports into tools...")
    initialize_ports(ticket_port, rag_port)

    print(f"[startup] Agent v2 ready on port {settings.port}")
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────
    print("[shutdown] Agent v2 stopping")


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


@app.get("/health", tags=["health"])
def health():
    return {
        "status": "healthy",
        "service": "ia-helpdesk-agent",
        "version": "2.0.0",
        "adapter": settings.backend_adapter,
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=settings.port)
