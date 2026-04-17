"""
ChromaDB-backed RAG store implementing IRAGPort.

Seeds from the ticket REST API at startup — never reads SQLite directly.
Updates in real time when a ticket is resolved.
"""

import os
import html
import re
from langchain_chroma import Chroma
from langchain_core.documents import Document

from ports.rag_port import IRAGPort, SuggestionResult, SolutionItem
from rag.embeddings import get_embeddings
from config.settings import settings


def _strip_html(text: str) -> str:
    """
    Remove HTML tags and decode HTML entities from Odoo fields.Html content.

    Odoo stores motivo_resolucion, causa_raiz, and descripcion as fields.Html,
    which means they arrive with <p>, <br/>, <strong>, &amp;, &#39;, etc.
    These tags contaminate ChromaDB embeddings with non-semantic noise and
    prevent the similarity search from finding relevant solutions.

    Process:
    1. Decode HTML entities first (&amp; → &, &#39; → ', &lt; → <, etc.)
    2. Replace all HTML tags with a space (preserves word boundaries)
    3. Collapse consecutive whitespace into a single space
    """
    if not text:
        return ""
    text = html.unescape(str(text))
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


class ChromaRAGStore(IRAGPort):

    COLLECTION_NAME = "resolved_tickets"

    def __init__(self, persist_path: str, enabled: bool = True):
        """
        Args:
            persist_path: Directory where ChromaDB stores its data.
                          Comes from settings.vector_store_path — no hardcoded paths.
            enabled: If False, all methods return empty results (for testing without GPU).
        """
        self._enabled = enabled
        self._persist_path = persist_path

        if enabled:
            os.makedirs(persist_path, exist_ok=True)
            self._store = Chroma(
                collection_name=self.COLLECTION_NAME,
                embedding_function=get_embeddings(),
                persist_directory=persist_path,
            )

    def search_similar(self, query: str, category: str = None,
                       k: int = 5) -> SuggestionResult:
        if not self._enabled:
            return SuggestionResult(solutions_found=False)

        full_query = f"Problem: {query}"
        if category:
            full_query = f"Category: {category}. {full_query}"

        try:
            results = self._store.similarity_search_with_relevance_scores(
                full_query, k=k
            )
        except Exception:
            return SuggestionResult(solutions_found=False)

        if not results:
            return SuggestionResult(solutions_found=False)

        threshold = settings.rag_similarity_threshold
        solutions = []
        highest_score = 0.0

        for doc, score in results:
            # Skip results below the configured similarity threshold.
            # Without this filter the agent receives low-confidence suggestions
            # (e.g. score=0.3) that are semantically unrelated to the query.
            if score < threshold:
                continue
            if score > highest_score:
                highest_score = score
            meta = doc.metadata
            solutions.append(SolutionItem(
                ticket_name=meta.get("ticket_name", ""),
                ticket_id=meta.get("ticket_id", 0),
                category=meta.get("category", ""),
                ticket_type=meta.get("ticket_type", ""),
                description=meta.get("description", ""),
                motivo_resolucion=meta.get("motivo_resolucion", ""),
                causa_raiz=meta.get("causa_raiz", ""),
                score=round(score, 3),
            ))

        return SuggestionResult(
            solutions_found=len(solutions) > 0,
            solutions=solutions,
            confidence=round(highest_score, 3),
        )

    def add_resolved_ticket(self, ticket_id: int, ticket_name: str,
                            ticket_type: str, category: str,
                            description: str, motivo_resolucion: str,
                            causa_raiz: str = "") -> bool:
        if not self._enabled:
            return False

        # Strip HTML from Odoo fields.Html content before embedding.
        # These fields arrive with <p>, <br/>, <strong>, &amp; etc. from Odoo
        # and must be cleaned before building the document_text for ChromaDB.
        clean_description   = _strip_html(description)
        clean_motivo        = _strip_html(motivo_resolucion)
        clean_causa         = _strip_html(causa_raiz)

        # causa_raiz is embedded alongside the resolution so semantic search
        # can match root-cause patterns across similar tickets.
        root_cause_part = f" Root cause: {clean_causa}." if clean_causa else ""
        document_text = (
            f"Category: {category}. "
            f"Type: {ticket_type}. "
            f"Problem: {clean_description}. "
            f"Resolution: {clean_motivo}."
            f"{root_cause_part}"
        )

        # Deduplication: if a document for this ticket_id already exists,
        # delete it before adding the updated version.
        # This handles the case where the same ticket is re-resolved (e.g.
        # after being reopened) — the old embedding is replaced, not duplicated.
        existing = self._store.get(where={"ticket_id": ticket_id})
        if existing and existing.get("ids"):
            self._store.delete(ids=existing["ids"])

        doc = Document(
            page_content=document_text,
            metadata={
                "ticket_id": ticket_id,
                "ticket_name": ticket_name,
                "ticket_type": ticket_type,
                "category": category,
                "description": clean_description,
                "motivo_resolucion": clean_motivo,
                "causa_raiz": clean_causa,
            },
        )
        self._store.add_documents([doc])
        return True

    def initialize_from_resolved_tickets(self, tickets: list) -> int:
        """
        Seeds the vector store if it is empty.
        Does NOT re-seed on every restart to preserve performance.
        """
        if not self._enabled:
            return 0

        if self._store._collection.count() > 0:
            return 0  # Already seeded — skip

        documents = []
        for ticket in tickets:
            motivo_raw = ticket.get("motivo_resolucion") or ticket.get("resolucion", "")
            if not motivo_raw:
                continue  # Skip unresolved or missing resolution

            # Strip HTML from all Odoo fields.Html content at seed time.
            # Seeds come from get_resolved_tickets() which returns raw HTML
            # from Odoo — same contamination risk as real-time add_resolved_ticket.
            clean_description = _strip_html(ticket.get("description", ""))
            clean_motivo      = _strip_html(motivo_raw)
            clean_causa       = _strip_html(ticket.get("causa_raiz", ""))

            root_cause_part = f" Root cause: {clean_causa}." if clean_causa else ""
            document_text = (
                f"Category: {ticket.get('category', '')}. "
                f"Type: {ticket.get('ticket_type', '')}. "
                f"Problem: {clean_description}. "
                f"Resolution: {clean_motivo}."
                f"{root_cause_part}"
            )
            documents.append(Document(
                page_content=document_text,
                metadata={
                    "ticket_id": ticket.get("ticket_id", 0),
                    "ticket_name": ticket.get("ticket_name", ""),
                    "ticket_type": ticket.get("ticket_type", ""),
                    "category": ticket.get("category", ""),
                    "description": clean_description,
                    "motivo_resolucion": clean_motivo,
                    "causa_raiz": clean_causa,
                },
            ))

        if documents:
            self._store.add_documents(documents)

        return len(documents)

    def count(self) -> int:
        if not self._enabled:
            return 0
        return self._store._collection.count()
