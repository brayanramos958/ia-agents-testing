"""
Express backend adapter — DEV ONLY.

Maps the simplified Express/SQLite schema to ITicketPort.
Translates between Odoo-style FK IDs (used by the agent) and
string enums (used by the Express backend).

DO NOT use this adapter in production.
For production, use HttpAdapter configured for the Odoo REST API.
"""

import httpx
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
_TYPE_MAP    = {t["id"]: t["name"] for t in DEV_TICKET_TYPES}
_CAT_MAP     = {c["id"]: c["name"] for c in DEV_CATEGORIES}
_URGENCY_MAP = {u["id"]: u["name"] for u in DEV_URGENCY}
_IMPACT_MAP  = {i["id"]: i["name"] for i in DEV_IMPACT}
_PRIORITY_MAP= {p["id"]: p["name"] for p in DEV_PRIORITY}


class ExpressAdapter(ITicketPort):
    """
    Connects to the local Express + SQLite dev backend.
    Translates Odoo-style IDs ↔ Express string enums internally.
    """

    def __init__(self, base_url: str):
        self._base_url = base_url.rstrip("/")

    def _headers(self, user_id: int, user_rol: str) -> dict:
        return {
            "x-user-id": str(user_id),
            "x-user-rol": user_rol,
        }

    def _get(self, path: str, params: dict = None) -> dict | list:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.get(f"{self._base_url}{path}", params=params)
            response.raise_for_status()
            return response.json()

    def _post(self, path: str, body: dict, user_id: int, user_rol: str) -> dict:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.post(
                f"{self._base_url}{path}",
                json=body,
                headers=self._headers(user_id, user_rol),
            )
            return response.json()

    def _put(self, path: str, body: dict, user_id: int, user_rol: str) -> dict:
        with httpx.Client(timeout=30.0, follow_redirects=True) as client:
            response = client.put(
                f"{self._base_url}{path}",
                json=body,
                headers=self._headers(user_id, user_rol),
            )
            return response.json()

    # ── Ticket operations ────────────────────────────────────────────────────

    def create_ticket(self, payload: dict, user_id: int) -> dict:
        # Translate Odoo FK IDs to Express string values
        express_body = {
            "tipo_requerimiento": _TYPE_MAP.get(payload.get("ticket_type_id"), "Incidente"),
            "categoria":          _CAT_MAP.get(payload.get("category_id"), "Otro"),
            "descripcion":        payload.get("descripcion", ""),
            "urgencia":           _URGENCY_MAP.get(payload.get("urgency_id"), "media"),
            "impacto":            _IMPACT_MAP.get(payload.get("impact_id"), "medio"),
            "prioridad":          _PRIORITY_MAP.get(payload.get("priority_id"), "media"),
            "created_by":         user_id,
        }
        # Use asunto as descripcion if provided (Express uses descripcion as title)
        if payload.get("asunto"):
            express_body["descripcion"] = payload["asunto"]
            if payload.get("descripcion"):
                express_body["descripcion"] += f"\n\n{payload['descripcion']}"

        result = self._post("/api/tickets", express_body, user_id, "creador")
        if result.get("id"):
            return {
                "success": True,
                "ticket_name": f"TCK-{result['id']:04d}",
                "ticket_id": result["id"],
            }
        return {"success": False, "error": result.get("error", "Unknown error")}

    def get_tickets_by_creator(self, user_id: int) -> list:
        return self._get("/api/tickets", {"created_by": user_id})

    def get_tickets_by_assignee(self, user_id: int) -> list:
        return self._get("/api/tickets", {"asignado_a": user_id})

    def get_ticket_detail(self, ticket_id: int, user_id: int, role: str) -> dict:
        return self._get(f"/api/tickets/{ticket_id}")

    def resolve_ticket(self, ticket_id: int, motivo_resolucion: str,
                       causa_raiz: str, user_id: int) -> dict:
        # Express uses "resolucion"; we store the full text combining both fields
        resolution_text = motivo_resolucion
        if causa_raiz:
            resolution_text += f"\n\nRoot cause: {causa_raiz}"
        return self._put(
            f"/api/tickets/{ticket_id}/resolve",
            {"resolucion": resolution_text},
            user_id,
            "resueltor",
        )

    def update_ticket(self, ticket_id: int, fields: dict, user_id: int) -> dict:
        return self._put(f"/api/tickets/{ticket_id}", fields, user_id, "creador")

    def get_all_tickets(self, filters: dict = None) -> list:
        return self._get("/api/tickets", filters or {})

    def assign_ticket(self, ticket_id: int, assignee_id: int,
                      agent_group_id: int, user_id: int) -> dict:
        return self._put(
            f"/api/tickets/{ticket_id}/assign",
            {"asignado_a": assignee_id},
            user_id,
            "supervisor",
        )

    def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        return self._put(
            f"/api/tickets/{ticket_id}/reopen",
            {"motivo": reason},
            user_id,
            "supervisor",
        )

    def delete_ticket(self, ticket_id: int, user_id: int) -> dict:
        # SECURITY: This method is implemented but delete_ticket tool is excluded
        # from all role tool lists. See tools/ticket_tools.py for the exclusion comment.
        with httpx.Client(timeout=30.0) as client:
            response = client.delete(
                f"{self._base_url}/api/tickets/{ticket_id}",
                headers=self._headers(user_id, "supervisor"),
            )
            return response.json()

    # ── Catalog queries ──────────────────────────────────────────────────────
    # Return hardcoded dev catalogs. HttpAdapter will fetch these from Odoo API.

    def get_resolvers(self) -> list:
        return self._get("/api/users", {"rol": "resueltor"})

    def get_agent_groups(self) -> list:
        return [{"id": 1, "name": "Soporte N1"}, {"id": 2, "name": "Soporte N2"}]

    def get_ticket_types(self) -> list:
        return DEV_TICKET_TYPES

    def get_categories(self, parent_id: int = None) -> list:
        return [c for c in DEV_CATEGORIES if c["parent_id"] == parent_id]

    def get_urgency_levels(self) -> list:
        return DEV_URGENCY

    def get_impact_levels(self) -> list:
        return DEV_IMPACT

    def get_priority_levels(self) -> list:
        return DEV_PRIORITY

    def get_stages(self) -> list:
        return DEV_STAGES

    def get_resolved_tickets(self) -> list:
        tickets = self._get("/api/tickets", {"estado": "resuelto"})
        result = []
        for t in tickets:
            result.append({
                "ticket_id":         t.get("id"),
                "ticket_name":       f"TCK-{t.get('id', 0):04d}",
                "ticket_type":       t.get("tipo_requerimiento", ""),
                "category":          t.get("categoria", ""),
                "description":       t.get("descripcion", ""),
                "motivo_resolucion": t.get("resolucion", ""),
            })
        return result
