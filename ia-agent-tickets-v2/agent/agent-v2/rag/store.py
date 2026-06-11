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

import html
import re
import logging
from langchain_postgres import PGVector
from langchain_core.documents import Document

from ports.rag_port import IRAGPort, SuggestionResult, SolutionItem
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

    def __init__(self, postgres_dsn: str, enabled: bool = True):
        self._enabled = enabled
        self._store: PGVector | None = None

        if enabled:
            self._store = PGVector(
                embeddings=get_embeddings(),
                collection_name=self.COLLECTION_NAME,
                connection=_pg_dsn(postgres_dsn),
                use_jsonb=True,
                create_extension=True,
            )

    def search_similar(self, query: str, category: str = None,
                       k: int = 5) -> SuggestionResult:
        if not self._enabled or not self._store:
            return SuggestionResult(solutions_found=False)

        full_query = f"Problem: {query}"
        if category:
            full_query = f"Category: {category}. {full_query}"

        # ── Phase C.2 (UX-4): category-filtered search ────────────────────────
        # Build pgvector filter when category is provided AND non-empty.
        # Empty string is treated as "no filter" (some old docs have category="").
        # PGVector with use_jsonb=True generates: cmetadata->>'category' = $1
        # which is indexable on the JSONB column for fast pre-filtering.
        category_filter = None
        if category and category.strip():
            category_filter = {"category": category.strip()}

        results = self._search_with_filter(full_query, category_filter, k)

        # ── Fallback: if filter excluded everything, retry without filter ────
        # Why: the LLM may have misread the catalog and passed a category that
        # doesn't exist in the knowledge base. Better to return SOMETHING
        # semantically close than to fail with "no solutions found" when there
        # are clearly similar resolved tickets in other categories.
        if not results and category_filter is not None:
            _log.info(
                "RAG category filter '%s' returned no results — falling back to global search",
                category,
            )
            results = self._search_with_filter(full_query, None, k)

        if not results:
            return SuggestionResult(solutions_found=False)

        threshold = settings.rag_similarity_threshold
        solutions = []
        highest_score = 0.0

        for doc, score in results:
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

    def _search_with_filter(self, full_query: str,
                            category_filter: dict | None,
                            k: int) -> list:
        """
        Run a single similarity_search_with_relevance_scores call.

        Returns the raw (doc, score) tuples or empty list on failure.
        Centralised so the main search_similar() can do its
        "filter → fallback" pattern in two lines.
        """
        try:
            # similarity_search_with_relevance_scores returns (doc, score) where
            # score is in [0, 1] (higher = more similar). With COSINE strategy,
            # score = 1 - pgvector_cosine_distance.
            if category_filter is not None:
                return self._store.similarity_search_with_relevance_scores(
                    full_query, k=k, filter=category_filter,
                )
            return self._store.similarity_search_with_relevance_scores(
                full_query, k=k,
            )
        except Exception as exc:
            _log.warning("pgvector search failed: %s", exc)
            return []

    def add_resolved_ticket(self, ticket_id: int, ticket_name: str,
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
            self._store.add_documents([doc], ids=[f"ticket-{ticket_id}"])
        except Exception as exc:
            _log.warning("pgvector add_resolved_ticket failed: %s", exc)
            return False
        return True

    def initialize_from_resolved_tickets(self, tickets: list) -> int:
        if not self._enabled or not self._store:
            return 0

        if self.count() > 0:
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
                self._store.add_documents(documents, ids=ids)
            except Exception as exc:
                _log.warning("pgvector seed failed: %s", exc)
                return 0

        return len(documents)

    def count(self) -> int:
        """Returns document count via direct SQL. Only used for startup logging."""
        if not self._enabled or not self._store:
            return 0
        try:
            import psycopg
            with psycopg.connect(settings.postgres_dsn) as conn:
                row = conn.execute(
                    "SELECT COUNT(*) FROM langchain_pg_embedding e "
                    "JOIN langchain_pg_collection c ON e.collection_id = c.uuid "
                    "WHERE c.name = %s",
                    (self.COLLECTION_NAME,),
                ).fetchone()
            return row[0] if row else 0
        except Exception as exc:
            _log.debug("pgvector count failed: %s", exc)
            return 0

    # ── Delta sync (periodic background task) ─────────────────────────────────
    # These two methods are the RAG lifecycle hooks for production:
    #   1. cleanup_orphaned_documents() runs once at startup to purge the
    #      "noisy" docs that pre-date the category filter.
    #   2. sync_resolved_tickets(ticket_port) is called every
    #      ``settings.rag_sync_interval_hours`` to ingest newly-resolved
    #      tickets without re-indexing the entire history.

    def _indexed_ticket_ids(self) -> set[int]:
        """Return the set of ticket_id values already embedded in pgvector."""
        if not self._enabled or not self._store:
            return set()
        try:
            import psycopg
            with psycopg.connect(settings.postgres_dsn) as conn:
                rows = conn.execute(
                    "SELECT (e.cmetadata->>'ticket_id')::int "
                    "FROM langchain_pg_embedding e "
                    "JOIN langchain_pg_collection c ON e.collection_id = c.uuid "
                    "WHERE c.name = %s "
                    "AND e.cmetadata ? 'ticket_id'",
                    (self.COLLECTION_NAME,),
                ).fetchall()
            return {r[0] for r in rows if r[0] is not None}
        except Exception as exc:
            _log.warning("pgvector indexed_ticket_ids failed: %s", exc)
            return set()

    async def sync_resolved_tickets(self, ticket_port) -> dict:
        """
        Pull resolved tickets from ``ticket_port`` and add the ones not yet
        indexed. Idempotent: tickets already in pgvector (by ``ticket_id``)
        are skipped, so calling this every N hours does not duplicate work.

        Args:
            ticket_port: An object exposing ``get_resolved_tickets()`` (async
                since Fase 8 — the orchestrator awaits the call).

        Returns:
            dict with ``{"added": N, "skipped": M, "errors": K}`` for logging.
        """
        if not self._enabled or not self._store:
            return {"added": 0, "skipped": 0, "errors": 0, "disabled": True}

        added = 0
        skipped = 0
        errors = 0

        try:
            # ticket_port.get_resolved_tickets is async (Fase 8)
            resolved = await ticket_port.get_resolved_tickets()
        except Exception as exc:
            _log.warning("rag_sync_fetch_failed: %s", exc)
            return {"added": 0, "skipped": 0, "errors": 1}

        # Build the set of IDs already in pgvector once (cheap SQL query)
        indexed = self._indexed_ticket_ids()

        for ticket in (resolved or []):
            ticket_id = ticket.get("ticket_id", 0)
            if not ticket_id:
                continue
            if int(ticket_id) in indexed:
                skipped += 1
                continue

            # Skip tickets with empty category — they would be deleted by
            # cleanup_orphaned_documents() anyway, so adding them would
            # create a sync ↔ cleanup loop that wastes embedding compute.
            raw_category = ticket.get("category", "") or ticket.get("categoria", "")
            if not raw_category or not str(raw_category).strip():
                skipped += 1
                continue

            try:
                ok = self.add_resolved_ticket(
                    ticket_id=ticket_id,
                    ticket_name=ticket.get("ticket_name", ""),
                    ticket_type=ticket.get("ticket_type", "") or ticket.get("tipo_requerimiento", ""),
                    category=ticket.get("category", "") or ticket.get("categoria", ""),
                    description=ticket.get("description", "") or ticket.get("descripcion", ""),
                    motivo_resolucion=ticket.get("motivo_resolucion", "") or ticket.get("resolucion", ""),
                    causa_raiz=ticket.get("causa_raiz", ""),
                )
                if ok:
                    added += 1
                    # Track in our local set so duplicates within this
                    # same batch are not double-counted.
                    indexed.add(int(ticket_id))
                else:
                    errors += 1
            except Exception as exc:
                _log.warning(
                    "rag_sync_add_failed",
                    extra={"ticket_id": ticket_id, "error": str(exc)},
                )
                errors += 1

        result = {"added": added, "skipped": skipped, "errors": errors}
        if added > 0 or errors > 0:
            _log.info("rag_sync_done", extra=result)
        return result

    def cleanup_orphaned_documents(self) -> int:
        """
        Delete pgvector rows with empty / null / missing ``category`` metadata.

        These documents pre-date the category-filter feature (UX-4) and
        contaminate global searches. Safe to call repeatedly — it is a
        pure DELETE with no side effects on valid documents.

        Returns:
            Number of documents deleted.
        """
        if not self._enabled or not self._store:
            return 0
        try:
            import psycopg
            with psycopg.connect(settings.postgres_dsn) as conn:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        DELETE FROM langchain_pg_embedding e
                        USING langchain_pg_collection c
                        WHERE e.collection_id = c.uuid
                          AND c.name = %s
                          AND (
                            NOT (e.cmetadata ? 'category')
                            OR e.cmetadata->>'category' IS NULL
                            OR TRIM(e.cmetadata->>'category') = ''
                          )
                        """,
                        (self.COLLECTION_NAME,),
                    )
                    deleted = cur.rowcount
                conn.commit()
            if deleted:
                _log.info("rag_cleanup_done", extra={"deleted": deleted})
            return deleted
        except Exception as exc:
            _log.warning("pgvector cleanup failed: %s", exc)
            return 0
