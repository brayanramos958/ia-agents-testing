"""
Tests para calidad del RAG — TDD: estos tests deben FALLAR antes del fix
y PASAR después.

Bug-C: add_resolved_ticket e initialize_from_resolved_tickets no limpian HTML
       de los campos que vienen de Odoo fields.Html (motivo_resolucion,
       causa_raiz, descripcion). Los tags contaminan los embeddings.

Bug-E: search_similar() ignora rag_similarity_threshold — devuelve resultados
       con score muy bajo que confunden al agente.

Bug-F: Sin deduplicación — resolver el mismo ticket dos veces crea dos
       documentos en ChromaDB.

Ejecutar desde agent-v2/:
    .venv/bin/python3 scratch/test_rag_quality.py
"""

import sys
import os
import re

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unittest.mock import MagicMock, patch, call

PASS = "  PASS"
FAIL = "  FAIL"
results = []


def ok(name):
    results.append((True, name))
    print(f"{PASS}  {name}")


def fail(name, reason):
    results.append((False, name))
    print(f"{FAIL}  {name}")
    print(f"        → {reason}")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_store():
    """
    Crea un ChromaRAGStore con enabled=False y luego activa _enabled=True
    manualmente + inyecta un _store mockeado.
    Evita necesidad de ChromaDB y modelo de embeddings real en los tests.
    """
    from rag.store import ChromaRAGStore
    store = ChromaRAGStore.__new__(ChromaRAGStore)
    store._enabled = True
    store._persist_path = "/tmp/test_rag"
    mock_chroma = MagicMock()
    mock_chroma._collection.count.return_value = 0
    store._store = mock_chroma
    return store, mock_chroma


def _get_added_document_text(mock_chroma) -> str:
    """Extrae el page_content del documento pasado a add_documents()."""
    calls = mock_chroma.add_documents.call_args_list
    if not calls:
        return ""
    docs = calls[0][0][0]  # primer call, primer arg posicional, lista de docs
    return docs[0].page_content


def _get_added_metadata(mock_chroma) -> dict:
    """Extrae el metadata del documento pasado a add_documents()."""
    calls = mock_chroma.add_documents.call_args_list
    if not calls:
        return {}
    docs = calls[0][0][0]
    return docs[0].metadata


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 1 — Bug-C: _strip_html helper
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 1: Bug-C — _strip_html helper ─────────────────────────────")


def test_strip_html_removes_p_tags():
    """
    _strip_html debe eliminar <p>...</p> dejando el texto limpio.
    FALLA antes del fix: _strip_html no existe.
    PASA después del fix: función importable y funciona.
    """
    try:
        from rag.store import _strip_html
        result = _strip_html("<p>Se reemplazó el mouse</p>")
        if "<p>" not in result and "Se reemplazó el mouse" in result:
            ok("_strip_html: elimina tags <p>")
        else:
            fail("_strip_html: elimina tags <p>", f"Resultado: {result!r}")
    except ImportError as e:
        fail("_strip_html: elimina tags <p>", f"_strip_html no existe en rag.store: {e}")


def test_strip_html_removes_br_tags():
    """_strip_html debe eliminar <br/> y <br> y reemplazar con espacio."""
    try:
        from rag.store import _strip_html
        result = _strip_html("Línea 1<br/>Línea 2")
        if "<br" not in result and "Línea 1" in result and "Línea 2" in result:
            ok("_strip_html: elimina <br/>")
        else:
            fail("_strip_html: elimina <br/>", f"Resultado: {result!r}")
    except ImportError as e:
        fail("_strip_html: elimina <br/>", f"_strip_html no existe: {e}")


