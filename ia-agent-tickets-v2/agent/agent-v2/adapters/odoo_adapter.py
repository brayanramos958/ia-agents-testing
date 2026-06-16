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

ARCHITECTURE NOTE (Fase 8 — async migration):
    This adapter is fully async. All HTTP calls use ``httpx.AsyncClient``
    with a connection pool of 50. The session cookie is shared across all
    requests via the client's cookie jar.

    Concurrency:
        - Multiple concurrent ``_call_kw()`` calls reuse the same AsyncClient.
        - The session is obtained lazily on first request; subsequent calls
          share the same ``session_id`` cookie.
        - On session expiry, a single re-authentication is performed and
          retried. The ``_session_lock`` ensures only one coroutine
          re-authenticates at a time (no thundering herd).
        - ``get_operation_metrics()`` uses ``asyncio.gather()`` to run the
          5 Odoo read_group/search_count calls in parallel.
"""

import asyncio
import html as _html
import logging
from datetime import datetime
from typing import Any

import httpx

from config.settings import settings
from ports.ticket_port import ITicketPort

logger = logging.getLogger(__name__)


class OdooAdapter(ITicketPort):
    """
    Production adapter for Odoo 15 Community Helpdesk.

    Uses the ITS_Helpdesk_base model: helpdesk.ticket.base
    Extended by ITS_Helpdesk_custom: approval, viewers, BCC, private notes.

    The agent only uses the base fields — custom fields are Odoo-internal.

    Lifecycle:
        >>> adapter = OdooAdapter()
        >>> await adapter.close()  # release httpx connections
    """

    def __init__(self) -> None:
        self._base_url: str = settings.odoo_base_url.rstrip("/")
        self._db: str = settings.odoo_database
        self._user: str = settings.odoo_user
        self._password: str = settings.odoo_password

        # Session state — set lazily by _authenticate()
        self._session_id: str | None = None
        self._uid: int | None = None

        # Lock to prevent concurrent re-authentication (thundering herd protection)
        self._session_lock: asyncio.Lock = asyncio.Lock()

        # Stage ID cache — avoids repeated lookups on every resolve/reopen
        self._resolve_stage_id: int | None = None
        self._start_stage_id: int | None = None

        # httpx.AsyncClient with connection pool.
        # max_connections=50 matches the agent's expected concurrency limit.
        # max_keepalive_connections=20 keeps a warm pool to avoid handshake overhead.
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

    # ── HTML helper ──────────────────────────────────────────────────────────

    @staticmethod
    def _text_to_html(text: str) -> str:
        """
        Convert plain text to HTML for Odoo's ``fields.Html`` storage.

        Odoo stores ``descripcion``, ``causa_raiz`` and ``motivo_resolucion`` as
        ``fields.Html``. Sending plain text breaks chatter rendering and the
        resolution wizard validates a minimum of 10 real characters.

        Args:
            text: Plain text input.

        Returns:
            str: HTML-wrapped text with ``<p>`` and ``<br/>`` tags.
        """
        if not text:
            return ""
        escaped = _html.escape(str(text))
        paragraphs = escaped.split("\n\n")
        parts: list[str] = []
        for p in paragraphs:
            p = p.replace("\n", "<br/>").strip()
            if p:
                parts.append(f"<p>{p}</p>")
        return "".join(parts) if parts else f"<p>{escaped}</p>"

    # ── Authentication ────────────────────────────────────────────────────────

    async def _authenticate(self) -> None:
        """
        Obtain a session cookie from Odoo.

        Called lazily on first request and on session expiry. Uses
        ``_session_lock`` to ensure only one coroutine authenticates at a time.

        Raises:
            RuntimeError: If Odoo returns an error or invalid credentials.
        """
        logger.info("Odoo: authenticating against %s", self._base_url)
        try:
            resp = await self._client.post(
                f"{self._base_url}/web/session/authenticate",
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {
                        "db": self._db,
                        "login": self._user,
                        "password": self._password,
                    },
                },
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Odoo authentication request failed: {exc}") from exc

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
        # Note: We do NOT set the cookie on the AsyncClient cookie jar because
        # keep-alive connections in the pool may have stale cookies cached in
        # their request headers. Instead, _call_kw() reads self._session_id
        # fresh on every request and passes it as an explicit Cookie header.
        logger.info("Odoo: authenticated as uid=%s", self._uid)

    async def _ensure_session(self) -> None:
        """Authenticate if no session exists. Lock-protected."""
        if self._session_id and self._uid:
            return
        async with self._session_lock:
            # Re-check after acquiring the lock (double-checked locking)
            if self._session_id and self._uid:
                return
            await self._authenticate()

    async def authenticate_user(self, login: str, password: str) -> dict:
        """
        Authenticate a user against Odoo and return their basic info.

        This is a public-facing method (called by ``/auth/login``) and does NOT
        use the service-account session. It authenticates as the user directly.

        Args:
            login: Odoo login (email or username).
            password: Odoo password.

        Returns:
            dict: ``{"uid": int, "name": str, "login": str, "role": str}`` where
            role is one of ``"creador"``, ``"resueltor"``, ``"supervisor"``.

        Raises:
            ValueError: Invalid credentials or user not found in Odoo.
        """
        # Step 1: authenticate
        try:
            resp = await self._client.post(
                f"{self._base_url}/web/session/authenticate",
                json={
                    "jsonrpc": "2.0",
                    "method": "call",
                    "params": {"db": self._db, "login": login, "password": password},
                },
                timeout=httpx.Timeout(10.0, connect=5.0),
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise ValueError(f"Odoo request failed: {exc}") from exc

        body = resp.json()
        if body.get("error"):
            raise ValueError("Credenciales inválidas")

        result = body.get("result", {})
        uid = result.get("uid")
        if not uid:
            raise ValueError("Credenciales inválidas")

        # Step 2: read user info using the service account session
        await self._ensure_session()
        user_data = await self._call_kw(
            "res.users", "read",
            [[uid]],
            {"fields": ["id", "name", "login", "groups_id"]},
        )
        if not user_data:
            raise ValueError(f"Usuario {uid} no encontrado en Odoo")

        user = user_data[0]
        groups = user.get("groups_id", [])

        # Determine role from group membership using group IDs (stable across
        # Odoo version upgrades and language changes). See:
        #   ITS_Helpdesk_base/security/security.xml
        #     group_helpdesk_client    -> id 335 "Helpdesk Solicitante"  -> creador
        #     group_helpdesk_agent     -> id 334 "Helpdesk Agente"       -> resueltor
        #     group_helpdesk_manager   -> id 333 "Helpdesk Gestor"       -> supervisor
        #     group_helpdesk_admin     -> id 332 "Helpdesk Admin"        -> supervisor
        HELPDESK_GROUP_IDS = {
            335: "creador",      # Helpdesk Solicitante
            334: "resueltor",    # Helpdesk Agente
            333: "supervisor",   # Helpdesk Gestor
            332: "supervisor",   # Helpdesk Admin
        }
        role = "creador"  # default fallback

        def _gid(g):
            """Extract integer group ID from [id, name] tuple or int."""
            if isinstance(g, (list, tuple)) and len(g) >= 1:
                try:
                    return int(g[0])
                except (TypeError, ValueError):
                    return None
            if isinstance(g, int):
                return g
            return None

        # Priority: supervisor (admin/manager) > resueltor (agent) > creador (client)
        for g in groups:
            gid = _gid(g)
            if gid in (332, 333):
                role = "supervisor"
                break
            if gid == 334:
                role = "resueltor"
            # gid == 335 stays "creador" (default)

        return {
            "uid": uid,
            "name": user.get("name", ""),
            "login": user.get("login", login),
            "role": role,
        }

    # ── JSON-RPC core ─────────────────────────────────────────────────────────

    async def _call_kw(
        self,
        model: str,
        method: str,
        args: list,
        kwargs: dict | None = None,
        _retry_on_session_expiry: bool = True,
    ) -> Any:
        """
        Execute an Odoo ORM method via JSON-RPC.

        Args:
            model: Odoo model technical name (e.g. ``"helpdesk.ticket.base"``).
            method: ORM method (e.g. ``"search_read"``, ``"create"``, ``"write"``).
            args: Positional arguments list.
            kwargs: Keyword arguments dict (``fields``, ``limit``, ``domain``, etc.).

        Returns:
            Any: The JSON-RPC result value.

        Raises:
            RuntimeError: With the Odoo error message on failure.
        """
        await self._ensure_session()

        payload = {
            "jsonrpc": "2.0",
            "method": "call",
            "params": {
                "model": model,
                "method": method,
                "args": args,
                "kwargs": kwargs or {},
            },
        }

        try:
            # Pass session_id as explicit Cookie header on EVERY request.
            # This is more reliable than relying on the AsyncClient cookie jar
            # because keep-alive connections in the pool may have stale cookies
            # cached in their request headers. Reading self._session_id (the
            # freshest value) on every call avoids that race.
            cookies: dict | None = None
            if self._session_id:
                cookies = {"session_id": self._session_id}
            resp = await self._client.post(
                f"{self._base_url}/web/dataset/call_kw",
                json=payload,
                cookies=cookies,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            raise RuntimeError(f"Odoo HTTP error [{model}.{method}]: {exc}") from exc

        body = resp.json()

        if body.get("error"):
            err_data = body["error"].get("data", {})
            msg = err_data.get("message") or str(body["error"])

            # Re-authenticate on session expiry and retry once.
            # _retry_on_session_expiry=False prevents infinite recursion if
            # the re-authenticated session is ALSO rejected (e.g. invalid creds).
            if (
                _retry_on_session_expiry
                and ("session" in msg.lower() or "invalid" in msg.lower())
            ):
                logger.warning("Odoo session expired, re-authenticating")
                async with self._session_lock:
                    self._session_id = None
                    self._uid = None
                    await self._authenticate()
                # After re-auth, the new session_id is in the shared cookie jar.
                # All other concurrent coroutines waiting on _session_lock will
                # see the fresh session on their next call.
                return await self._call_kw(
                    model, method, args, kwargs,
                    _retry_on_session_expiry=False,
                )

            raise RuntimeError(f"Odoo error [{model}.{method}]: {msg}")

        return body["result"]

    # ── Stage helpers ─────────────────────────────────────────────────────────

    async def _get_resolve_stage_id(self) -> int:
        """
        Return the ID of the stage with ``is_resolve=True``. Cached after first call.

        Returns:
            int: Stage ID.

        Raises:
            RuntimeError: If no resolve stage is configured in Odoo.
        """
        if self._resolve_stage_id:
            return self._resolve_stage_id

        stages = await self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[["is_resolve", "=", True], ["active", "=", True]]],
            {"fields": ["id", "name"], "limit": 1},
        )
        if not stages:
            raise RuntimeError(
                "No existe ningún estado con 'is_resolve=True' configurado en Odoo. "
                "Por favor configura un estado de Resolución en el módulo Helpdesk."
            )
        self._resolve_stage_id = stages[0]["id"]
        return self._resolve_stage_id

    async def _get_start_stage_id(self) -> int:
        """
        Return the ID of the stage with ``is_start=True``. Cached after first call.

        Returns:
            int: Stage ID.

        Raises:
            RuntimeError: If no start stage is configured in Odoo.
        """
        if self._start_stage_id:
            return self._start_stage_id

        stages = await self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[["is_start", "=", True], ["active", "=", True]]],
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

    async def create_ticket(self, payload: dict, user_id: int) -> dict:
        """
        Create a ticket in Odoo.

        Resolves ``partner_id`` from ``user_id`` automatically (required field).
        Sets ``usuario_solicitante_id`` explicitly (onchange doesn't fire via JSON-RPC).
        Sends ``system_equipment`` as a standalone Char field (ITS_Helpdesk_custom).
        Wraps text fields (``descripcion``) as HTML for ``fields.Html`` compatibility.

        Args:
            payload: Ticket data. See :meth:`ITicketPort.create_ticket` for fields.
            user_id: Odoo res.users ID of the creator.

        Returns:
            dict: ``{"success": True, "ticket_name": str, "ticket_id": int}`` or
                  ``{"success": False, "error": str}``.
        """
        # 1. Resolve partner_id from user_id — required field in helpdesk.ticket.base
        user_data = await self._call_kw(
            "res.users", "read",
            [[user_id]],
            {"fields": ["partner_id"]},
        )
        if not user_data:
            return {"success": False, "error": f"User {user_id} not found in Odoo"}
        partner_id = user_data[0]["partner_id"][0]  # partner_id is [id, name] tuple

        # 2. Build Odoo-native payload
        odoo_vals: dict[str, Any] = {
            "asunto": payload["asunto"],
            "descripcion": self._text_to_html(payload.get("descripcion", "")),
            "ticket_type_id": payload["ticket_type_id"],
            "category_id": payload["category_id"],
            "urgency_id": payload["urgency_id"],
            "impact_id": payload["impact_id"],
            "priority_id": payload["priority_id"],
            "partner_id": partner_id,
            # Fix: @api.onchange('partner_id') no dispara vía JSON-RPC.
            # Sin este campo, el ticket no aparece en el portal del usuario.
            "usuario_solicitante_id": user_id,
        }
        # Optional classification fields
        if payload.get("subcategory_id"):
            odoo_vals["subcategory_id"] = payload["subcategory_id"]
        if payload.get("element_id"):
            odoo_vals["element_id"] = payload["element_id"]
        # Fix: system_equipment es un campo real en ITS_Helpdesk_custom (Char, tracking).
        # Antes se concatenaba a descripcion porque se asumía que no existía en Odoo.
        if payload.get("system_equipment"):
            odoo_vals["system_equipment"] = payload["system_equipment"]

        # 3. Create and return
        ticket_id = await self._call_kw("helpdesk.ticket.base", "create", [odoo_vals])
        ticket = await self._call_kw(
            "helpdesk.ticket.base", "read",
            [[ticket_id]],
            {"fields": ["name"]},
        )
        return {
            "success": True,
            "ticket_name": ticket[0]["name"],
            "ticket_id": ticket_id,
        }

    async def get_tickets_by_creator(self, user_id: int) -> list:
        """
        Return open tickets created by or for the given user.

        Filters out closed/resolved stages (``stage_id.is_close=False``) so that
        ``_fetch_creator_context`` only injects active tickets into the system prompt.
        Consistent with :meth:`get_tickets_by_assignee` which has the same filter.

        Args:
            user_id: Odoo res.users ID.

        Returns:
            list[dict]: Ticket records.
        """
        return await self._call_kw(
            "helpdesk.ticket.base", "search_read",
            [[["stage_id.is_close", "=", False],
              "|",
              ["creado_por", "=", user_id],
              ["usuario_solicitante_id", "=", user_id]]],
            {"fields": [
                "name", "asunto", "stage_id", "urgency_id",
                "ticket_type_id", "fecha_creacion", "partner_id",
            ]},
        )

    async def get_tickets_by_assignee(self, user_id: int) -> list:
        """
        Return tickets currently assigned to the given agent.

        Args:
            user_id: Odoo res.users ID of the assignee.

        Returns:
            list[dict]: Ticket records.
        """
        return await self._call_kw(
            "helpdesk.ticket.base", "search_read",
            [[["asignado_a", "=", user_id], ["stage_id.is_close", "=", False]]],
            {"fields": [
                "name", "asunto", "stage_id", "urgency_id", "priority_id",
                "ticket_type_id", "partner_id", "fecha_creacion",
            ]},
        )

    async def get_ticket_detail(self, ticket_id: int, user_id: int, role: str) -> dict:
        """
        Return full ticket details.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            user_id: Caller's user ID (for authorization checks — not enforced here).
            role: Caller's role (``"creador"``, ``"resueltor"``, ``"supervisor"``).

        Returns:
            dict: Ticket record or ``{"error": str}``.
        """
        tickets = await self._call_kw(
            "helpdesk.ticket.base", "read",
            [[ticket_id]],
            {"fields": [
                "name", "asunto", "descripcion", "causa_raiz", "motivo_resolucion",
                "stage_id", "ticket_type_id", "category_id", "subcategory_id", "element_id",
                "priority_id", "urgency_id", "impact_id",
                "partner_id", "asignado_a", "agent_group_id",
                "sla_id", "deadline_date", "sla_status", "is_about_to_expire",
                "fecha_creacion", "fecha_cierre", "ultima_modificacion",
                "approval_status",  # Fix: ITS_Helpdesk_custom — pending/approved/rejected
            ]},
        )
        if not tickets:
            return {"error": f"Ticket {ticket_id} not found"}
        return tickets[0]

    async def resolve_ticket(
        self,
        ticket_id: int,
        motivo_resolucion: str,
        causa_raiz: str,
        user_id: int,
    ) -> dict:
        """
        Resolve a ticket: sets resolution fields AND moves to the resolve stage.

        The stage change is mandatory — Odoo does not auto-transition.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            motivo_resolucion: Resolution text (min 10 chars enforced by Odoo).
            causa_raiz: Root cause analysis text.
            user_id: Resolver's user ID.

        Returns:
            dict: ``{"success": True, "ticket_id": int}`` or error dict.
        """
        resolve_stage_id = await self._get_resolve_stage_id()

        await self._call_kw(
            "helpdesk.ticket.base", "write",
            [[ticket_id], {
                "motivo_resolucion": self._text_to_html(motivo_resolucion),
                "causa_raiz": self._text_to_html(causa_raiz),
                "stage_id": resolve_stage_id,
            }],
        )
        return {"success": True, "ticket_id": ticket_id}

    async def update_ticket(self, ticket_id: int, fields: dict, user_id: int) -> dict:
        """
        Update arbitrary ticket fields using Odoo technical field names.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            fields: Dict of Odoo field names to values.
            user_id: Caller's user ID (for audit trail).

        Returns:
            dict: ``{"success": True, "ticket_id": int}``.
        """
        await self._call_kw("helpdesk.ticket.base", "write", [[ticket_id], fields])
        return {"success": True, "ticket_id": ticket_id}

    async def get_all_tickets(self, filters: dict | None = None) -> list:
        """
        Return open/active tickets by default (not closed/resolved).

        To include closed tickets, pass filters that explicitly override the
        default ``stage_id.is_close = False`` filter.

        Args:
            filters: Optional dict supporting Odoo field names.

        Returns:
            list[dict]: At most 50 tickets.
        """
        domain: list = []
        # Default: only open tickets (stage not closed/resolved).
        if not filters or "stage_id.is_close" not in filters:
            domain.append(["stage_id.is_close", "=", False])
        if filters:
            for key, value in filters.items():
                domain.append([key, "=", value])

        return await self._call_kw(
            "helpdesk.ticket.base", "search_read",
            [domain],
            {"fields": [
                "name", "asunto", "stage_id", "urgency_id", "priority_id",
                "ticket_type_id", "partner_id", "asignado_a",
                "agent_group_id", "fecha_creacion",
                "sla_status", "deadline_date", "is_about_to_expire",
                "approval_status",
            ], "limit": 50},
        )

    async def assign_ticket(
        self,
        ticket_id: int,
        assignee_id: int,
        agent_group_id: int,
        user_id: int,
    ) -> dict:
        """
        Assign a ticket to an agent and agent group.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            assignee_id: Odoo res.users ID of the assignee.
            agent_group_id: Odoo helpdesk.agent.group ID (``0`` to skip).
            user_id: Supervisor's user ID.

        Returns:
            dict: ``{"success": True, "ticket_id": int}``.
        """
        vals: dict[str, Any] = {"asignado_a": assignee_id}
        if agent_group_id:
            vals["agent_group_id"] = agent_group_id

        await self._call_kw("helpdesk.ticket.base", "write", [[ticket_id], vals])
        return {"success": True, "ticket_id": ticket_id}

    async def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """
        Reopen a resolved/closed ticket by moving it back to the start stage.

        Appends the reopen reason to ``motivo_resolucion`` preserving the original
        resolution text for audit trail.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            reason: Reopen reason (stored for audit trail).
            user_id: Supervisor's user ID.

        Returns:
            dict: ``{"success": True, "ticket_id": int}``.
        """
        start_stage_id = await self._get_start_stage_id()

        # Read current value before overwriting to preserve history
        current = await self._call_kw(
            "helpdesk.ticket.base", "read",
            [[ticket_id]],
            {"fields": ["motivo_resolucion"]},
        )
        original = current[0].get("motivo_resolucion", "") if current else ""
        separator = "<hr/><p><strong>--- Resolución anterior ---</strong></p>" if original else ""
        new_motivo = (
            f"<p><strong>Reabierto:</strong> {_html.escape(reason)}</p>"
            f"{separator}{original}"
        )

        await self._call_kw(
            "helpdesk.ticket.base", "write",
            [[ticket_id], {
                "stage_id": start_stage_id,
                "motivo_resolucion": new_motivo,
                "fecha_cierre": False,
            }],
        )
        return {"success": True, "ticket_id": ticket_id}

    async def delete_ticket(self, ticket_id: int, user_id: int) -> dict:
        """
        Permanently delete a ticket.

        SECURITY: Implemented but ``delete_ticket`` tool is excluded from all
        role tool lists. See ``tools/ticket_tools.py`` for the exclusion comment.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            user_id: Supervisor's user ID.

        Returns:
            dict: ``{"success": True}``.
        """
        await self._call_kw("helpdesk.ticket.base", "unlink", [[ticket_id]])
        return {"success": True}

    async def approve_ticket(self, ticket_id: int, user_id: int) -> dict:
        """
        Approve a pending ticket in Odoo.

        Sets ``approval_status='approved'`` and ``approval_date`` to now.
        Both fields are from ITS_Helpdesk_custom — ``approval_date`` is a
        Datetime field that Odoo accepts in ``'%Y-%m-%d %H:%M:%S'`` format.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            user_id: Supervisor's user ID.

        Returns:
            dict: ``{"success": True, "ticket_id": int}``.
        """
        await self._call_kw(
            "helpdesk.ticket.base", "write",
            [[ticket_id], {
                "approval_status": "approved",
                "approval_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }],
        )
        return {"success": True, "ticket_id": ticket_id}

    async def reject_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """
        Reject a pending ticket in Odoo.

        Sets ``approval_status='rejected'`` and stores the reason in
        ``approval_comment``. NOTE: Odoo uses ``approval_comment`` (Text field)
        — NOT ``rejection_reason``, which does not exist in ITS_Helpdesk_custom.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            reason: Rejection reason.
            user_id: Supervisor's user ID.

        Returns:
            dict: ``{"success": True, "ticket_id": int}``.
        """
        await self._call_kw(
            "helpdesk.ticket.base", "write",
            [[ticket_id], {
                "approval_status": "rejected",
                "approval_comment": self._text_to_html(reason),
            }],
        )
        return {"success": True, "ticket_id": ticket_id}

    # ── Catalog queries ──────────────────────────────────────────────────────

    async def get_ticket_types(self) -> list:
        """Return available ticket types ordered by sequence."""
        return await self._call_kw(
            "helpdesk.ticket.type", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name"], "order": "sequence"},
        )

    async def get_categories(self, parent_id: int | None = None) -> list:
        """
        Return categories from the 3-level hierarchy.

        Args:
            parent_id: If ``None``, returns Level 1 categories. Otherwise returns
                       children of that category (Level 2 or Level 3).

        Returns:
            list[dict]: Ordered by sequence.
        """
        if parent_id is None:
            domain = [["level", "=", 1], ["active", "=", True]]
        else:
            domain = [["parent_id", "=", parent_id], ["active", "=", True]]

        return await self._call_kw(
            "helpdesk.category", "search_read",
            [domain],
            {"fields": ["id", "name", "full_name", "level", "parent_id"], "order": "sequence"},
        )

    async def get_urgency_levels(self) -> list:
        """Return urgency catalog ordered by sequence."""
        return await self._call_kw(
            "helpdesk.ticket.urgency", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name"], "order": "sequence"},
        )

    async def get_impact_levels(self) -> list:
        """Return impact catalog ordered by sequence."""
        return await self._call_kw(
            "helpdesk.ticket.impact", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name"], "order": "sequence"},
        )

    async def get_priority_levels(self) -> list:
        """Return priority catalog ordered by sequence."""
        return await self._call_kw(
            "helpdesk.ticket.priority", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name"], "order": "sequence"},
        )

    async def get_stages(self) -> list:
        """
        Return all active stages with their workflow flags.

        The agent uses ``is_resolve``, ``is_start``, ``is_close``, ``is_pause``
        to make decisions.

        Returns:
            list[dict]: Ordered by sequence.
        """
        return await self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name", "is_start", "is_resolve", "is_close", "is_pause"],
             "order": "sequence"},
        )

    async def get_agent_groups(self) -> list:
        """Return all available agent groups."""
        return await self._call_kw(
            "helpdesk.agent.group", "search_read",
            [[]],
            {"fields": ["id", "name"]},
        )

    async def get_resolvers(self) -> list:
        """
        Return users that belong to the helpdesk agent or manager group.

        Filters by group XML ID (resistant to name changes across Odoo versions).

        Returns:
            list[dict]: Each item has ``id``, ``name``, ``login``.
        """
        # Use group IDs directly since full_name varies by category/localization.
        # group_helpdesk_agent  = id 334, group_helpdesk_manager = id 333
        return await self._call_kw(
            "res.users", "search_read",
            [[
                ["share", "=", False],
                ["active", "=", True],
                "|",
                ["groups_id", "in", [334]],   # Helpdesk Agente
                ["groups_id", "in", [333]],   # Helpdesk Gestor
            ]],
            {"fields": ["id", "name", "login"]},
        )

    async def get_resolved_tickets(self) -> list:
        """
        Return resolved tickets for RAG seeding.

        Fetches tickets in stages with ``is_resolve=True`` or ``is_close=True``.

        Returns:
            list[dict]: At most 500 tickets with at minimum:
                ticket_id, ticket_name, ticket_type, category,
                description, motivo_resolucion, causa_raiz.
        """
        raw = await self._call_kw(
            "helpdesk.ticket.base", "search_read",
            [["|",
               ["stage_id.is_resolve", "=", True],
               ["stage_id.is_close", "=", True]]],
            {"fields": [
                "id", "name", "ticket_type_id", "category_id",
                "descripcion", "motivo_resolucion", "causa_raiz",
            ], "limit": 500},
        )

        result: list[dict] = []
        for t in raw:
            if not t.get("motivo_resolucion"):
                continue  # Skip tickets without resolution text — not useful for RAG

            result.append({
                "ticket_id": t["id"],
                "ticket_name": t.get("name", ""),
                "ticket_type": t["ticket_type_id"][1] if isinstance(t.get("ticket_type_id"), list) else "",
                "category": t["category_id"][1] if isinstance(t.get("category_id"), list) else "",
                "description": t.get("descripcion", ""),
                "motivo_resolucion": t.get("motivo_resolucion", ""),
                "causa_raiz": t.get("causa_raiz", ""),
            })
        return result

    # ── Operation metrics ─────────────────────────────────────────────────────

    async def get_operation_metrics(self) -> dict:
        """
        Compute operational KPIs from the helpdesk database.

        The 5 Odoo calls (MTTN, MTTR, by_category, by_urgency, approval_rate,
        reopen) are run in parallel via ``asyncio.gather()`` for ~3x speedup
        vs sequential calls.

        Metrics:
            avg_time_to_assign_hours  — mean (fecha_creacion → approval_date)
            avg_time_to_resolve_hours — mean (fecha_creacion → fecha_cierre)
            tickets_by_category       — count grouped by category (top 10)
            tickets_by_urgency        — count grouped by urgency
            approval_rate             — count by approval_status
            reopen_rate               — ratio of reopened vs total resolved

        Returns:
            dict: Operational KPIs. On partial failure, includes ``_error`` field
            with the error message and returns the partial results.
        """
        result: dict = {
            "avg_time_to_assign_hours": 0.0,
            "avg_time_to_resolve_hours": 0.0,
            "tickets_by_category": [],
            "tickets_by_urgency": [],
            "approval_rate": {"approved": 0, "rejected": 0, "pending": 0},
            "reopen_rate": 0.0,
        }

        try:
            # Run all 5 Odoo queries in parallel — they are independent.
            # asyncio.gather() returns results in the same order as the coroutines.
            (approved, closed, by_cat, by_urg, by_appr, reopened, total_resolved) = (
                await asyncio.gather(
                    self._call_kw(
                        "helpdesk.ticket.base", "search_read",
                        [[["approval_date", "!=", False]]],
                        {"fields": ["fecha_creacion", "approval_date"], "limit": 500},
                    ),
                    self._call_kw(
                        "helpdesk.ticket.base", "search_read",
                        [[["fecha_cierre", "!=", False]]],
                        {"fields": ["fecha_creacion", "fecha_cierre"], "limit": 500},
                    ),
                    self._call_kw(
                        "helpdesk.ticket.base", "read_group",
                        [[]],
                        {
                            "fields": ["category_id"],
                            "groupby": ["category_id"],
                            "limit": 10,
                        },
                    ),
                    self._call_kw(
                        "helpdesk.ticket.base", "read_group",
                        [[]],
                        {
                            "fields": ["urgency_id"],
                            "groupby": ["urgency_id"],
                        },
                    ),
                    self._call_kw(
                        "helpdesk.ticket.base", "read_group",
                        [[]],
                        {
                            "fields": ["approval_status"],
                            "groupby": ["approval_status"],
                        },
                    ),
                    self._call_kw(
                        "helpdesk.ticket.base", "search_count",
                        [[["motivo_resolucion", "ilike", "Reabierto:"]]],
                    ),
                    self._call_kw(
                        "helpdesk.ticket.base", "search_count",
                        [[["motivo_resolucion", "!=", False]]],
                    ),
                    return_exceptions=True,
                )
            )

            # ── MTTN (Mean Time To Notify/assign) ──────────────────────────
            if not isinstance(approved, Exception) and approved:
                result["avg_time_to_assign_hours"] = self._avg_hours(
                    [t.get("fecha_creacion", "") for t in approved],
                    [t.get("approval_date", "") for t in approved],
                )
            elif isinstance(approved, Exception):
                logger.warning("MTTN query failed: %s", approved)

            # ── MTTR (Mean Time To Resolve) ────────────────────────────────
            if not isinstance(closed, Exception) and closed:
                result["avg_time_to_resolve_hours"] = self._avg_hours(
                    [t.get("fecha_creacion", "") for t in closed],
                    [t.get("fecha_cierre", "") for t in closed],
                )
            elif isinstance(closed, Exception):
                logger.warning("MTTR query failed: %s", closed)

            # ── Distribution by category (level 1 only) ─────────────────────
            if not isinstance(by_cat, Exception):
                result["tickets_by_category"] = [
                    {
                        "category": (g["category_id"][1] if isinstance(g.get("category_id"), list) and len(g["category_id"]) >= 2 else "Sin categoría"),
                        "count": g["category_id_count"],
                    }
                    for g in by_cat
                    if g.get("category_id")
                ]
            else:
                logger.warning("by_category query failed: %s", by_cat)

            # ── Distribution by urgency ────────────────────────────────────
            if not isinstance(by_urg, Exception):
                result["tickets_by_urgency"] = [
                    {
                        "urgency": (g["urgency_id"][1] if isinstance(g.get("urgency_id"), list) and len(g["urgency_id"]) >= 2 else "Sin urgencia"),
                        "count": g["urgency_id_count"],
                    }
                    for g in by_urg
                    if g.get("urgency_id")
                ]
            else:
                logger.warning("by_urgency query failed: %s", by_urg)

            # ── Approval rate ──────────────────────────────────────────────
            if not isinstance(by_appr, Exception):
                appr_counts = {
                    g["approval_status"]: g["approval_status_count"]
                    for g in by_appr
                    if g.get("approval_status")
                }
                result["approval_rate"] = {
                    "approved": appr_counts.get("approved", 0),
                    "rejected": appr_counts.get("rejected", 0),
                    "pending": appr_counts.get("pending", 0),
                }
            else:
                logger.warning("by_approval query failed: %s", by_appr)

            # ── Reopen rate ────────────────────────────────────────────────
            if not isinstance(reopened, Exception) and not isinstance(total_resolved, Exception):
                if total_resolved > 0:
                    result["reopen_rate"] = round(reopened / total_resolved, 4)
            else:
                logger.warning("reopen query failed: %s / %s", reopened, total_resolved)

        except Exception as exc:
            # Don't fail the whole metrics endpoint — return what we have
            # plus the error message in a separate field for debugging.
            logger.exception("get_operation_metrics partial failure")
            result["_error"] = str(exc)

        return result

    @staticmethod
    def _hours_between(start_str: str, end_str: str) -> float:
        """
        Compute hours between two Odoo datetime strings.

        Odoo returns datetimes as ``"YYYY-MM-DD HH:MM:SS"`` — the format is
        fixed, so ``strptime`` is safe.

        Args:
            start_str: Start datetime string.
            end_str: End datetime string.

        Returns:
            float: Hours between start and end, or 0.0 on parse error.
        """
        if not start_str or not end_str:
            return 0.0
        try:
            fmt = "%Y-%m-%d %H:%M:%S"
            start = datetime.strptime(start_str[:19], fmt)
            end = datetime.strptime(end_str[:19], fmt)
            return (end - start).total_seconds() / 3600.0
        except (ValueError, TypeError):
            return 0.0

    @staticmethod
    def _avg_hours(starts: list, ends: list) -> float:
        """
        Compute mean hours between parallel lists of start/end datetimes.

        Args:
            starts: List of start datetime strings.
            ends: List of end datetime strings.

        Returns:
            float: Mean hours, or 0.0 if no valid pairs.
        """
        pairs = [(s, e) for s, e in zip(starts, ends) if s and e]
        if not pairs:
            return 0.0
        total = sum(OdooAdapter._hours_between(s, e) for s, e in pairs)
        return round(total / len(pairs), 2)
