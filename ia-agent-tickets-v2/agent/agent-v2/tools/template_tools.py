"""
Template tools — predefined ticket templates for common requests.

Architecture:
  Nivel A: Predefined templates in PostgreSQL with keyword matching.
           Zero LLM tokens — pure SQL query + catalog resolution.
  Nivel B: Templates indexed in RAG for semantic matching (future).
  Nivel C: Template extraction from documents via LLM (future).

Templates are seeded at startup (via scheduler._ensure_tables) from
a hardcoded catalog and enriched with resolved IDs from the Odoo backend.
"""

from __future__ import annotations

import logging
from typing import Any

import psycopg
from langchain_core.tools import tool

from config.settings import settings

_log = logging.getLogger(__name__)

# ── Seed data (catalog names — IDs resolved at seed time) ──────────────────

TEMPLATE_SEED: list[dict[str, Any]] = [
    {
        "name": "Restablecer contraseña",
        "description": (
            "No puedo iniciar sesión en el sistema. "
            "Solicito restablecimiento de contraseña de mi cuenta."
        ),
        "ticket_type_name": "Incidencia",
        "category_name": "Soporte Técnico",
        "urgency_name": "Media",
        "impact_name": "Individual",
        "priority_name": "Media",
        "keywords": (
            "contraseña password login acceso credenciales "
            "restablecer bloqueo no puedo entrar olvidé"
        ),
    },
    {
        "name": "VPN caída",
        "description": (
            "No puedo conectarme a la VPN corporativa. "
            "Me aparece error de conexión al intentar acceder."
        ),
        "ticket_type_name": "Incidencia",
        "category_name": "Redes",
        "urgency_name": "Alta",
        "impact_name": "Alto",
        "priority_name": "Alta",
        "keywords": (
            "vpn conexión conectividad remoto forti "
            "pulse secure cualquier connect red privada túnel"
        ),
    },
    {
        "name": "Impresora sin servicio",
        "description": (
            "La impresora del piso no responde / no imprime. "
            "Solicito revisión técnica."
        ),
        "ticket_type_name": "Incidencia",
        "category_name": "Infraestructura",
        "urgency_name": "Media",
        "impact_name": "Departamental",
        "priority_name": "Media",
        "keywords": (
            "impresora imprimir toner papel atascada "
            "no imprime sin papel escaner fotocopiadora"
        ),
    },
    {
        "name": "Solicitud de software",
        "description": (
            "Necesito instalar un software adicional en mi equipo "
            "de trabajo para realizar mis funciones."
        ),
        "ticket_type_name": "Solicitud",
        "category_name": "Soporte Técnico",
        "urgency_name": "Baja",
        "impact_name": "Individual",
        "priority_name": "Baja",
        "keywords": (
            "instalar software aplicacion programa office "
            "adobe autocad chrome navegador herramienta"
        ),
    },
    {
        "name": "Equipo no enciende",
        "description": (
            "Mi computador no enciende / pantalla negra. "
            "Necesito revisión urgente para poder trabajar."
        ),
        "ticket_type_name": "Incidencia",
        "category_name": "Infraestructura",
        "urgency_name": "Urgente",
        "impact_name": "Alto",
        "priority_name": "Urgente",
        "keywords": (
            "no enciende pantalla computador pc hardware "
            "dañado roto falla azul pantalla azul"
        ),
    },
]

# ── Safety guard ──────────────────────────────────────────────────────────

def _safe_uid(llm_provided) -> int:
    """Forces the authenticated user_id from ContextVar (Capa 4 isolation)."""
    from core.context import current_user_id as _uid_var
    ctx = _uid_var.get()
    return ctx if ctx else int(llm_provided)

# ── Tables ────────────────────────────────────────────────────────────────

