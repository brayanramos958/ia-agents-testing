"""
Application configuration — single source of truth.
All values come from environment variables or .env file.
"""

from pydantic_settings import BaseSettings
from typing import List


class Settings(BaseSettings):
    # ── LLM ────────────────────────────────────────────────────────────────
    groq_api_key: str
    llm_model: str = "meta-llama/llama-4-scout-17b-16e-instruct"
    openrouter_api_key: str = ""
    openrouter_model: str = "meta-llama/llama-3.3-70b-instruct:free"
    # Modelos free de OpenRouter usados como cadena de fallback cuando Groq hace rate limit.
    # Se intentan en orden — si uno falla con 429, se pasa al siguiente.
    # Verificados en OpenRouter API (abril 2026) — todos soportan tool calling y son gratuitos.
    # Verificados en OpenRouter API (abril 2026) — todos soportan tool calling y son gratuitos.
    openrouter_fallback_models: List[str] = [
        "meta-llama/llama-3.3-70b-instruct:free",
        "nvidia/nemotron-3-super-120b-a12b:free",
        "openai/gpt-oss-120b:free",
        "openai/gpt-oss-20b:free",
        "nvidia/nemotron-3-nano-30b-a3b:free",
        "qwen/qwen3-coder:free",
        "google/gemma-4-31b-it:free",
    ]

    # ── Backend adapter ─────────────────────────────────────────────────────
    # "express"  → ExpressAdapter (local dev, simplified schema)
    # "http"     → HttpAdapter (production — configurable for Odoo REST API)
    # "postgres" → PostgresAdapter (future — direct DB access)
    backend_adapter: str = "express"
    backend_url: str = "http://localhost:3001"

    # HttpAdapter — Odoo REST API config (only needed when backend_adapter=http)
    odoo_base_url: str = ""
    odoo_api_key: str = ""
    odoo_database: str = ""

    # ── RAG ─────────────────────────────────────────────────────────────────
    vector_store_path: str = "./vector_store"
    rag_enabled: bool = True
    rag_top_k: int = 5
    # Minimum confidence to present a solution before creating a ticket
    rag_similarity_threshold: float = 0.6

    # ── Auth ─────────────────────────────────────────────────────────────────
    # Header: X-Agent-Key
    # To upgrade to OAuth2/JWT:
    #   1. Replace api_key_middleware with FastAPI OAuth2PasswordBearer dependency
    #   2. Business logic in routes stays unchanged
    agent_api_key: str = "dev-key-change-in-prod"

    # ── Conversation persistence ─────────────────────────────────────────────
    # "memory" → InMemorySaver (lost on restart, ok for dev)
    # "sqlite" → SqliteSaver (persists across restarts, recommended)
    checkpoint_backend: str = "sqlite"
    checkpoint_db_path: str = "./checkpoints.db"

    # ── AI feedback (separate from ticket CSAT) ──────────────────────────────
    # Stores ratings of the AI assistant's helpfulness — NOT ticket satisfaction.
    # Ticket CSAT is handled natively by the enterprise system (satisfaction_rating).
    feedback_db_path: str = "./feedback.db"

    # ── Server ───────────────────────────────────────────────────────────────
    port: int = 8001  # Port 8000 is reserved for agent-v1
    cors_origins: List[str] = ["*"]

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()
