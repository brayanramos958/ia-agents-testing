"""
ChromaDB-backed RAG store implementing IRAGPort.

Seeds from the ticket REST API at startup — never reads SQLite directly.
Updates in real time when a ticket is resolved.
"""

import os
from langchain_chroma import Chroma
from langchain_core.documents import Document

from ports.rag_port import IRAGPort, SuggestionResult, SolutionItem
from rag.embeddings import get_embeddings


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

        solutions = []
        highest_score = 0.0

        for doc, score in results:
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
                score=round(score, 3),
            ))

        return SuggestionResult(
            solutions_found=len(solutions) > 0,
            solutions=solutions,
            confidence=round(highest_score, 3),
        )

    def add_resolved_ticket(self, ticket_id: int, ticket_name: str,
                            ticket_type: str, category: str,
                            description: str, motivo_resolucion: str) -> bool:
        if not self._enabled:
            return False

        document_text = (
            f"Category: {category}. "
            f"Type: {ticket_type}. "
            f"Problem: {description}. "
            f"Resolution: {motivo_resolucion}"
        )
        doc = Document(
            page_content=document_text,
            metadata={
                "ticket_id": ticket_id,
                "ticket_name": ticket_name,
                "ticket_type": ticket_type,
                "category": category,
                "description": description,
                "motivo_resolucion": motivo_resolucion,
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
            motivo = ticket.get("motivo_resolucion") or ticket.get("resolucion", "")
            if not motivo:
                continue  # Skip unresolved or missing resolution
            document_text = (
                f"Category: {ticket.get('category', '')}. "
                f"Type: {ticket.get('ticket_type', '')}. "
                f"Problem: {ticket.get('description', '')}. "
                f"Resolution: {motivo}"
            )
            documents.append(Document(
                page_content=document_text,
                metadata={
                    "ticket_id": ticket.get("ticket_id", 0),
                    "ticket_name": ticket.get("ticket_name", ""),
                    "ticket_type": ticket.get("ticket_type", ""),
                    "category": ticket.get("category", ""),
                    "description": ticket.get("description", ""),
                    "motivo_resolucion": motivo,
                },
            ))

        if documents:
            self._store.add_documents(documents)

        return len(documents)

    def count(self) -> int:
        if not self._enabled:
            return 0
        return self._store._collection.count()
