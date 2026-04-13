"""
LLM and checkpointer factory functions.

build_llm()          → Groq with OpenRouter fallback
build_checkpointer() → InMemorySaver or SqliteSaver based on settings
"""

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI
from config.settings import settings


def build_llm():
    """
    Primario: Groq llama3-8b-8192 (30K TPM — soporta el payload del agente).
    Fallback: OpenRouter si Groq no está disponible.

    NOTA: los modelos free de OpenRouter tienen ~1 RPM.
    Groq con llama3-8b-8192 tiene 30K TPM — suficiente para el agente.
    """
    primary = ChatGroq(
        api_key=settings.groq_api_key,
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        temperature=0.1,
    )
    print(f"[LLM] Using Groq: meta-llama/llama-4-scout-17b-16e-instruct (30K TPM)")
    return primary


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