def test_strip_html_decodes_entities():
    """
    _strip_html debe decodificar HTML entities antes de limpiar.
    &amp; → &, &lt; → <, &gt; → >, &#39; → '
    """
    try:
        from rag.store import _strip_html
        result = _strip_html("El usuario&#39;s mouse &amp; teclado")
        if "&amp;" not in result and "&#39;" not in result and "mouse" in result:
            ok("_strip_html: decodifica HTML entities (&amp;, &#39;, etc.)")
        else:
            fail("_strip_html: decodifica HTML entities", f"Resultado: {result!r}")
    except ImportError as e:
        fail("_strip_html: decodifica HTML entities", f"_strip_html no existe: {e}")


def test_strip_html_handles_empty_string():
    """_strip_html con string vacío o None debe retornar string vacío sin crash."""
    try:
        from rag.store import _strip_html
        r1 = _strip_html("")
        r2 = _strip_html(None)
        if r1 == "" and r2 == "":
            ok("_strip_html: maneja string vacío y None sin crash")
        else:
            fail("_strip_html: maneja empty/None", f"r1={r1!r}, r2={r2!r}")
    except ImportError as e:
        fail("_strip_html: maneja empty/None", f"_strip_html no existe: {e}")
    except Exception as exc:
        fail("_strip_html: maneja empty/None", f"Excepción: {exc}")


def test_strip_html_complex_odoo_html():
    """
    Simula el HTML real que devuelve Odoo para fields.Html.
    Texto anidado con <p>, <br/>, <strong>, &amp; debe quedar limpio.
    """
    try:
        from rag.store import _strip_html
        odoo_html = "<p>Se <strong>reemplazó</strong> el mouse.<br/>Equipo: HP &amp; Lenovo.</p>"
        result = _strip_html(odoo_html)
        has_tags = bool(re.search(r'<[^>]+>', result))
        has_entity = "&amp;" in result or "&#" in result
        has_content = "reemplazó" in result and "HP" in result and "Lenovo" in result
        if not has_tags and not has_entity and has_content:
            ok("_strip_html: HTML complejo de Odoo queda completamente limpio")
        else:
            fail(
                "_strip_html: HTML complejo de Odoo",
                f"Tags: {has_tags}, Entities: {has_entity}, Content: {has_content}. "
                f"Resultado: {result!r}"
            )
    except ImportError as e:
        fail("_strip_html: HTML complejo de Odoo", f"_strip_html no existe: {e}")


test_strip_html_removes_p_tags()
test_strip_html_removes_br_tags()
test_strip_html_decodes_entities()
test_strip_html_handles_empty_string()
test_strip_html_complex_odoo_html()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 2 — Bug-C: add_resolved_ticket limpia HTML antes de embeber
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 2: Bug-C — add_resolved_ticket strip HTML ─────────────────")

HTML_DESCRIPTION   = "<p>El mouse <strong>no funciona</strong> correctamente.</p>"
HTML_RESOLUCION    = "<p>Se <em>reemplazó</em> el mouse.<br/>Funcionando.</p>"
HTML_CAUSA_RAIZ    = "<p>Cable interno <strong>fracturado</strong> por uso.</p>"
CLEAN_DESCRIPTION  = "El mouse no funciona correctamente."
CLEAN_RESOLUCION   = "Se reemplazó el mouse. Funcionando."
CLEAN_CAUSA_RAIZ   = "Cable interno fracturado por uso."


def test_add_resolved_ticket_strips_html_from_document_text():
    """
    add_resolved_ticket debe limpiar HTML de description, motivo_resolucion
    y causa_raiz ANTES de construir document_text (lo que se embebe).

    FALLA antes del fix: document_text contiene <p>, <strong>, etc.
    PASA después del fix: document_text no contiene ningún tag HTML.
    """
    store, mock_chroma = _make_store()
    store.add_resolved_ticket(
        ticket_id=1,
        ticket_name="TCK-0001",
        ticket_type="Incidente",
        category="Hardware",
        description=HTML_DESCRIPTION,
        motivo_resolucion=HTML_RESOLUCION,
        causa_raiz=HTML_CAUSA_RAIZ,
    )

    doc_text = _get_added_document_text(mock_chroma)

    has_tags = bool(re.search(r'<[^>]+>', doc_text))
    has_content = "mouse" in doc_text and "reemplazó" in doc_text

    if not has_tags and has_content:
        ok("add_resolved_ticket: document_text no contiene HTML tags")
    else:
        fail(
            "add_resolved_ticket: document_text no contiene HTML tags",
            f"Tags presentes: {has_tags}, Contenido OK: {has_content}. "
            f"Text: {doc_text[:150]!r}"
        )


