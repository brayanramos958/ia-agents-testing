"""
Generic HTTP adapter — PRODUCTION.

Configurable for Odoo REST API via environment variables.
All endpoints, headers, and field mappings are set in settings.py / .env.

To connect to Odoo:
    BACKEND_ADAPTER=http
    ODOO_BASE_URL=https://your-instance.odoo.com
    ODOO_API_KEY=your-api-key
    ODOO_DATABASE=your-db-name
"""

import httpx
from ports.ticket_port import ITicketPort
from config.settings import settings


class HttpAdapter(ITicketPort):
    """
    Generic REST adapter for production ticket systems.
    Configured entirely via environment variables — no hardcoded endpoints.

    Current implementation targets Odoo 17+ REST API format.
    Override _build_headers() and endpoint paths to support other systems.
    """

    def __init__(self):
        self._base_url = settings.odoo_base_url.rstrip("/")
        self._api_key  = settings.odoo_api_key
        self._database = settings.odoo_database

    def _build_headers(self) -> dict:
        """
        Returns authentication headers for Odoo REST API.

        To switch to a different auth scheme:
        1. Override this method in a subclass
        2. Or replace these headers with the target system's requirements
        """
        return {
            "Authorization": f"Bearer {self._api_key}",
            "X-Odoo-Database": self._database,
            "Content-Type": "application/json",
        }

    def _get(self, path: str, params: dict = None) -> list | dict:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{self._base_url}{path}",
                headers=self._build_headers(),
                params=params,
            )
            response.raise_for_status()
            return response.json()

    def _post(self, path: str, body: dict) -> dict:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{self._base_url}{path}",
                json=body,
                headers=self._build_headers(),
            )
            response.raise_for_status()
            return response.json()

    def _put(self, path: str, body: dict) -> dict:
        with httpx.Client(timeout=30.0) as client:
            response = client.put(
                f"{self._base_url}{path}",
                json=body,
                headers=self._build_headers(),
            )
            response.raise_for_status()
            return response.json()

    # ── Ticket operations ────────────────────────────────────────────────────

    def create_ticket(self, payload: dict, user_id: int) -> dict:
        """
        Creates a ticket via Odoo REST API.
        Payload uses Odoo technical field names directly — no translation needed.
        """
        result = self._post("/api/helpdesk/ticket", payload)
        return {
            "success": True,
            "ticket_name": result.get("name", ""),
            "ticket_id": result.get("id", 0),
        }

    def get_tickets_by_creator(self, user_id: int) -> list:
        return self._get("/api/helpdesk/ticket", {"usuario_solicitante_id": user_id})

    def get_tickets_by_assignee(self, user_id: int) -> list:
        return self._get("/api/helpdesk/ticket", {"asignado_a": user_id})

    def get_ticket_detail(self, ticket_id: int, user_id: int, role: str) -> dict:
        return self._get(f"/api/helpdesk/ticket/{ticket_id}")

    def resolve_ticket(self, ticket_id: int, motivo_resolucion: str,
                       causa_raiz: str, user_id: int) -> dict:
        return self._put(
            f"/api/helpdesk/ticket/{ticket_id}",
            {
                "motivo_resolucion": motivo_resolucion,
                "causa_raiz": causa_raiz,
                # Move to resolve stage — Odoo stage change via write on stage_id
                # The actual resolve stage ID must be queried from get_stages()
            },
        )

    def update_ticket(self, ticket_id: int, fields: dict, user_id: int) -> dict:
        return self._put(f"/api/helpdesk/ticket/{ticket_id}", fields)

    def get_all_tickets(self, filters: dict = None) -> list:
        return self._get("/api/helpdesk/ticket", filters or {})

    def assign_ticket(self, ticket_id: int, assignee_id: int,
                      agent_group_id: int, user_id: int) -> dict:
        return self._put(
            f"/api/helpdesk/ticket/{ticket_id}",
            {"asignado_a": assignee_id, "agent_group_id": agent_group_id},
        )

    def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        return self._put(
            f"/api/helpdesk/ticket/{ticket_id}",
            {"stage_id": None, "causa_raiz": reason},  # Set stage back to open
        )

    def delete_ticket(self, ticket_id: int, user_id: int) -> dict:
        # SECURITY: This method is implemented but delete_ticket tool is excluded
        # from all role tool lists. See tools/ticket_tools.py for the exclusion comment.
        with httpx.Client(timeout=30.0) as client:
            response = client.delete(
                f"{self._base_url}/api/helpdesk/ticket/{ticket_id}",
                headers=self._build_headers(),
            )
            response.raise_for_status()
            return {"success": True}

    # ── Catalog queries ──────────────────────────────────────────────────────

    def get_resolvers(self) -> list:
        return self._get("/api/helpdesk/agent")

    def get_agent_groups(self) -> list:
        return self._get("/api/helpdesk/agent-group")

    def get_ticket_types(self) -> list:
        return self._get("/api/helpdesk/ticket-type")

    def get_categories(self, parent_id: int = None) -> list:
        params = {"parent_id": parent_id} if parent_id else {"level": 1}
        return self._get("/api/helpdesk/category", params)

    def get_urgency_levels(self) -> list:
        return self._get("/api/helpdesk/urgency")

    def get_impact_levels(self) -> list:
        return self._get("/api/helpdesk/impact")

    def get_priority_levels(self) -> list:
        return self._get("/api/helpdesk/priority")

    def get_stages(self) -> list:
        return self._get("/api/helpdesk/stage")

    def get_resolved_tickets(self) -> list:
        raw = self._get("/api/helpdesk/ticket", {
            "is_resolve_stage": True,
            "fields": "id,name,ticket_type_id,category_id,descripcion,motivo_resolucion",
        })
        result = []
        for t in raw:
            result.append({
                "ticket_id":         t.get("id"),
                "ticket_name":       t.get("name", ""),
                "ticket_type":       t.get("ticket_type_id", {}).get("name", "") if isinstance(t.get("ticket_type_id"), dict) else "",
                "category":          t.get("category_id", {}).get("name", "") if isinstance(t.get("category_id"), dict) else "",
                "description":       t.get("descripcion", ""),
                "motivo_resolucion": t.get("motivo_resolucion", ""),
            })
        return result
