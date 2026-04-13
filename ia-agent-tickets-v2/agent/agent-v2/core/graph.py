"""
LLM and checkpointer factory functions.

build_llm()          → Groq primary + OpenRouter fallback on rate limit
build_checkpointer() → InMemorySaver or SqliteSaver based on settings
"""

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from config.settings import settings


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


def build_checkpointer():
    """
    Creates the conversation memory backend.

    "memory" → InMemorySaver: fast but lost on restart (dev only)
    "sqlite" → SqliteSaver: persists across restarts (recommended)
    """
    if settings.checkpoint_backend == "sqlite":
        import sqlite3
        from langgraph.checkpoint.sqlite import SqliteSaver
        # from_conn_string() returns a context manager in langgraph v3+.
        # Pass a raw connection instead to get the saver directly.
        conn = sqlite3.connect(settings.checkpoint_db_path, check_same_thread=False)
        return SqliteSaver(conn)

    from langgraph.checkpoint.memory import MemorySaver
    return MemorySaver()
