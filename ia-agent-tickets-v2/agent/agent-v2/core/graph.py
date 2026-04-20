"""
LLM and checkpointer factory functions.

build_llm()          → Groq primary + OpenRouter fallback on rate limit
init_checkpointer()  → async init: opens DB connection, stores instance
build_checkpointer() → returns the initialized instance (or MemorySaver as fallback)

Supported checkpoint backends:
  sqlite   → AsyncSqliteSaver   (dev / single-worker)
  postgres → AsyncPostgresSaver (production / multi-user concurrency)
  memory   → MemorySaver        (dev / no persistence)
"""

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from config.settings import settings

# Module-level holder — set once during lifespan startup
_checkpointer_instance = None


def build_llm():
    """
    Primario: Groq meta-llama/llama-4-scout-17b-16e-instruct.

    Cadena de fallback cuando Groq (o cualquier modelo previo) devuelve 429:
      Groq → OpenRouter[0] → OpenRouter[1] → ... → OpenRouter[N]

    with_fallbacks() intenta cada fallback en orden hasta que uno responde.
    Se interceptan tanto groq.RateLimitError como openai.RateLimitError
    para cubrir errores de rate limit en cualquier punto de la cadena.
    """
    from groq import RateLimitError as GroqRateLimitError
    from openai import RateLimitError as OpenAIRateLimitError, NotFoundError as OpenAINotFoundError

    primary = ChatGroq(
        api_key=settings.groq_api_key,
        model="meta-llama/llama-4-scout-17b-16e-instruct",
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
        )
        for model in settings.openrouter_fallback_models
    ]

    names = " → ".join(settings.openrouter_fallback_models)
    print(f"[LLM] Groq: llama-4-scout → fallbacks: {names}")

    return primary.with_fallbacks(
        fallbacks,
        exceptions_to_handle=(GroqRateLimitError, OpenAIRateLimitError, OpenAINotFoundError),
    )


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
        from psycopg_pool import AsyncConnectionPool
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        # psycopg3 requires the postgresql+psycopg scheme for async pool.
        # Replace standard postgresql:// prefix if user omitted the driver suffix.
        dsn = settings.postgres_dsn
        if dsn.startswith("postgresql://") and "+psycopg" not in dsn:
            dsn = dsn.replace("postgresql://", "postgresql+psycopg://", 1)

        pool = AsyncConnectionPool(conninfo=dsn, max_size=20, open=False)
        await pool.open()
        checkpointer = AsyncPostgresSaver(pool)
        await checkpointer.setup()
        _checkpointer_instance = checkpointer
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