def test_add_resolved_ticket_stores_clean_text_in_metadata():
    """
    Los campos en metadata también deben guardarse SIN HTML para que el
    agente pueda leerlos directamente en las sugerencias.

    FALLA antes del fix: metadata contiene HTML crudo de Odoo.
    PASA después del fix: metadata.description, .motivo_resolucion, .causa_raiz son texto limpio.
    """
    store, mock_chroma = _make_store()
    store.add_resolved_ticket(
        ticket_id=2,
        ticket_name="TCK-0002",
        ticket_type="Incidente",
        category="Hardware",
        description=HTML_DESCRIPTION,
        motivo_resolucion=HTML_RESOLUCION,
        causa_raiz=HTML_CAUSA_RAIZ,
    )

    meta = _get_added_metadata(mock_chroma)

    desc_clean  = not bool(re.search(r'<[^>]+>', meta.get("description", "")))
    motivo_clean = not bool(re.search(r'<[^>]+>', meta.get("motivo_resolucion", "")))
    causa_clean = not bool(re.search(r'<[^>]+>', meta.get("causa_raiz", "")))

    if desc_clean and motivo_clean and causa_clean:
        ok("add_resolved_ticket: metadata almacena texto limpio (sin HTML)")
    else:
        fail(
            "add_resolved_ticket: metadata sin HTML",
            f"desc_clean={desc_clean}, motivo_clean={motivo_clean}, causa_clean={causa_clean}. "
            f"description={meta.get('description','')[:60]!r}"
        )


test_add_resolved_ticket_strips_html_from_document_text()
test_add_resolved_ticket_stores_clean_text_in_metadata()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 3 — Bug-C: initialize_from_resolved_tickets limpia HTML
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 3: Bug-C — initialize_from_resolved_tickets strip HTML ─────")


def test_initialize_strips_html_from_seeded_documents():
    """
    initialize_from_resolved_tickets también debe limpiar HTML al sembrar
    el vector store desde Odoo al inicio.

    FALLA antes del fix: document_text del seed contiene HTML.
    PASA después del fix: todos los page_content son texto limpio.
    """
    store, mock_chroma = _make_store()

    tickets = [
        {
            "ticket_id": 10,
            "ticket_name": "TCK-0010",
            "ticket_type": "Incidente",
            "category": "Software",
            "description": "<p>Error al abrir <strong>Excel</strong>.</p>",
            "motivo_resolucion": "<p>Se reinstalo Office.<br/>Resuelto.</p>",
            "causa_raiz": "<p>Licencia <em>vencida</em>.</p>",
        },
        {
            "ticket_id": 11,
            "ticket_name": "TCK-0011",
            "ticket_type": "Solicitud",
            "category": "Hardware",
            "description": "<p>Mouse &amp; teclado dañados.</p>",
            "motivo_resolucion": "<p>Equipos reemplazados.</p>",
            "causa_raiz": "",
        },
    ]

    store.initialize_from_resolved_tickets(tickets)

    calls = mock_chroma.add_documents.call_args_list
    if not calls:
        fail("initialize_from_resolved_tickets: strip HTML", "add_documents no fue llamado")
        return

    docs = calls[0][0][0]  # lista de Document
    any_has_tags = any(bool(re.search(r'<[^>]+>', d.page_content)) for d in docs)
    any_has_entity = any("&amp;" in d.page_content for d in docs)

    if not any_has_tags and not any_has_entity:
        ok("initialize_from_resolved_tickets: todos los documentos sin HTML")
    else:
        bad = [d.page_content[:100] for d in docs if re.search(r'<[^>]+>', d.page_content)]
        fail(
            "initialize_from_resolved_tickets: documentos sin HTML",
            f"Documentos con HTML: {bad}"
        )


