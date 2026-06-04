"""
PostgreSQL + pgvector RAG store implementing IRAGPort.

Replaces ChromaDB. Uses the same PostgreSQL instance as the LangGraph checkpointer
— no extra service required.

Requirements:
  PostgreSQL 14+ with pgvector extension. The store creates it automatically:
    CREATE EXTENSION IF NOT EXISTS vector;
  Connection is read from settings.postgres_dsn.

Tables created by langchain_postgres (auto on first use):
  langchain_pg_collection  — collection metadata
  langchain_pg_embedding   — vectors + metadata (JSONB)
"""

import asyncio
import html
import re
import logging
from langchain_postgres import PGVector
from langchain_core.documents import Document

from ports.rag_port import IRAGPort, SuggestionResult, SolutionItem, BoostResult
from rag.embeddings import get_embeddings
from config.settings import settings

_log = logging.getLogger(__name__)


def _strip_html(text: str) -> str:
    """
    Remove HTML tags and decode entities from Odoo fields.Html content.
    Prevents tag noise from contaminating vector embeddings.
    """
    if not text:
        return ""
    text = html.unescape(str(text))
    text = re.sub(r'<[^>]+>', ' ', text)
    return re.sub(r'\s+', ' ', text).strip()


def _pg_dsn(dsn: str) -> str:
    """Convert postgresql:// to postgresql+psycopg:// required by langchain_postgres."""
    if dsn.startswith("postgresql://"):
        return dsn.replace("postgresql://", "postgresql+psycopg://", 1)
    if dsn.startswith("postgres://"):
        return dsn.replace("postgres://", "postgresql+psycopg://", 1)
    return dsn  # already has driver prefix