async def ensure_template_tables() -> None:
    """Creates the ticket_templates table if it doesn't exist."""
    if not settings.postgres_dsn:
        return
    try:
        async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ticket_templates (
                    id              SERIAL PRIMARY KEY,
                    name            TEXT NOT NULL,
                    description     TEXT DEFAULT '',
                    keywords        TEXT DEFAULT '',
                    ticket_type_id  INTEGER,
                    category_id     INTEGER,
                    urgency_id      INTEGER,
                    impact_id       INTEGER,
                    priority_id     INTEGER,
                    is_active       BOOLEAN DEFAULT TRUE,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.commit()
            _log.debug("ticket_templates table verified.")
    except Exception:
        _log.warning("Could not create ticket_templates table — templates disabled.")


async def seed_templates(ticket_port) -> int:
    """
    Seeds predefined templates into ticket_templates.
    Resolves catalog names → IDs using the active backend port.

    Idempotent: skips templates whose name already exists in the table.

    Returns:
        Number of new templates inserted.
    """
    if not settings.postgres_dsn:
        return 0

    try:
        # Resolve catalog IDs from the active backend
        types = await ticket_port.get_ticket_types() or []
        cats = await ticket_port.get_categories() or []
        urgencies = await ticket_port.get_urgency_levels() or []
        impacts = await ticket_port.get_impact_levels() or []
        priorities = await ticket_port.get_priority_levels() or []
    except Exception as exc:
        _log.warning("Could not fetch catalogs for template seeding: %s", exc)
        return 0

    # Build name → ID lookup tables
    def _id_map(items: list, key: str = "name") -> dict[str, int]:
        mapping: dict[str, int] = {}
        for item in items:
            name = item.get(key, "")
            if isinstance(name, str):
                mapping[name.lower()] = item["id"]
                # Also index by first word for partial matches
                first = name.split("/")[0].strip().lower()
                if first not in mapping:
                    mapping[first] = item["id"]
        return mapping

    type_map = _id_map(types)
    cat_map = _id_map(cats)
    urgency_map = _id_map(urgencies)
    impact_map = _id_map(impacts)
    priority_map = _id_map(priorities)

    inserted = 0
    async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
        for tmpl in TEMPLATE_SEED:
            # Check if already seeded
            exists = await conn.execute(
                "SELECT 1 FROM ticket_templates WHERE name = %s LIMIT 1",
                [tmpl["name"]],
            )
            if await exists.fetchone():
                continue

            # Resolve names → IDs (fallback to NULL if catalog not found)
            tid = type_map.get(tmpl["ticket_type_name"].lower())
            cid = cat_map.get(tmpl["category_name"].split("/")[0].strip().lower())
            uid = urgency_map.get(tmpl["urgency_name"].lower())
            iid = impact_map.get(tmpl["impact_name"].lower())
            pid = priority_map.get(tmpl["priority_name"].lower())

            await conn.execute(
                """
                INSERT INTO ticket_templates
                    (name, description, keywords,
                     ticket_type_id, category_id, urgency_id, impact_id, priority_id)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                [
                    tmpl["name"],
                    tmpl["description"],
                    tmpl["keywords"],
                    tid,
                    cid,
                    uid,
                    iid,
                    pid,
                ],
            )
            inserted += 1
            _log.debug("Seeded template: %s (type=%s, cat=%s)", tmpl["name"], tid, cid)

        if inserted:
            await conn.commit()
            _log.info("Seeded %d ticket template(s)", inserted)

    return inserted

# ── Tools ─────────────────────────────────────────────────────────────────

@tool
async def get_ticket_templates(query: str = "") -> str:
    """
    Lists available ticket templates for common issues.

    Use this when a creator describes a problem that matches a common pattern.
    Templates have pre-filled fields (type, category, urgency) so the user
    only needs to provide the specific details.

    Args:
        query: Optional keywords to filter templates (e.g. "vpn", "impresora").
               Leave empty to see all templates.

    Returns a list of matching templates with names and descriptions.
    """
    if not settings.postgres_dsn:
        return "SIN PLANTILLAS: El sistema de plantillas no está configurado."

    try:
        async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
            if query:
                # Keyword search: split into words and match against keywords column
                words = query.lower().split()
                conditions = " OR ".join(
                    ["keywords ILIKE %s" for _ in words]
                )
                params = [f"%{w}%" for w in words]
                cur = await conn.execute(
                    f"""
                    SELECT id, name, description, keywords
                    FROM ticket_templates
                    WHERE is_active = TRUE AND ({conditions})
                    ORDER BY name
                    LIMIT 5
                    """,
                    params,
                )
            else:
                cur = await conn.execute(
                    """
                    SELECT id, name, description, keywords
                    FROM ticket_templates
                    WHERE is_active = TRUE
                    ORDER BY name
                    LIMIT 10
                    """
                )

            rows = await cur.fetchall()

        if not rows:
            return (
                "SIN PLANTILLAS: No se encontraron plantillas que coincidan "
                "con la búsqueda. Procede a recopilar los datos del ticket "
                "manualmente y llama a create_ticket."
            )

        lines = ["PLANTILLAS DISPONIBLES:"]
        for row in rows:
            lines.append(
                f"  [{row[0]}] {row[1]} — {row[2][:100]}"
            )
        lines.append(
            "\nPara usar una plantilla, pregúntale al usuario si quiere "
            "usarla y luego llama a `use_ticket_template` con el ID. "
            "Si ninguna coincide, recopila los datos manualmente."
        )
        return "\n".join(lines)

    except Exception as exc:
        _log.error("get_ticket_templates failed: %s", exc)
        return (
            "ERROR: No se pudieron cargar las plantillas. "
            "Procede a recopilar los datos del ticket manualmente."
        )


@tool
async def use_ticket_template(template_id: int) -> str:
    """
    Returns the pre-filled fields of a ticket template.

    Use this AFTER the user confirms they want to use the template.
    The returned fields save the user time — they only need to provide
    the specific description of their issue.

    Args:
        template_id: The numeric ID of the template (from get_ticket_templates)

    Returns the template's pre-filled fields as structured text.
    """
    if not settings.postgres_dsn:
        return "ERROR: Sistema de plantillas no configurado."

    try:
        async with await psycopg.AsyncConnection.connect(settings.postgres_dsn) as conn:
            cur = await conn.execute(
                """
                SELECT id, name, description,
                       ticket_type_id, category_id, urgency_id,
                       impact_id, priority_id
                FROM ticket_templates
                WHERE id = %s AND is_active = TRUE
                """,
                [template_id],
            )
            row = await cur.fetchone()

        if not row:
            return (
                f"ERROR: Plantilla {template_id} no encontrada o inactiva. "
                f"Usa get_ticket_templates para ver las disponibles."
            )

        fields = {
            "template_id": row[0],
            "template_name": row[1],
            "description": row[2],
            "ticket_type_id": row[3],
            "category_id": row[4],
            "urgency_id": row[5],
            "impact_id": row[6],
            "priority_id": row[7],
        }

        lines = [
            f"PLANTILLA: {fields['template_name']}",
            f"  Descripción sugerida: {fields['description']}",
        ]
        if fields["ticket_type_id"]:
            lines.append(f"  Tipo de ticket: {fields['ticket_type_id']} (ya pre-seleccionado)")
        if fields["category_id"]:
            lines.append(f"  Categoría: {fields['category_id']} (ya pre-seleccionado)")
        if fields["urgency_id"]:
            lines.append(f"  Urgencia: {fields['urgency_id']} (ya pre-seleccionado)")
        if fields["impact_id"]:
            lines.append(f"  Impacto: {fields['impact_id']} (ya pre-seleccionado)")
        if fields["priority_id"]:
            lines.append(f"  Prioridad: {fields['priority_id']} (ya pre-seleccionado)")

        lines.append(
            "\nUsa estos campos YA PRE-SELECCIONADOS al llamar a create_ticket. "
            "Solo pregunta al usuario los datos que falten: "
            "equipo afectado, usuarios impactados, detalles específicos, AnyDesk."
        )

        return "\n".join(lines)

    except Exception as exc:
        _log.error("use_ticket_template failed: %s", exc)
        return f"ERROR al cargar la plantilla: {exc}"