test_initialize_strips_html_from_seeded_documents()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 4 — Bug-E: search_similar aplica rag_similarity_threshold
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 4: Bug-E — search_similar aplica threshold ────────────────")

from langchain_core.documents import Document as LCDocument


def _make_chroma_results(*score_pairs):
    """Genera lista de (Document, score) para mockear similarity_search."""
    return [
        (LCDocument(page_content=f"doc_{i}", metadata={
            "ticket_id": i, "ticket_name": f"TCK-{i:04d}",
            "ticket_type": "Incidente", "category": "Hardware",
            "description": f"desc {i}", "motivo_resolucion": f"resolucion {i}",
            "causa_raiz": "",
        }), score)
        for i, score in enumerate(score_pairs)
    ]


def test_search_similar_filters_below_threshold():
    """
    Si todos los resultados tienen score < rag_similarity_threshold (0.6),
    search_similar debe retornar solutions_found=False con lista vacía.

    FALLA antes del fix: devuelve todos los resultados sin filtrar.
    PASA después del fix: aplica el threshold y retorna vacío.
    """
    store, mock_chroma = _make_store()
    mock_chroma.similarity_search_with_relevance_scores.return_value = \
        _make_chroma_results(0.3, 0.45, 0.55)  # todos bajo 0.6

    result = store.search_similar("mouse no funciona", category="Hardware")

    if not result.solutions_found and len(result.solutions) == 0:
        ok("search_similar: retorna vacío cuando todos los scores < threshold (0.6)")
    else:
        fail(
            "search_similar: filtra por threshold",
            f"solutions_found={result.solutions_found}, "
            f"solutions count={len(result.solutions)}, "
            f"scores={[s.score for s in result.solutions]}"
        )


def test_search_similar_keeps_results_above_threshold():
    """
    Resultados con score >= threshold deben aparecer; los que están abajo, no.
    FALLA antes del fix: devuelve todos incluyendo los de score bajo.
    PASA después del fix: solo devuelve los que superan el threshold.
    """
    store, mock_chroma = _make_store()
    # score 0.8 y 0.7 → pasan; 0.4 → no pasa
    mock_chroma.similarity_search_with_relevance_scores.return_value = \
        _make_chroma_results(0.8, 0.4, 0.7)

    result = store.search_similar("mouse no funciona")

    scores_returned = [s.score for s in result.solutions]
    all_above = all(s >= 0.6 for s in scores_returned)
    low_excluded = 0.4 not in scores_returned

    if result.solutions_found and len(result.solutions) == 2 and all_above and low_excluded:
        ok("search_similar: mantiene scores >= 0.6, excluye scores < 0.6")
    else:
        fail(
            "search_similar: filtra correctamente por threshold",
            f"solutions_found={result.solutions_found}, "
            f"scores devueltos: {scores_returned} (esperados: [0.8, 0.7])"
        )


def test_search_similar_all_above_threshold():
    """
    Si todos los resultados superan el threshold, se devuelven todos.
    Este test debe PASAR antes y después del fix (verifica no-regresión).
    """
    store, mock_chroma = _make_store()
    mock_chroma.similarity_search_with_relevance_scores.return_value = \
        _make_chroma_results(0.9, 0.75, 0.65)

    result = store.search_similar("mouse no funciona")

    if result.solutions_found and len(result.solutions) == 3:
        ok("search_similar: retorna todos cuando todos superan threshold")
    else:
        fail(
            "search_similar: retorna todos sobre threshold",
            f"solutions_found={result.solutions_found}, count={len(result.solutions)}"
        )


