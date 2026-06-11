"""
Generic HTTP adapter — PRODUCTION.

Configurable for Odoo REST API via environment variables.
All endpoints, headers, and field mappings are set in settings.py / .env.

To connect to Odoo:
    BACKEND_ADAPTER=http
    ODOO_BASE_URL=https://your-instance.odoo.com
    ODOO_API_KEY=your-api-key
    ODOO_DATABASE=your-db-name

ARCHITECTURE NOTE (Fase 8 — async migration):
    All methods are ``async def`` and use a shared ``httpx.AsyncClient`` with
    a connection pool. The client is created in ``__init__`` and must be
    closed via ``await adapter.close()`` on shutdown.
"""

import httpx

from config.settings import settings
from ports.ticket_port import ITicketPort


class HttpAdapter(ITicketPort):
    """
    Generic REST adapter for production ticket systems.

    Configured entirely via environment variables — no hardcoded endpoints.
    Current implementation targets Odoo 17+ REST API format.

    Override :meth:`_build_headers` and endpoint paths to support other systems.
    """

    def __init__(self) -> None:
        self._base_url: str = settings.odoo_base_url.rstrip("/")
        self._api_key: str = settings.odoo_api_key
        self._database: str = settings.odoo_database

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

    def _build_headers(self) -> dict:
        """
        Return authentication headers for the Odoo REST API.

        To switch to a different auth scheme:
        1. Override this method in a subclass
        2. Or replace these headers with the target system's requirements

        Returns:
            dict: Headers dict.
        """
        return {
            "Authorization": f"Bearer {self._api_key}",
            "X-Odoo-Database": self._database,
            "Content-Type": "application/json",
        }

    async def _get(self, path: str, params: dict | None = None) -> list | dict:
        """GET request helper."""
        try:
            response = await self._client.get(
                f"{self._base_url}{path}",
                headers=self._build_headers(),
                params=params,
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"HTTP GET {path} failed: {exc}") from exc

    async def _post(self, path: str, body: dict) -> dict:
        """POST request helper."""
        try:
            response = await self._client.post(
                f"{self._base_url}{path}",
                json=body,
                headers=self._build_headers(),
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"HTTP POST {path} failed: {exc}") from exc

    async def _put(self, path: str, body: dict) -> dict:
        """PUT request helper."""
        try:
            response = await self._client.put(
                f"{self._base_url}{path}",
                json=body,
                headers=self._build_headers(),
            )
            response.raise_for_status()
            return response.json()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"HTTP PUT {path} failed: {exc}") from exc

    # ── Ticket operations ────────────────────────────────────────────────────

    async def create_ticket(self, payload: dict, user_id: int) -> dict:
        """
        Create a ticket via Odoo REST API.

        Payload uses Odoo technical field names directly — no translation needed.

        Args:
            payload: Ticket data.
            user_id: Creator's user ID.

        Returns:
            dict: ``{"success": True, "ticket_name": str, "ticket_id": int}``.
        """
        result = await self._post("/api/helpdesk/ticket", payload)
        return {
            "success": True,
            "ticket_name": result.get("name", ""),
            "ticket_id": result.get("id", 0),
        }

    async def get_tickets_by_creator(self, user_id: int) -> list:
        """Return all tickets created by the given user."""
        return await self._get("/api/helpdesk/ticket", {"usuario_solicitante_id": user_id})

    async def get_tickets_by_assignee(self, user_id: int) -> list:
        """Return all tickets assigned to the given user."""
        return await self._get("/api/helpdesk/ticket", {"asignado_a": user_id})

    async def get_ticket_detail(self, ticket_id: int, user_id: int, role: str) -> dict:
        """Return full ticket details."""
        return await self._get(f"/api/helpdesk/ticket/{ticket_id}")

    async def resolve_ticket(
        self,
        ticket_id: int,
        motivo_resolucion: str,
        causa_raiz: str,
        user_id: int,
    ) -> dict:
        """
        Resolve a ticket by writing resolution fields.

        Note: stage change via REST API requires knowing the resolve stage ID.
        The actual stage must be queried from :meth:`get_stages`.
        """
        return await self._put(
            f"/api/helpdesk/ticket/{ticket_id}",
            {
                "motivo_resolucion": motivo_resolucion,
                "causa_raiz": causa_raiz,
            },
        )

    async def update_ticket(self, ticket_id: int, fields: dict, user_id: int) -> dict:
        """Update arbitrary ticket fields."""
        return await self._put(f"/api/helpdesk/ticket/{ticket_id}", fields)

    async def get_all_tickets(self, filters: dict | None = None) -> list:
        """Return all tickets, optionally filtered."""
        return await self._get("/api/helpdesk/ticket", filters or {})

    async def assign_ticket(
        self,
        ticket_id: int,
        assignee_id: int,
        agent_group_id: int,
        user_id: int,
    ) -> dict:
        """Assign a ticket to an agent and agent group."""
        return await self._put(
            f"/api/helpdesk/ticket/{ticket_id}",
            {"asignado_a": assignee_id, "agent_group_id": agent_group_id},
        )

    async def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """Reopen a resolved/closed ticket."""
        return await self._put(
            f"/api/helpdesk/ticket/{ticket_id}",
            {"stage_id": None, "causa_raiz": reason},
        )

    async def delete_ticket(self, ticket_id: int, user_id: int) -> dict:
        """
        Permanently delete a ticket.

        SECURITY: Implemented but ``delete_ticket`` tool is excluded from all
        role tool lists.
        """
        try:
            response = await self._client.delete(
                f"{self._base_url}/api/helpdesk/ticket/{ticket_id}",
                headers=self._build_headers(),
            )
            response.raise_for_status()
            return {"success": True}
        except httpx.HTTPError as exc:
            raise RuntimeError(f"HTTP DELETE failed: {exc}") from exc

    # ── Catalog queries ──────────────────────────────────────────────────────

    async def get_resolvers(self) -> list:
        """Return users with the resolver role."""
        return await self._get("/api/helpdesk/agent")

    async def get_agent_groups(self) -> list:
        """Return all available agent groups."""
        return await self._get("/api/helpdesk/agent-group")

    async def get_ticket_types(self) -> list:
        """Return available ticket types."""
        return await self._get("/api/helpdesk/ticket-type")

    async def get_categories(self, parent_id: int | None = None) -> list:
        """
        Return categories from the 3-level hierarchy.

        Args:
            parent_id: If ``None``, returns Level 1 categories.
        """
        params = {"parent_id": parent_id} if parent_id else {"level": 1}
        return await self._get("/api/helpdesk/category", params)

    async def get_urgency_levels(self) -> list:
        """Return urgency catalog."""
        return await self._get("/api/helpdesk/urgency")

    async def get_impact_levels(self) -> list:
        """Return impact catalog."""
        return await self._get("/api/helpdesk/impact")

    async def get_priority_levels(self) -> list:
        """Return priority catalog."""
        return await self._get("/api/helpdesk/priority")

    async def get_stages(self) -> list:
        """Return workflow stages with their flags."""
        return await self._get("/api/helpdesk/stage")

    async def get_resolved_tickets(self) -> list:
        """Return resolved tickets for RAG seeding."""
        raw = await self._get("/api/helpdesk/ticket", {
            "is_resolve_stage": True,
            "fields": "id,name,ticket_type_id,category_id,descripcion,motivo_resolucion",
        })
        result: list[dict] = []
        for t in raw:
            result.append({
                "ticket_id": t.get("id"),
                "ticket_name": t.get("name", ""),
                "ticket_type": t.get("ticket_type_id", {}).get("name", "") if isinstance(t.get("ticket_type_id"), dict) else "",
                "category": t.get("category_id", {}).get("name", "") if isinstance(t.get("category_id"), dict) else "",
                "description": t.get("descripcion", ""),
                "motivo_resolucion": t.get("motivo_resolucion", ""),
            })
        return result
