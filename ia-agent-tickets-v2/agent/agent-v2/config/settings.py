"""
Application configuration — single source of truth.
All values come from environment variables or .env file.
"""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # ── LLM ────────────────────────────────────────────────────────────────
    # "vercel" → Vercel AI Gateway (default, production) — OpenAI-compatible
    # "groq"   → Groq API
    # "ollama" → Ollama local (development)
    llm_provider: str = "vercel"

    # ── Vercel AI Gateway (only used when llm_provider=vercel) ──────────────
    ai_gateway_api_key: str = ""
    ai_gateway_model: str = "minimax/minimax-m2.7"
    ai_gateway_base_url: str = "https://ai-gateway.vercel.sh/v1"

    # ── OpenCode Go (only used when llm_provider=opencode_go) ────────────────
    # Low-cost subscription provider — $5 first month, $10/month after.
    # https://opencode.ai/docs/es/go/
    # OpenAI-compatible endpoint. Get your key at https://opencode.ai/auth
    opencode_go_api_key: str = ""
    opencode_go_model: str = "deepseek-v4-pro"
    opencode_go_base_url: str = "https://opencode.ai/zen/go/v1"

    groq_api_key: str = ""
    llm_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    openrouter_api_key: str = ""
    openrouter_model: str = "nvidia/nemotron-3-super-120b-a12b:free"

    # ── Ollama (only used when llm_provider=ollama) ─────────────────────────
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "gemma3"
    # Modelos free de OpenRouter usados como cadena de fallback cuando Groq hace rate limit.
    # Se intentan en orden — si uno falla con 429/402, se pasa al siguiente.
    # Verificados en OpenRouter API (abril 2026) — todos soportan tool calling y son gratuitos.
    openrouter_fallback_models: List[str] = [
        "nvidia/nemotron-3-super-120b-a12b:free",   # 120B, 262K ctx
        "google/gemma-4-31b-it:free",                # 31B,  262K ctx
        "google/gemma-4-26b-a4b-it:free",            # 26B,  262K ctx
        "minimax/minimax-m2.5:free",                 # 196K ctx
        "nvidia/nemotron-3-nano-30b-a3b:free",       # 30B,  256K ctx
    ]

    # ── Backend adapter ─────────────────────────────────────────────────────
    # "express"  → ExpressAdapter (local dev, simplified schema — no Odoo needed)
    # "odoo"     → OdooAdapter (production — Odoo 15 Community JSON-RPC)
    # "http"     → HttpAdapter (legacy — deprecated, kept as reference only)
    # "postgres" → PostgresAdapter (future — direct DB access)
    backend_adapter: str = "express"
    backend_url: str = "http://localhost:3001"

    # OdooAdapter — Odoo 15 Community JSON-RPC (required when backend_adapter=odoo)
    # Odoo 15 uses session auth: login + password.
    # NOTE: API keys (Bearer token) are Odoo 17+ — do NOT use them for Odoo 15.
    odoo_base_url: str = ""
    odoo_database: str = ""
    odoo_user: str = ""        # Login del usuario de servicio (e.g. helpdesk@empresa.com)
    odoo_password: str = ""    # Contraseña del usuario de servicio

    # ── RAG ─────────────────────────────────────────────────────────────────
    # pgvector uses postgres_dsn — no separate vector_store_path needed.
    # vector_store_path kept for backward compatibility with existing .env files.
    vector_store_path: str = "./vector_store"
    rag_enabled: bool = True
    rag_top_k: int = 5
    # Minimum confidence to present a solution before creating a ticket
    rag_similarity_threshold: float = 0.6

    # Background RAG sync — keeps the vector store up to date with
    # newly-resolved tickets from the backend (Odoo / Express).
    # Default: every 6 hours. Set to 0 to disable periodic sync
    # (manual sync via /agent/rag/sync is still available).
    rag_sync_enabled: bool = True
    rag_sync_interval_hours: int = 6

    # ── LLM concurrency ──────────────────────────────────────────────────────
    # Max simultaneous LLM calls before requests wait in line.
    # Prevents saturating the provider (Groq: 30 req/min, Vercel: variable).
    # Requests beyond this limit wait up to llm_semaphore_timeout seconds.
    llm_max_concurrent: int = 20
    # Seconds a request waits for a slot in the semaphore before getting
    # a "system busy" reply.
    llm_semaphore_timeout: float = 30.0

    # ── HTTP client pool (Fase 8 — async migration) ──────────────────────────
    # httpx.AsyncClient connection pool size. The adapter's AsyncClient is
    # configured with these values. 50 connections support ~50 concurrent users
    # without saturating the pool.
    httpx_max_connections: int = 50
    # Max keepalive connections in the pool. Keep a warm subset to avoid
    # handshake overhead on hot paths.
    httpx_max_keepalive: int = 20

    # ── Async tools feature flag (Fase 8) ────────────────────────────────────
    # When True (default), tools are async def and run directly in the event loop.
    # When False, tools fall back to sync (compatibility mode for slow migration).
    # Set to False only as an emergency rollback — the async path is faster.
    enable_async_tools: bool = True

    # ── Shared cache (Fase 8 — multi-worker) ────────────────────────────────
    # TTL for creator/resolver context cache entries in PostgreSQL.
    # 3600 = 1 hour. Use 1800 for shorter freshness, 7200 for less DB load.
    cache_ttl_seconds: int = 300  # 5 minutes — stale context is worse than extra Odoo call

    # ── Rate limiting ────────────────────────────────────────────────────────
    # Per-user sliding-window limit (requests per 60 seconds).
    # Applied to /agent/chat and /agent/stream.
    # For multi-worker production: set this via .env and back the counter with Redis.
    rate_limit_per_minute: int = 10

    # ── Auth ─────────────────────────────────────────────────────────────────
    # Header: X-Agent-Key (dev fallback)
    # Header: Authorization: Bearer <token> (production — JWT)
    # To upgrade to OAuth2/JWT:
    #   1. Replace api_key_middleware with FastAPI OAuth2PasswordBearer dependency
    #   2. Business logic in routes stays unchanged
    agent_api_key: str = "dev-key-change-in-prod"

    # ── JWT (production auth) ──────────────────────────────────────────────────
    # Secret key used to sign JWTs. Must be at least 32 chars in production.
    # Generate with: python -c "import secrets; print(secrets.token_hex(32))"
    jwt_secret: str = "dev-jwt-secret-do-not-use-in-production-change-me"
    # Algorithm for JWT signing (HS256 = HMAC-SHA256)
    jwt_algorithm: str = "HS256"
    # Token expiration in hours (0 = no expiration)
    jwt_expiration_hours: int = 8

    # ── Conversation persistence ─────────────────────────────────────────────
    # "memory"   → InMemorySaver (lost on restart, dev only)
    # "postgres" → AsyncPostgresSaver (production — required for multi-user concurrency)
    # NOTE 2026-06-11: SQLite checkpoint support removed. The default is now
    # PostgreSQL (the checkpointer and the RAG share the same DSN).
    checkpoint_backend: str = "postgres"
    # PostgreSQL DSN — used for both the checkpointer and the RAG.
    # Format: postgresql://user:password@host:5432/dbname
    postgres_dsn: str = ""

    # ── AI feedback (separate from ticket CSAT) ──────────────────────────────
    # Stores ratings of the AI assistant's helpfulness — NOT ticket satisfaction.
    # Ticket CSAT is handled natively by the enterprise system (satisfaction_rating).
    # Lives in PostgreSQL (same DSN as RAG + checkpointer) — see feedback/collector.py.

    # ── Server ───────────────────────────────────────────────────────────────
    port: int = 8001  # Port 8000 is reserved for agent-v1
    cors_origins: List[str] = ["*"]

    # ── Agent core tuning ────────────────────────────────────────────────────
    # Maximum threads kept in the in-memory creator/resolver context cache.
    # When the cache reaches this size, the oldest entry is evicted.
    # Only used in single-process dev (multi-worker uses PostgreSQL cache).
    context_cache_max_size: int = 500

    # Number of non-system messages to keep in the LLM context window.
    # Older messages are trimmed by the pre_model_hook to prevent unbounded growth.
    # The trim_hook additionally PROTECTS any AIMessage with tool_calls
    # pending confirmation, so it never gets cut regardless of this limit.
    # See core/agent.py::trim_hook for the trimming logic.
    chat_history_trim_limit: int = 8

    # Maximum characters per ToolMessage content before truncation.
    # Tool results (e.g. suggest_solution, catalog queries) can be very large.
    # Truncating them keeps context within bounds without losing the signal.
    tool_message_max_chars: int = 2000

    # ── Conversation resilience (rate-limit survival) ───────────────────────
    # Seconds the agent keeps a thread "alive" after a failed LLM call so
    # the user can resend the same message and continue the conversation.
    # After this window, the next message starts a fresh conversation.
    # Default: 120s (2 minutes) — long enough for a manual retry, short
    # enough to avoid confusing two unrelated questions.
    continuity_window_seconds: int = 120

    # ── LLM retry on transient rate limits ──────────────────────────────────
    # When the LLM provider returns 429/502/503, retry up to N times with
    # exponential backoff. Applies to both /agent/chat and /agent/stream.
    # Delays are in seconds, one entry per retry.
    llm_max_retries: int = 3
    llm_retry_delays: List[float] = [1.0, 2.0, 4.0]

    # ── Escalation thresholds (background scheduler) ────────────────────────
    # Hours of inactivity before a reminder is sent to the assigned agent.
    escalation_agent_hours: int = 4
    # Hours of inactivity before the supervisor is notified.
    escalation_supervisor_hours: int = 6
    # Maximum tickets scanned per escalation check (avoids loading the whole table).
    escalation_scan_limit: int = 200

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        # extra="ignore" allows third-party env vars (e.g. LANGCHAIN_*, HF_TOKEN)
        # to coexist in .env without causing a ValidationError at startup.
        extra = "ignore"


settings = Settings()
