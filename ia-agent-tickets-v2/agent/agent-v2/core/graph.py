"""
LLM and checkpointer factory functions.

build_llm()          → builds LLM based on LLM_PROVIDER env var
init_checkpointer()  → async init: opens DB connection, stores instance
build_checkpointer() → returns the initialized instance (or MemorySaver as fallback)

Supported LLM providers (LLM_PROVIDER):
  vercel → Vercel AI Gateway — OpenAI-compatible, minimax/minimax-m2.7 (default, production)
  groq   → Groq API primary + OpenRouter fallback chain
  ollama → Ollama local server (development)

Supported checkpoint backends:
  postgres → AsyncPostgresSaver (production / multi-user concurrency)
  memory   → MemorySaver        (dev / no persistence)
"""

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from config.settings import settings
from core.logging import get_logger

_log = get_logger(__name__)

# Module-level holder — set once during lifespan startup
_checkpointer_instance = None


def _build_vercel_llm():
    if not settings.ai_gateway_api_key:
        raise RuntimeError(
            "LLM_PROVIDER=vercel requires AI_GATEWAY_API_KEY to be set in .env.\n"
            "Get your key at https://vercel.com/dashboard → AI Gateway."
        )

    # DeepSeek V4 Pro runs in "thinking mode" by default which:
    #   1. Ignores tool definitions when tool_choice='auto'
    #   2. Rejects tool_choice='any' with 400 Bad Request
    # Disabling thinking makes it a standard chat model that handles tool calling.
    extra_body = {}
    if "deepseek" in settings.ai_gateway_model.lower():
        extra_body = {"thinking": {"type": "disabled"}}

    llm = ChatOpenAI(
        api_key=settings.ai_gateway_api_key,
        base_url=settings.ai_gateway_base_url,
        model=settings.ai_gateway_model,
        temperature=0.1,
        timeout=60,
        extra_body=extra_body,
    )
    _log.info("llm_init", extra={"provider": "vercel", "model": settings.ai_gateway_model, "base_url": settings.ai_gateway_base_url, "thinking_disabled": bool(extra_body)})
    return llm


def _build_ollama_llm():
    from langchain_ollama import ChatOllama
    llm = ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=0.1,
        num_ctx=8192,  # cap context to prevent OOM crashes on CPU
        think=False,   # disable Qwen3 chain-of-thought — reduces tokens and prevents crashes
    )
    _log.info("llm_init", extra={"provider": "ollama", "model": settings.ollama_model, "base_url": settings.ollama_base_url})
    return llm


def _build_groq_llm():
    """
    Primario: Groq meta-llama/llama-4-scout-17b-16e-instruct.

    Cadena de fallback cuando Groq (o cualquier modelo previo) devuelve 429:
      Groq → OpenRouter[0] → OpenRouter[1] → ... → OpenRouter[N]
    """
    if not settings.groq_api_key:
        raise RuntimeError(
            "LLM_PROVIDER=groq requires GROQ_API_KEY to be set in .env.\n"
            "To use Ollama locally, set LLM_PROVIDER=ollama instead."
        )

    from groq import RateLimitError as GroqRateLimitError
    from openai import (
        RateLimitError as OpenAIRateLimitError,
        NotFoundError as OpenAINotFoundError,
        APIStatusError as OpenAIAPIStatusError,  # catches 402 spend-limit and other HTTP errors
    )

    primary = ChatGroq(
        api_key=settings.groq_api_key,
        model=settings.llm_model,
        temperature=0.1,
    )

    if not settings.openrouter_api_key:
        _log.info("llm_init", extra={"provider": "groq", "model": settings.llm_model, "fallback_enabled": False})
        return primary

    fallbacks = [
        ChatOpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            model=model,
            temperature=0.1,
            timeout=60,  # fail-fast per model — prevents hanging on exhausted/slow providers
        )
        for model in settings.openrouter_fallback_models
    ]

    _log.info("llm_init", extra={"provider": "groq", "model": settings.llm_model, "fallback_count": len(fallbacks)})

    return primary.with_fallbacks(
        fallbacks,
        exceptions_to_handle=(
            GroqRateLimitError,
            OpenAIRateLimitError,
            OpenAINotFoundError,
            OpenAIAPIStatusError,  # handles 402 spend-limit from OpenRouter
        ),
    )


def build_llm():
    # Pre-register the active provider in the circuit breaker registry so
    # /agent/llm-status has data to show even before the first LLM call.
    # This is idempotent — the status is created once and reused.
    from core.circuit_breaker import get_provider_status
    if settings.llm_provider == "vercel":
        get_provider_status(settings.ai_gateway_model)
        return _build_vercel_llm()
    if settings.llm_provider == "ollama":
        get_provider_status(settings.ollama_model)
        return _build_ollama_llm()
    get_provider_status(settings.llm_model)
    return _build_groq_llm()


async def init_checkpointer() -> None:
    """
    Initializes the checkpointer backend and stores a ready-to-use instance.

    Must be called once during FastAPI lifespan startup before any request
    arrives. The connection stays open for the lifetime of the process.

    Backends:
      postgres → AsyncPostgresSaver via psycopg pool (production)
      *        → MemorySaver (in-memory, lost on restart)
    """
    global _checkpointer_instance

    if settings.checkpoint_backend == "postgres":
        if not settings.postgres_dsn:
            raise RuntimeError(
                "CHECKPOINT_BACKEND=postgres requires POSTGRES_DSN to be set in .env.\n"
                "Format: postgresql://user:password@host:5432/dbname"
            )
        import psycopg
        from psycopg_pool import AsyncConnectionPool
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        # setup() runs CREATE INDEX CONCURRENTLY which requires autocommit=True.
        # Use a dedicated autocommit connection only for migrations, then close it.
        async with await psycopg.AsyncConnection.connect(
            settings.postgres_dsn, autocommit=True
        ) as setup_conn:
            await AsyncPostgresSaver(setup_conn).setup()

        # Pool for actual request handling — standard transaction mode.
        # psycopg3 accepts standard postgresql:// URIs (not postgresql+psycopg://).
        pool = AsyncConnectionPool(conninfo=settings.postgres_dsn, max_size=20, open=False)
        await pool.open()
        _checkpointer_instance = AsyncPostgresSaver(pool)
        _log.info("checkpointer_ready", extra={"backend": "postgres", "host": settings.postgres_dsn.split("@")[-1]})

    else:
        from langgraph.checkpoint.memory import MemorySaver
        _checkpointer_instance = MemorySaver()
        _log.info("checkpointer_ready", extra={"backend": "memory"})


def build_checkpointer():
    """
    Returns the pre-initialized checkpointer instance.

    Raises RuntimeError if init_checkpointer() was never awaited — this
    means the lifespan startup did not complete before a request arrived.
    """
    if _checkpointer_instance is None:
        raise RuntimeError(
            "Checkpointer not initialized. "
            "Ensure init_checkpointer() is awaited during FastAPI lifespan startup."
        )
    return _checkpointer_instance
