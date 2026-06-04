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
  sqlite   → AsyncSqliteSaver   (dev / single-worker)
  postgres → AsyncPostgresSaver (production / multi-user concurrency)
  memory   → MemorySaver        (dev / no persistence)
"""

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from config.settings import settings
from core.circuit_breaker import retry_with_backoff, get_provider_status, CircuitOpenError, RateLimitError

# Module-level holder — set once during lifespan startup
_checkpointer_instance = None


def _build_vercel_llm():
    if not settings.ai_gateway_api_key:
        raise RuntimeError(
            "LLM_PROVIDER=vercel requires AI_GATEWAY_API_KEY to be set in .env.\n"
            "Get your key at https://vercel.com/dashboard → AI Gateway."
        )

    from openai import RateLimitError as OpenAIRateLimitError, APIStatusError as OpenAIAPIStatusError

    primary = ChatOpenAI(
        api_key=settings.ai_gateway_api_key,
        base_url=settings.ai_gateway_base_url,
        model=settings.ai_gateway_model,
        temperature=0.1,
        timeout=settings.llm_timeout,
    )
    # Register provider status for circuit breaker
    get_provider_status(settings.ai_gateway_model)
    print(f"[LLM] Vercel AI Gateway: {settings.ai_gateway_model} @ {settings.ai_gateway_base_url} (timeout={settings.llm_timeout}s)")

    # Fallback chain: Groq → OpenRouter (si están configurados)
    fallbacks = []

    if settings.groq_api_key:
        from langchain_groq import ChatGroq
        groq_llm = ChatGroq(
            api_key=settings.groq_api_key,
            model=settings.llm_model,
            temperature=0.1,
        )
        get_provider_status(f"groq/{settings.llm_model}")
        fallbacks.append(groq_llm)
        print(f"[LLM] Fallback 1: Groq {settings.llm_model}")

    if settings.openrouter_api_key:
        for model in settings.openrouter_fallback_models:
            fallbacks.append(ChatOpenAI(
                api_key=settings.openrouter_api_key,
                base_url="https://openrouter.ai/api/v1",
                model=model,
                temperature=0.1,
                timeout=60,
            ))
        print(f"[LLM] Fallback 2+: OpenRouter {settings.openrouter_fallback_models}")

    if not fallbacks:
        return primary

    from groq import RateLimitError as GroqRateLimitError
    return primary.with_fallbacks(
        fallbacks,
        exceptions_to_handle=(
            GroqRateLimitError,
            OpenAIRateLimitError,
            OpenAIAPIStatusError,
        ),
    )


def _build_ollama_llm():
    from langchain_ollama import ChatOllama
    llm = ChatOllama(
        base_url=settings.ollama_base_url,
        model=settings.ollama_model,
        temperature=0.1,
        num_ctx=8192,  # cap context to prevent OOM crashes on CPU
        think=False,   # disable Qwen3 chain-of-thought — reduces tokens and prevents crashes
    )
    print(f"[LLM] Ollama: {settings.ollama_model} @ {settings.ollama_base_url} (ctx=8192, think=off)")
    return llm


def _build_anthropic_llm():
    """Builds ChatAnthropic for Anthropic's Claude API."""
    if not settings.anthropic_api_key:
        raise RuntimeError(
            "LLM_PROVIDER=anthropic requires ANTHROPIC_API_KEY to be set in env.docker.\n"
            "Get your key at https://console.anthropic.com/"
        )
    from langchain_anthropic import ChatAnthropic

    llm = ChatAnthropic(
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
        temperature=0.1,
        timeout=60,
        max_tokens=4096,  # suficiente para respuestas de helpdesk
    )
    print(f"[LLM] Anthropic: {settings.anthropic_model}")
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
        print("[LLM] Groq: meta-llama/llama-4-scout-17b-16e-instruct (sin fallback — OPENROUTER_API_KEY no configurada)")
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

    names = " -> ".join(settings.openrouter_fallback_models)
    print(f"[LLM] Groq: {settings.llm_model} -> fallbacks: {names}")

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
    if settings.llm_provider == "vercel":
        return _build_vercel_llm()
    if settings.llm_provider == "ollama":
        return _build_ollama_llm()
    if settings.llm_provider == "anthropic":
        return _build_anthropic_llm()
    return _build_groq_llm()


# ── Security classifier (Cap 2) ─────────────────────────────────────────────
# Lightweight model that runs BEFORE the main LLM to detect prompt injection,
# jailbreak attempts, and role impersonation. Uses the same Vercel Gateway API key
# but a much cheaper model (~$0.00015/request). Cached by thread_id.

_security_llm = None


def build_security_classifier():
    """
    Returns a ChatOpenAI instance wired to the Vercel AI Gateway with the
    cheap security classifier model.

    Only built when security_classifier_enabled=True and llm_provider=vercel.
    For other providers (groq, ollama), security classification is skipped.
    """
    global _security_llm
    if _security_llm is not None:
        return _security_llm

    if not settings.security_classifier_enabled:
        return None
    if settings.llm_provider != "vercel":
        return None
    if not settings.ai_gateway_api_key:
        return None

    _security_llm = ChatOpenAI(
        api_key=settings.ai_gateway_api_key,
        base_url=settings.ai_gateway_base_url,
        model=settings.security_classifier_model,
        temperature=0,        # deterministic — same input always gives same verdict
        max_tokens=5,         # only needs to output SAFE or UNSAFE
        timeout=10,           # fast fail — don't block the user for security checks
    )
    print(f"[security] Classifier ready: {settings.security_classifier_model} @ {settings.ai_gateway_base_url}")
    return _security_llm


async def init_checkpointer() -> None:
    """
    Initializes the checkpointer backend and stores a ready-to-use instance.

    Must be called once during FastAPI lifespan startup before any request
    arrives. The connection stays open for the lifetime of the process.

    Backends:
      sqlite   → AsyncSqliteSaver via aiosqlite (dev / single-worker)
      postgres → AsyncPostgresSaver via psycopg pool (production)
      *        → MemorySaver (in-memory, lost on restart)
    """
    global _checkpointer_instance

    if settings.checkpoint_backend == "sqlite":
        import aiosqlite
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

        conn = await aiosqlite.connect(settings.checkpoint_db_path)
        checkpointer = AsyncSqliteSaver(conn)
        await checkpointer.setup()
        _checkpointer_instance = checkpointer
        print(f"[checkpointer] AsyncSqliteSaver ready — {settings.checkpoint_db_path}")

    elif settings.checkpoint_backend == "postgres":
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
        print(f"[checkpointer] AsyncPostgresSaver ready — {settings.postgres_dsn.split('@')[-1]}")

    else:
        from langgraph.checkpoint.memory import MemorySaver
        _checkpointer_instance = MemorySaver()
        print("[checkpointer] MemorySaver ready (in-memory, lost on restart)")


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
