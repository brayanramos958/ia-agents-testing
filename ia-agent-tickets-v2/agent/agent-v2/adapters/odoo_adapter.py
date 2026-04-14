"""
Odoo 15 Community adapter — PRODUCTION.

Connects to Odoo 15 via JSON-RPC 2.0 (/web/dataset/call_kw).
Authentication via session cookie obtained from /web/session/authenticate.

Environment variables required (set in .env):
    BACKEND_ADAPTER=odoo
    ODOO_BASE_URL=https://your-odoo-instance.com
    ODOO_DATABASE=your-db-name
    ODOO_USER=service-user@company.com
    ODOO_PASSWORD=service-user-password

NOTE: Odoo 15 Community does NOT have a REST API.
      All operations go through JSON-RPC 2.0 on /web/dataset/call_kw.
      Bearer token auth is Odoo 17+ only — do NOT use it here.
"""

import httpx
from ports.ticket_port import ITicketPort
from config.settings import settings


class OdooAdapter(ITicketPort):
    """
    Production adapter for Odoo 15 Community Helpdesk.

    Uses the ITS_Helpdesk_base model: helpdesk.ticket.base
    Extended by ITS_Helpdesk_custom: approval, viewers, BCC, private notes.

    The agent only uses the base fields — custom fields are Odoo-internal.
    """

    def __init__(self):
        self._base_url = settings.odoo_base_url.rstrip("/")
        self._db       = settings.odoo_database
        self._user     = settings.odoo_user
        self._password = settings.odoo_password

        self._session_id: str | None = None
        self._uid: int | None = None

        # Stage ID cache — avoids repeated lookups on every resolve/reopen
        self._resolve_stage_id: int | None = None
        self._start_stage_id: int | None = None

    # ── Authentication ────────────────────────────────────────────────────────

    def _authenticate(self) -> None:
        """
        Obtains a session cookie from Odoo.
        Called lazily on first request and on session expiry.
        """
        resp = httpx.post(
            f"{self._base_url}/web/session/authenticate",
            json={
                "jsonrpc": "2.0",
                "method":  "call",
                "params": {
                    "db":       self._db,
                    "login":    self._user,
                    "password": self._password,
                },
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        body = resp.json()

        if body.get("error"):
            msg = body["error"].get("data", {}).get("message", str(body["error"]))
            raise RuntimeError(f"Odoo authentication failed: {msg}")

        result = body.get("result", {})
        if not result.get("uid"):
            raise RuntimeError(
                "Odoo authentication failed: invalid credentials or database name."
            )

        self._session_id = resp.cookies.get("session_id")
        self._uid = result["uid"]

    def _ensure_session(self) -> None:
        """Authenticates if no session exists."""
        if not self._session_id or not self._uid:
            self._authenticate()

    # ── JSON-RPC core ─────────────────────────────────────────────────────────

    def _call_kw(self, model: str, method: str, args: list, kwargs: dict = None) -> any:
        """
        Executes an Odoo ORM method via JSON-RPC.

        Args:
            model:  Odoo model technical name  (e.g. "helpdesk.ticket.base")
            method: ORM method                 (e.g. "search_read", "create", "write")
            args:   Positional arguments list
            kwargs: Keyword arguments dict (fields, limit, domain, etc.)

        Returns the JSON-RPC result value.
        Raises RuntimeError with the Odoo error message on failure.
        """
        self._ensure_session()

        payload = {
            "jsonrpc": "2.0",
            "method":  "call",
            "params": {
                "model":  model,
                "method": method,
                "args":   args,
                "kwargs": kwargs or {},
            },
        }

        resp = httpx.post(
            f"{self._base_url}/web/dataset/call_kw",
            json=payload,
            cookies={"session_id": self._session_id},
            timeout=30.0,
        )
        resp.raise_for_status()
        body = resp.json()

        if body.get("error"):
            err_data = body["error"].get("data", {})
            msg = err_data.get("message") or str(body["error"])

            # Re-authenticate on session expiry and retry once
            if "session" in msg.lower() or "invalid" in msg.lower():
                self._session_id = None
                self._uid = None
                return self._call_kw(model, method, args, kwargs)

            raise RuntimeError(f"Odoo error [{model}.{method}]: {msg}")

        return body["result"]

    # ── Stage helpers ─────────────────────────────────────────────────────────

    def _get_resolve_stage_id(self) -> int:
        """Returns the ID of the stage with is_resolve=True. Cached after first call."""
        if self._resolve_stage_id:
            return self._resolve_stage_id

        stages = self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[[["is_resolve", "=", True], ["active", "=", True]]]],
            {"fields": ["id", "name"], "limit": 1},
        )
        if not stages:
            raise RuntimeError(
                "No existe ningún estado con 'is_resolve=True' configurado en Odoo. "
                "Por favor configura un estado de Resolución en el módulo Helpdesk."
            )
        self._resolve_stage_id = stages[0]["id"]
        return self._resolve_stage_id

    def _get_start_stage_id(self) -> int:
        """Returns the ID of the stage with is_start=True. Cached after first call."""
        if self._start_stage_id:
            return self._start_stage_id

        stages = self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[[["is_start", "=", True], ["active", "=", True]]]],
            {"fields": ["id", "name"], "limit": 1},
        )
        if not stages:
            raise RuntimeError(
                "No existe ningún estado con 'is_start=True' configurado en Odoo. "
                "Por favor configura un estado Inicial en el módulo Helpdesk."
            )
        self._start_stage_id = stages[0]["id"]
        return self._start_stage_id

    # ── Ticket operations ────────────────────────────────────────────────────

    def create_ticket(self, payload: dict, user_id: int) -> dict:
        """
        Creates a ticket in Odoo.

        Resolves partner_id from user_id automatically (required field in Odoo).
        Maps system_equipment into descripcion as a suffix if provided.
        """
        # 1. Resolve partner_id from user_id — required field in helpdesk.ticket.base
        user_data = self._call_kw(
            "res.users", "read",
            [[user_id]],
            {"fields": ["partner_id"]},
        )
        if not user_data:
            return {"success": False, "error": f"User {user_id} not found in Odoo"}
        partner_id = user_data[0]["partner_id"][0]  # partner_id is [id, name] tuple

        # 2. Map system_equipment → descripcion suffix (no such field in Odoo)
        descripcion = payload.get("descripcion", "")
        if payload.get("system_equipment"):
            descripcion += f"\n\nEquipo/Sistema afectado: {payload['system_equipment']}"

        # 3. Build Odoo-native payload
        odoo_vals = {
            "asunto":         payload["asunto"],
            "descripcion":    descripcion,
            "ticket_type_id": payload["ticket_type_id"],
            "category_id":    payload["category_id"],
            "urgency_id":     payload["urgency_id"],
            "impact_id":      payload["impact_id"],
            "priority_id":    payload["priority_id"],
            "partner_id":     partner_id,
        }
        # Optional classification fields
        if payload.get("subcategory_id"):
            odoo_vals["subcategory_id"] = payload["subcategory_id"]
        if payload.get("element_id"):
            odoo_vals["element_id"] = payload["element_id"]

        # 4. Create and return
        ticket_id = self._call_kw("helpdesk.ticket.base", "create", [odoo_vals])
        ticket = self._call_kw(
            "helpdesk.ticket.base", "read",
            [[ticket_id]],
            {"fields": ["name"]},
        )
        return {
            "success":     True,
            "ticket_name": ticket[0]["name"],
            "ticket_id":   ticket_id,
        }

    def get_tickets_by_creator(self, user_id: int) -> list:
        """Returns tickets created by or for the given user."""
        return self._call_kw(
            "helpdesk.ticket.base", "search_read",
            [[["|",
               ["creado_por", "=", user_id],
               ["usuario_solicitante_id", "=", user_id]]]],
            {"fields": [
                "name", "asunto", "stage_id", "urgency_id",
                "ticket_type_id", "fecha_creacion", "partner_id",
            ]},
        )

    def get_tickets_by_assignee(self, user_id: int) -> list:
        """Returns tickets currently assigned to the given agent."""
        return self._call_kw(
            "helpdesk.ticket.base", "search_read",
            [[[["asignado_a", "=", user_id], ["stage_id.is_close", "=", False]]]],
            {"fields": [
                "name", "asunto", "stage_id", "urgency_id", "priority_id",
                "ticket_type_id", "partner_id", "fecha_creacion",
            ]},
        )

    def get_ticket_detail(self, ticket_id: int, user_id: int, role: str) -> dict:
        """Returns full ticket details."""
        tickets = self._call_kw(
            "helpdesk.ticket.base", "read",
            [[ticket_id]],
            {"fields": [
                "name", "asunto", "descripcion", "causa_raiz", "motivo_resolucion",
                "stage_id", "ticket_type_id", "category_id", "subcategory_id", "element_id",
                "priority_id", "urgency_id", "impact_id",
                "partner_id", "asignado_a", "agent_group_id",
                "sla_id", "deadline_date", "sla_status",
                "fecha_creacion", "fecha_cierre", "ultima_modificacion",
            ]},
        )
        if not tickets:
            return {"error": f"Ticket {ticket_id} not found"}
        return tickets[0]

    def resolve_ticket(self, ticket_id: int, motivo_resolucion: str,
                       causa_raiz: str, user_id: int) -> dict:
        """
        Resolves a ticket: sets resolution fields AND moves to the resolve stage.
        The stage change is mandatory — Odoo does not auto-transition.
        """
        resolve_stage_id = self._get_resolve_stage_id()

        self._call_kw(
            "helpdesk.ticket.base", "write",
            [[ticket_id], {
                "motivo_resolucion": motivo_resolucion,
                "causa_raiz":        causa_raiz,
                "stage_id":          resolve_stage_id,
            }],
        )
        return {"success": True, "ticket_id": ticket_id}

    def update_ticket(self, ticket_id: int, fields: dict, user_id: int) -> dict:
        """Updates arbitrary ticket fields using Odoo technical field names."""
        self._call_kw("helpdesk.ticket.base", "write", [[ticket_id], fields])
        return {"success": True, "ticket_id": ticket_id}

    def get_all_tickets(self, filters: dict = None) -> list:
        """Returns all tickets. Supports filters dict with Odoo field names."""
        domain = []
        if filters:
            for key, value in filters.items():
                domain.append([key, "=", value])

        return self._call_kw(
            "helpdesk.ticket.base", "search_read",
            [domain],
            {"fields": [
                "name", "asunto", "stage_id", "urgency_id", "priority_id",
                "ticket_type_id", "partner_id", "asignado_a",
                "agent_group_id", "fecha_creacion", "sla_status",
            ], "limit": 200},
        )

    def assign_ticket(self, ticket_id: int, assignee_id: int,
                      agent_group_id: int, user_id: int) -> dict:
        """Assigns a ticket to an agent and agent group."""
        vals = {"asignado_a": assignee_id}
        if agent_group_id:
            vals["agent_group_id"] = agent_group_id

        self._call_kw("helpdesk.ticket.base", "write", [[ticket_id], vals])
        return {"success": True, "ticket_id": ticket_id}

    def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """
        Reopens a resolved/closed ticket by moving it back to the start stage.
        Stores the reason in motivo_resolucion for audit trail.
        """
        start_stage_id = self._get_start_stage_id()

        self._call_kw(
            "helpdesk.ticket.base", "write",
            [[ticket_id], {
                "stage_id":          start_stage_id,
                "motivo_resolucion": f"Reabierto: {reason}",
                "fecha_cierre":      False,
            }],
        )
        return {"success": True, "ticket_id": ticket_id}

    def delete_ticket(self, ticket_id: int, user_id: int) -> dict:
        # SECURITY: Implemented but delete_ticket tool is excluded from all role tool lists.
        self._call_kw("helpdesk.ticket.base", "unlink", [[ticket_id]])
        return {"success": True}

    # ── Catalog queries ──────────────────────────────────────────────────────

    def get_ticket_types(self) -> list:
        return self._call_kw(
            "helpdesk.ticket.type", "search_read",
            [[[["active", "=", True]]]],
            {"fields": ["id", "name"], "order": "sequence"},
        )

    def get_categories(self, parent_id: int = None) -> list:
        """
        Returns categories from the 3-level hierarchy.
            parent_id=None  → Level 1 root categories
            parent_id=<id>  → Children of that category (L2 or L3)
        """
        if parent_id is None:
            domain = [["level", "=", 1], ["active", "=", True]]
        else:
            domain = [["parent_id", "=", parent_id], ["active", "=", True]]

        return self._call_kw(
            "helpdesk.category", "search_read",
            [[domain]],
            {"fields": ["id", "name", "full_name", "level", "parent_id"], "order": "sequence"},
        )

    def get_urgency_levels(self) -> list:
        return self._call_kw(
            "helpdesk.ticket.urgency", "search_read",
            [[[["active", "=", True]]]],
            {"fields": ["id", "name"], "order": "sequence"},
        )

    def get_impact_levels(self) -> list:
        return self._call_kw(
            "helpdesk.ticket.impact", "search_read",
            [[[["active", "=", True]]]],
            {"fields": ["id", "name"], "order": "sequence"},
        )

    def get_priority_levels(self) -> list:
        return self._call_kw(
            "helpdesk.ticket.priority", "search_read",
            [[[["active", "=", True]]]],
            {"fields": ["id", "name"], "order": "sequence"},
        )

    def get_stages(self) -> list:
        """
        Returns all active stages with their workflow flags.
        The agent uses is_resolve, is_start, is_close, is_pause to make decisions.
        """
        return self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[[["active", "=", True]]]],
            {"fields": ["id", "name", "is_start", "is_resolve", "is_close", "is_pause"],
             "order": "sequence"},
        )

    def get_agent_groups(self) -> list:
        return self._call_kw(
            "helpdesk.agent.group", "search_read",
            [[[]]],
            {"fields": ["id", "name"]},
        )

    def get_resolvers(self) -> list:
        """
        Returns users that belong to the helpdesk agent or manager group.
        Filters by group technical name from ITS_Helpdesk_base security.
        """
        return self._call_kw(
            "res.users", "search_read",
            [[[
                ["share", "=", False],
                "|",
                ["groups_id.full_name", "ilike", "Helpdesk / Agente"],
                ["groups_id.full_name", "ilike", "Helpdesk / Manager"],
            ]]],
            {"fields": ["id", "name", "login"]},
        )

    def get_resolved_tickets(self) -> list:
        """
        Returns resolved tickets for RAG seeding.
        Fetches tickets in stages with is_resolve=True or is_close=True.
        """
        raw = self._call_kw(
            "helpdesk.ticket.base", "search_read",
            [[["|",
               ["stage_id.is_resolve", "=", True],
               ["stage_id.is_close",   "=", True]]]],
            {"fields": [
                "id", "name", "ticket_type_id", "category_id",
                "descripcion", "motivo_resolucion",
            ], "limit": 500},
        )

        result = []
        for t in raw:
            if not t.get("motivo_resolucion"):
                continue  # Skip tickets without resolution text — not useful for RAG

            result.append({
                "ticket_id":         t["id"],
                "ticket_name":       t.get("name", ""),
                "ticket_type":       t["ticket_type_id"][1] if isinstance(t.get("ticket_type_id"), list) else "",
                "category":          t["category_id"][1]    if isinstance(t.get("category_id"), list)    else "",
                "description":       t.get("descripcion", ""),
                "motivo_resolucion": t.get("motivo_resolucion", ""),
            })
        return result
