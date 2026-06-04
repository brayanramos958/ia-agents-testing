"""
HuggingFace embeddings singleton.

Uses lru_cache so the model is loaded exactly once per process.
Loading sentence-transformers is expensive (~2s, ~100MB RAM).

To reset in tests: call get_embeddings.cache_clear()
"""

from functools import lru_cache
from langchain_huggingface import HuggingFaceEmbeddings


@lru_cache(maxsize=1)
def get_embeddings() -> HuggingFaceEmbeddings:
    """
    Returns the shared HuggingFace embeddings instance.
    Model: all-MiniLM-L6-v2 — lightweight, runs locally, no API calls.
    """
    return HuggingFaceEmbeddings(
        model_name="sentence-transformers/all-MiniLM-L6-v2",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    )
