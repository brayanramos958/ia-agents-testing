"""
Express backend adapter — DEV ONLY.

Maps the simplified Express/SQLite schema to ITicketPort.
Translates between Odoo-style FK IDs (used by the agent) and
string enums (used by the Express backend).

DO NOT use this adapter in production.
For production, use HttpAdapter configured for the Odoo REST API.

ARCHITECTURE NOTE (Fase 8 — async migration):
    All methods are ``async def`` and use a shared ``httpx.AsyncClient`` with
    a connection pool. The client is created in ``__init__`` and must be
    closed via ``await adapter.close()`` on shutdown.
"""

import httpx

from config.settings import settings
from ports.ticket_port import ITicketPort


# ── Catalog data for dev environment ─────────────────────────────────────────
# These catalogs mirror what the real Odoo system returns but are
# hardcoded for local development against the Express backend.

DEV_TICKET_TYPES = [
    {"id": 1, "name": "Incidente"},
    {"id": 2, "name": "Solicitud"},
    {"id": 3, "name": "Problema"},
]

DEV_CATEGORIES = [
    {"id": 1, "name": "Hardware",   "full_name": "Hardware",   "level": 1, "parent_id": None},
    {"id": 2, "name": "Software",   "full_name": "Software",   "level": 1, "parent_id": None},
    {"id": 3, "name": "Red",        "full_name": "Red",        "level": 1, "parent_id": None},
    {"id": 4, "name": "Seguridad",  "full_name": "Seguridad",  "level": 1, "parent_id": None},
    {"id": 5, "name": "Otro",       "full_name": "Otro",       "level": 1, "parent_id": None},
    # L2 examples under Hardware
    {"id": 10, "name": "Impresoras",   "full_name": "Hardware / Impresoras",   "level": 2, "parent_id": 1},
    {"id": 11, "name": "Computadoras", "full_name": "Hardware / Computadoras", "level": 2, "parent_id": 1},
    {"id": 12, "name": "Periféricos",  "full_name": "Hardware / Periféricos",  "level": 2, "parent_id": 1},
    # L2 examples under Software
    {"id": 20, "name": "Sistemas Operativos", "full_name": "Software / Sistemas Operativos", "level": 2, "parent_id": 2},
    {"id": 21, "name": "Aplicaciones",        "full_name": "Software / Aplicaciones",        "level": 2, "parent_id": 2},
    # L3 examples
    {"id": 100, "name": "Tóner",      "full_name": "Hardware / Impresoras / Tóner",      "level": 3, "parent_id": 10},
    {"id": 101, "name": "Atasco",     "full_name": "Hardware / Impresoras / Atasco",     "level": 3, "parent_id": 10},
    {"id": 102, "name": "Pantalla",   "full_name": "Hardware / Computadoras / Pantalla", "level": 3, "parent_id": 11},
    {"id": 103, "name": "Batería",    "full_name": "Hardware / Computadoras / Batería",  "level": 3, "parent_id": 11},
]

DEV_URGENCY = [
    {"id": 1, "name": "baja"},
    {"id": 2, "name": "media"},
    {"id": 3, "name": "alta"},
    {"id": 4, "name": "critica"},
]

DEV_IMPACT = [
    {"id": 1, "name": "bajo"},
    {"id": 2, "name": "medio"},
    {"id": 3, "name": "alto"},
]

DEV_PRIORITY = [
    {"id": 1, "name": "baja"},
    {"id": 2, "name": "media"},
    {"id": 3, "name": "alta"},
    {"id": 4, "name": "urgente"},
]

DEV_STAGES = [
    {"id": 1, "name": "Abierto",  "is_start": True,  "is_resolve": False, "is_close": False, "is_pause": False},
    {"id": 2, "name": "Asignado", "is_start": False, "is_resolve": False, "is_close": False, "is_pause": False},
    {"id": 3, "name": "Resuelto", "is_start": False, "is_resolve": True,  "is_close": False, "is_pause": False},
    {"id": 4, "name": "Cerrado",  "is_start": False, "is_resolve": False, "is_close": True,  "is_pause": False},
]

# ID → name lookup maps (for translating IDs to strings before sending to Express)
_TYPE_MAP = {t["id"]: t["name"] for t in DEV_TICKET_TYPES}
_CAT_MAP = {c["id"]: c["name"] for c in DEV_CATEGORIES}
_URGENCY_MAP = {u["id"]: u["name"] for u in DEV_URGENCY}
_IMPACT_MAP = {i["id"]: i["name"] for i in DEV_IMPACT}
_PRIORITY_MAP = {p["id"]: p["name"] for p in DEV_PRIORITY}