test_search_similar_filters_below_threshold()
test_search_similar_keeps_results_above_threshold()
test_search_similar_all_above_threshold()


# ─────────────────────────────────────────────────────────────────────────────
# GRUPO 5 — Bug-F: Deduplicación en add_resolved_ticket
# ─────────────────────────────────────────────────────────────────────────────

print("\n── Grupo 5: Bug-F — Deduplicación por ticket_id ────────────────────")


def test_add_resolved_ticket_deduplication_updates_existing():
    """
    Si ticket_id ya existe en ChromaDB, add_resolved_ticket NO debe crear
    un segundo documento — debe reemplazar el existente.

    FALLA antes del fix: siempre llama add_documents sin verificar duplicados.
    PASA después del fix: detecta el duplicado y hace upsert en lugar de insert.
    """
    store, mock_chroma = _make_store()

    # Simular que ticket_id=5 ya existe en ChromaDB
    existing_id = "chroma-doc-abc123"
    mock_chroma.get.return_value = {
        "ids": [existing_id],
        "documents": ["old document text"],
        "metadatas": [{"ticket_id": 5}],
    }

    store.add_resolved_ticket(
        ticket_id=5,
        ticket_name="TCK-0005",
        ticket_type="Incidente",
        category="Hardware",
        description="El mouse no funciona",
        motivo_resolucion="Se reemplazó",
        causa_raiz="Cable roto",
    )

    # Después del fix: debe haberse llamado delete() o update_document() en lugar
    # de solo add_documents()
    delete_called = mock_chroma.delete.called
    update_called = mock_chroma.update_document.called or mock_chroma.update_documents.called
    add_called = mock_chroma.add_documents.called

    if delete_called or update_called:
        ok("add_resolved_ticket: detecta duplicado y actualiza (no inserta segundo doc)")
    else:
        fail(
            "add_resolved_ticket: deduplicación",
            f"delete_called={delete_called}, update_called={update_called}, "
            f"add_called={add_called} — se insertó sin verificar duplicado"
        )


def test_add_resolved_ticket_no_duplicate_when_no_existing():
    """
    Si ticket_id NO existe, add_resolved_ticket debe insertar normalmente.
    Verifica que la deduplicación no rompa el flujo normal.
    """
    store, mock_chroma = _make_store()

    # Simular que NO existe el ticket
    mock_chroma.get.return_value = {"ids": [], "documents": [], "metadatas": []}

    store.add_resolved_ticket(
        ticket_id=99,
        ticket_name="TCK-0099",
        ticket_type="Solicitud",
        category="Software",
        description="No puedo acceder a SAP",
        motivo_resolucion="Se restauraron los permisos",
        causa_raiz="Política de seguridad aplicada",
    )

    if mock_chroma.add_documents.called:
        ok("add_resolved_ticket: inserta normalmente cuando no existe duplicado")
    else:
        fail(
            "add_resolved_ticket: inserta cuando no hay duplicado",
            "add_documents no fue llamado — la deduplicación bloqueó el insert correcto"
        )


test_add_resolved_ticket_deduplication_updates_existing()
test_add_resolved_ticket_no_duplicate_when_no_existing()


# ─────────────────────────────────────────────────────────────────────────────
# Resumen final
# ─────────────────────────────────────────────────────────────────────────────

print("\n" + "─" * 60)
passed = sum(1 for ok_, _ in results if ok_)
failed = sum(1 for ok_, _ in results if not ok_)
total = len(results)
print(f"  Resultado: {passed}/{total} pasaron  |  {failed} fallaron")
if failed == 0:
    print("  ✓ Todos los bugs RAG fueron corregidos — tests pasan.")
else:
    print(f"  ✗ {failed} tests fallan — bugs RAG aún existen.")
print("─" * 60)

sys.exit(0 if failed == 0 else 1)