class PGVectorRAGStore(IRAGPort):

    COLLECTION_NAME = "resolved_tickets"
    # Boost multiplier per positive feedback — capped at 50% max boost
    _BOOST_FACTOR = 0.1
    _BOOST_CAP = 5  # max effective boosts (50% boost at cap)

    def __init__(self, postgres_dsn: str, enabled: bool = True):
        self._enabled = enabled
        self._store: PGVector | None = None
        self._boosts: dict[int, int] = {}  # ticket_id → boost_count

        if enabled:
            self._store = PGVector(
                embeddings=get_embeddings(),
                collection_name=self.COLLECTION_NAME,
                connection=_pg_dsn(postgres_dsn),
                use_jsonb=True,
                create_extension=True,
            )

    async def search_similar(self, query: str, category: str = None,
                             k: int = 5) -> SuggestionResult:
        if not self._enabled or not self._store:
            return SuggestionResult(solutions_found=False)

        full_query = f"Problem: {query}"
        if category:
            full_query = f"Category: {category}. {full_query}"

        # Fetch k*2 results and re-rank with boosts to surface confirmed-useful docs
        fetch_k = k * 2
        try:
            results = await asyncio.to_thread(
                self._store.similarity_search_with_relevance_scores, full_query, k=fetch_k)
        except Exception as exc:
            _log.warning("pgvector search failed: %s", exc)
            return SuggestionResult(solutions_found=False)

        if not results:
            return SuggestionResult(solutions_found=False)

        threshold = settings.rag_similarity_threshold
        scored = []

        for doc, score in results:
            if score < threshold:
                continue
            meta = doc.metadata
            tid = meta.get("ticket_id", 0)
            # Apply boost: each positive feedback adds _BOOST_FACTOR, capped at _BOOST_CAP
            boost = min(self._boosts.get(tid, 0), self._BOOST_CAP)
            adjusted = score * (1 + self._BOOST_FACTOR * boost)
            scored.append((adjusted, SolutionItem(
                ticket_name=meta.get("ticket_name", ""),
                ticket_id=tid,
                category=meta.get("category", ""),
                ticket_type=meta.get("ticket_type", ""),
                description=meta.get("description", ""),
                motivo_resolucion=meta.get("motivo_resolucion", ""),
                causa_raiz=meta.get("causa_raiz", ""),
                score=round(score, 3),
                source=meta.get("source", "ticket"),  # 'ticket' or 'knowledge'
            )))

        # Re-rank by adjusted score, return top k
        scored.sort(key=lambda x: -x[0])
        top = scored[:k]
        solutions = [s for _, s in top]
        highest = max((s[0] for s in scored), default=0.0)

        return SuggestionResult(
            solutions_found=len(solutions) > 0,
            solutions=solutions,
            confidence=round(min(highest, 1.0), 3),
        )

    async def add_resolved_ticket(self, ticket_id: int, ticket_name: str,
                                   ticket_type: str, category: str,
                                   description: str, motivo_resolucion: str,
                                   causa_raiz: str = "") -> bool:
        if not self._enabled or not self._store:
            return False

        clean_description = _strip_html(description)
        clean_motivo      = _strip_html(motivo_resolucion)
        clean_causa       = _strip_html(causa_raiz)

        root_cause_part = f" Root cause: {clean_causa}." if clean_causa else ""
        document_text = (
            f"Category: {category}. "
            f"Type: {ticket_type}. "
            f"Problem: {clean_description}. "
            f"Resolution: {clean_motivo}."
            f"{root_cause_part}"
        )

        doc = Document(
            page_content=document_text,
            metadata={
                "ticket_id":         ticket_id,
                "ticket_name":       ticket_name,
                "ticket_type":       ticket_type,
                "category":          category,
                "description":       clean_description,
                "motivo_resolucion": clean_motivo,
                "causa_raiz":        clean_causa,
            },
        )

        try:
            # Stable ID per ticket_id: PGVector upserts on ID collision,
            # so re-resolved tickets automatically replace their old embedding.
            await asyncio.to_thread(
                self._store.add_documents, [doc], ids=[f"ticket-{ticket_id}"])
        except Exception as exc:
            _log.warning("pgvector add_resolved_ticket failed: %s", exc)
            return False
        return True

    async def initialize_from_resolved_tickets(self, tickets: list) -> int:
        if not self._enabled or not self._store:
            return 0

        if await self.count() > 0:
            return 0  # Already seeded — skip

        documents = []
        ids = []

        for ticket in tickets:
            motivo_raw = ticket.get("motivo_resolucion") or ticket.get("resolucion", "")
            if not motivo_raw:
                continue

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
                    "ticket_id":         ticket.get("ticket_id", 0),
                    "ticket_name":       ticket.get("ticket_name", ""),
                    "ticket_type":       ticket.get("ticket_type", ""),
                    "category":          ticket.get("category", ""),
                    "description":       clean_description,
                    "motivo_resolucion": clean_motivo,
                    "causa_raiz":        clean_causa,
                },
            ))
            ids.append(f"ticket-{ticket.get('ticket_id', 0)}")

        if documents:
            try:
                await asyncio.to_thread(
                    self._store.add_documents, documents, ids=ids)
            except Exception as exc:
                _log.warning("pgvector seed failed: %s", exc)
                return 0

        return len(documents)

    async def seed_knowledge_articles(self, articles: list) -> int:
        """
        Add knowledge base articles to the same vector collection.
        
        Articles are stored alongside resolved tickets in the same collection
        with metadata source='knowledge' so search_similar finds both.
        
        Stable IDs use 'kb-{id}' prefix to avoid collision with 'ticket-{id}'.
        """
        if not self._enabled or not self._store:
            return 0

        documents = []
        ids = []

        for article in articles:
            name = article.get("name", "")
            body = article.get("body", "")
            if not body and not name:
                continue

            clean_body = _strip_html(body or "")
            keywords = article.get("keywords", "")
            category = article.get("category", "")

            document_text = (
                f"Knowledge Article: {name}. "
                f"Category: {category}. "
                f"Keywords: {keywords}. "
                f"Content: {clean_body}"
            )

            documents.append(Document(
                page_content=document_text,
                metadata={
                    "source":      "knowledge",
                    "article_id":  article.get("id", 0),
                    "name":        name,
                    "category":    category,
                    "keywords":    keywords,
                    "body":        clean_body,
                    "ticket_id":   0,        # not a ticket
                    "ticket_name": f"KB-{article.get('id', 0)}",
                    "ticket_type": "Knowledge",
                },
            ))
            ids.append(f"kb-{article.get('id', 0)}")

        if documents:
            try:
                await asyncio.to_thread(
                    self._store.add_documents, documents, ids=ids)
                _log.info("Seeded %d knowledge base articles into pgvector", len(documents))
            except Exception as exc:
                _log.warning("pgvector knowledge seed failed: %s", exc)
                return 0

        return len(documents)

    async def count(self) -> int:
        """Returns document count via direct SQL. Only used for startup logging."""
        if not self._enabled or not self._store:
            return 0
        try:
            import psycopg
            conn = await psycopg.AsyncConnection.connect(settings.postgres_dsn)
            try:
                row = await conn.execute(
                    "SELECT COUNT(*) FROM langchain_pg_embedding e "
                    "JOIN langchain_pg_collection c ON e.collection_id = c.uuid "
                    "WHERE c.name = %s",
                    (self.COLLECTION_NAME,),
                )
                result = await row.fetchone()
            finally:
                await conn.close()
            return result[0] if result else 0
        except Exception as exc:
            _log.debug("pgvector count failed: %s", exc)
            return 0

    async def boost_document(self, ticket_id: int) -> BoostResult:
        """
        Increment the boost counter for a document confirmed useful by a user.
        
        Boosts affect future search_similar() rankings by multiplying the
        cosine similarity score (10% per boost, capped at 50%).
        """
        if not self._enabled:
            return BoostResult(success=False, ticket_id=ticket_id,
                              message="RAG disabled")
        current = self._boosts.get(ticket_id, 0) + 1
        self._boosts[ticket_id] = current
        _log.info("RAG boost: ticket %s → boost_count=%s (multiplier=%.2f)",
                  ticket_id, current, 1 + self._BOOST_FACTOR * min(current, self._BOOST_CAP))
        return BoostResult(success=True, ticket_id=ticket_id,
                          boost_count=current,
                          message=f"Boosted to {current}")