class ExpressAdapter(ITicketPort):
    """
    Connects to the local Express + SQLite dev backend.

    Translates Odoo-style IDs ↔ Express string enums internally.
    """

    def __init__(self, base_url: str) -> None:
        self._base_url: str = base_url.rstrip("/")
        self._client: httpx.AsyncClient = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            limits=httpx.Limits(
                max_connections=settings.httpx_max_connections,
                max_keepalive_connections=settings.httpx_max_keepalive,
            ),
            follow_redirects=True,
        )

    async def close(self) -> None:
        """Close the httpx.AsyncClient and release all connections."""
        await self._client.aclose()

    @staticmethod
    def _headers(user_id: int, user_rol: str) -> dict:
        """Build auth/role headers for Express dev backend."""
        return {
            "x-user-id": str(user_id),
            "x-user-rol": user_rol,
        }

    async def _get(self, path: str, params: dict | None = None) -> dict | list:
        """GET request helper."""
        try:
            response = await self._client.get(f"{self._base_url}{path}", params=params)
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Express GET {path} failed: {exc}") from exc

    async def _post(self, path: str, body: dict, user_id: int, user_rol: str) -> dict:
        """POST request helper."""
        try:
            response = await self._client.post(
                f"{self._base_url}{path}",
                json=body,
                headers=self._headers(user_id, user_rol),
            )
            return response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Express POST {path} failed: {exc}") from exc

    async def _put(self, path: str, body: dict, user_id: int, user_rol: str) -> dict:
        """PUT request helper."""
        try:
            response = await self._client.put(
                f"{self._base_url}{path}",
                json=body,
                headers=self._headers(user_id, user_rol),
            )
            return response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Express PUT {path} failed: {exc}") from exc

    # ── Ticket operations ────────────────────────────────────────────────────

    async def create_ticket(self, payload: dict, user_id: int) -> dict:
        """
        Create a ticket via the Express dev backend.

        Translates Odoo FK IDs to Express string values before sending.

        Args:
            payload: Ticket data (Odoo-style field names).
            user_id: Creator's user ID.

        Returns:
            dict: ``{"success": True, "ticket_name": str, "ticket_id": int}`` or
                  ``{"success": False, "error": str}``.
        """
        # Translate Odoo FK IDs to Express string values
        express_body = {
            "tipo_requerimiento": _TYPE_MAP.get(payload.get("ticket_type_id"), "Incidente"),
            "categoria": _CAT_MAP.get(payload.get("category_id"), "Otro"),
            "descripcion": payload.get("descripcion", ""),
            "urgencia": _URGENCY_MAP.get(payload.get("urgency_id"), "media"),
            "impacto": _IMPACT_MAP.get(payload.get("impact_id"), "medio"),
            "prioridad": _PRIORITY_MAP.get(payload.get("priority_id"), "media"),
            "created_by": user_id,
        }
        # Use asunto as descripcion if provided (Express uses descripcion as title)
        if payload.get("asunto"):
            express_body["descripcion"] = payload["asunto"]
            if payload.get("descripcion"):
                express_body["descripcion"] += f"\n\n{payload['descripcion']}"

        result = await self._post("/api/tickets", express_body, user_id, "creador")
        if result.get("id"):
            return {
                "success": True,
                "ticket_name": f"TCK-{result['id']:04d}",
                "ticket_id": result["id"],
            }
        return {"success": False, "error": result.get("error", "Unknown error")}

    async def get_tickets_by_creator(self, user_id: int) -> list:
        """Return all tickets created by the given user."""
        return await self._get("/api/tickets", {"created_by": user_id})

    async def get_tickets_by_assignee(self, user_id: int) -> list:
        """Return all tickets assigned to the given user."""
        return await self._get("/api/tickets", {"asignado_a": user_id})

    async def get_ticket_detail(self, ticket_id: int, user_id: int, role: str) -> dict:
        """Return full ticket details."""
        return await self._get(f"/api/tickets/{ticket_id}")

    async def resolve_ticket(
        self,
        ticket_id: int,
        motivo_resolucion: str,
        causa_raiz: str,
        user_id: int,
    ) -> dict:
        """
        Resolve a ticket via the Express dev backend.

        Express uses ``"resolucion"``; we store the full text combining both fields.

        Args:
            ticket_id: Ticket ID.
            motivo_resolucion: Resolution text.
            causa_raiz: Root cause analysis text.
            user_id: Resolver's user ID.

        Returns:
            dict: Express response.
        """
        resolution_text = motivo_resolucion
        if causa_raiz:
            resolution_text += f"\n\nRoot cause: {causa_raiz}"
        return await self._put(
            f"/api/tickets/{ticket_id}/resolve",
            {"resolucion": resolution_text},
            user_id,
            "resueltor",
        )

    async def update_ticket(self, ticket_id: int, fields: dict, user_id: int) -> dict:
        """Update arbitrary ticket fields."""
        return await self._put(f"/api/tickets/{ticket_id}", fields, user_id, "creador")

    async def get_all_tickets(self, filters: dict | None = None) -> list:
        """Return all tickets, optionally filtered."""
        return await self._get("/api/tickets", filters or {})

    async def assign_ticket(
        self,
        ticket_id: int,
        assignee_id: int,
        agent_group_id: int,
        user_id: int,
    ) -> dict:
        """Assign a ticket to an agent."""
        return await self._put(
            f"/api/tickets/{ticket_id}/assign",
            {"asignado_a": assignee_id},
            user_id,
            "supervisor",
        )

    async def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """Reopen a resolved/closed ticket."""
        return await self._put(
            f"/api/tickets/{ticket_id}/reopen",
            {"motivo": reason},
            user_id,
            "supervisor",
        )

    async def approve_ticket(self, ticket_id: int, user_id: int) -> dict:
        """Approve a pending ticket."""
        return await self._put(
            f"/api/tickets/{ticket_id}",
            {"approval_status": "approved"},
            user_id,
            "supervisor",
        )

    async def reject_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """Reject a pending ticket."""
        return await self._put(
            f"/api/tickets/{ticket_id}",
            {"approval_status": "rejected", "rejection_reason": reason},
            user_id,
            "supervisor",
        )

    async def delete_ticket(self, ticket_id: int, user_id: int) -> dict:
        """
        Permanently delete a ticket.

        SECURITY: Implemented but ``delete_ticket`` tool is excluded from all
        role tool lists.
        """
        try:
            response = await self._client.delete(
                f"{self._base_url}/api/tickets/{ticket_id}",
                headers=self._headers(user_id, "supervisor"),
            )
            return response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Express DELETE /api/tickets/{ticket_id} failed: {exc}") from exc

    # ── Catalog queries ──────────────────────────────────────────────────────
    # Return hardcoded dev catalogs. HttpAdapter will fetch these from Odoo API.

    async def get_resolvers(self) -> list:
        """Return users with the resolver role."""
        return await self._get("/api/users", {"rol": "resueltor"})

    async def get_agent_groups(self) -> list:
        """Return hardcoded agent groups."""
        return [{"id": 1, "name": "Soporte N1"}, {"id": 2, "name": "Soporte N2"}]

    async def get_ticket_types(self) -> list:
        """Return hardcoded ticket types."""
        return DEV_TICKET_TYPES

    async def get_categories(self, parent_id: int | None = None) -> list:
        """Return hardcoded categories filtered by parent_id."""
        return [c for c in DEV_CATEGORIES if c["parent_id"] == parent_id]

    async def get_urgency_levels(self) -> list:
        """Return hardcoded urgency levels."""
        return DEV_URGENCY

    async def get_impact_levels(self) -> list:
        """Return hardcoded impact levels."""
        return DEV_IMPACT

    async def get_priority_levels(self) -> list:
        """Return hardcoded priority levels."""
        return DEV_PRIORITY

    async def get_stages(self) -> list:
        """Return hardcoded workflow stages."""
        return DEV_STAGES

    async def get_resolved_tickets(self) -> list:
        """Return resolved tickets for RAG seeding."""
        tickets = await self._get("/api/tickets", {"estado": "resuelto"})
        result: list[dict] = []
        for t in tickets:
            result.append({
                "ticket_id": t.get("id"),
                "ticket_name": f"TCK-{t.get('id', 0):04d}",
                "ticket_type": t.get("tipo_requerimiento", ""),
                "category": t.get("categoria", ""),
                "description": t.get("descripcion", ""),
                "motivo_resolucion": t.get("resolucion", ""),
            })
        return result

    # ── Operation metrics ─────────────────────────────────────────────────────

    async def get_operation_metrics(self) -> dict:
        """
        Dev stub — returns empty operation metrics.

        The Express backend doesn't expose aggregated KPIs yet.
        When it does, replace this with real queries.
        """
        return {
            "avg_time_to_assign_hours": 0.0,
            "avg_time_to_resolve_hours": 0.0,
            "tickets_by_category": [],
            "tickets_by_urgency": [],
            "approval_rate": {"approved": 0, "rejected": 0, "pending": 0},
            "reopen_rate": 0.0,
        }
