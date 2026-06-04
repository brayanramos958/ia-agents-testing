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

ASYNC: This adapter uses httpx.AsyncClient for non-blocking JSON-RPC calls.
       All methods are async and must be awaited.
       The FastAPI/LangGraph event loop is NOT blocked by Odoo calls.
      the FastAPI/LangGraph event loop. No async rewrite is needed.
"""

import html as _html
import logging
import httpx
from ports.ticket_port import ITicketPort
from config.settings import settings

_log = logging.getLogger(__name__)


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

        # Async HTTP client — reused across all requests
        self._client = httpx.AsyncClient(timeout=30.0)

    # ── HTML helper ──────────────────────────────────────────────────────────

    def _strip_html(self, text: str) -> str:
        """Convierte HTML a texto plano para validaciones de longitud real.

        Replica el comportamiento de Odoo tools.html2plaintext() para validar
        que el contenido real (sin etiquetas HTML) cumpla mínimos.
        """
        import re as _re
        if not text:
            return ""
        clean = _re.sub(r"<[^>]+>", "", str(text))
        return " ".join(clean.split())

    def _text_to_html(self, text: str) -> str:
        """Convierte texto plano a HTML para fields.Html de Odoo.

        Odoo almacena descripcion, causa_raiz y motivo_resolucion como
        fields.Html. Enviar texto plano rompe el renderizado en el chatter
        y los wizards de resolución validan mínimo 10 caracteres reales.
        """
        if not text:
            return ""
        escaped = _html.escape(str(text))
        paragraphs = escaped.split("\n\n")
        parts = []
        for p in paragraphs:
            p = p.replace("\n", "<br/>").strip()
            if p:
                parts.append(f"<p>{p}</p>")
        return "".join(parts) if parts else f"<p>{escaped}</p>"

    # ── Authentication ────────────────────────────────────────────────────────

    async def _authenticate(self) -> None:
        """
        Obtains a session cookie from Odoo.
        Called lazily on first request and on session expiry.
        """
        resp = await self._client.post(
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

        # ── GAP 3: Verify the Odoo user has sufficient permissions ────────────
        await self._verify_permissions()

    async def _verify_permissions(self) -> None:
        """
        Verifies the authenticated user has Admin or Gestor group membership.

        Without these groups, the adapter can still create/read/update tickets
        via JSON-RPC ORM methods, but record rules may restrict visibility:
        - Agent (group_helpdesk_agent): only sees tickets assigned to them/their group
        - Client (group_helpdesk_client): only sees their own tickets

        We log a warning if the user lacks supervisor-level groups so operators
        are aware that get_all_tickets and some supervisor ops may return
        incomplete results.
        """
        try:
            is_admin = await self._call_kw(
                "res.users", "has_group",
                ["ITS_Helpdesk_base.group_helpdesk_admin"],
            )
        except Exception:
            _log.warning("Could not verify admin group — assuming limited permissions.")
            return

        try:
            is_manager = await self._call_kw(
                "res.users", "has_group",
                ["ITS_Helpdesk_base.group_helpdesk_manager"],
            )
        except Exception:
            _log.warning("Could not verify manager group — assuming limited permissions.")
            return

        if not is_admin and not is_manager:
            _log.warning(
                "Odoo user (uid=%s) is neither Admin nor Manager. "
                "Record rules may limit ticket visibility. "
                "get_all_tickets() and supervisor tools may return incomplete results.",
                self._uid,
            )
        else:
            role = "Admin" if is_admin else "Manager"
            _log.info("Odoo user has %s group — full ticket visibility.", role)

    async def _ensure_session(self) -> None:
        """Authenticates if no session exists."""
        if not self._session_id or not self._uid:
            await self._authenticate()

    # ── JSON-RPC core ─────────────────────────────────────────────────────────

    async def _call_kw(self, model: str, method: str, args: list, kwargs: dict = None) -> any:
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
        await self._ensure_session()

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

        resp = await self._client.post(
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
                return await self._call_kw(model, method, args, kwargs)

            raise RuntimeError(f"Odoo error [{model}.{method}]: {msg}")

        return body["result"]

    # ── Stage helpers ─────────────────────────────────────────────────────────

    async def _get_resolve_stage_id(self) -> int:
        """Returns the ID of the stage with is_resolve=True. Cached after first call.
        
        Fallback strategy (production seed data has no is_resolve=True):
        1. Stage with is_resolve=True
        2. Stage with name 'Resuelto' or 'Cerrado'
        3. Stage with highest sequence (assumed to be terminal)
        """
        if self._resolve_stage_id:
            return self._resolve_stage_id

        # Primary lookup: stage with is_resolve=True
        stages = await self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[["is_resolve", "=", True], ["active", "=", True]]],
            {"fields": ["id", "name"], "limit": 1},
        )
        if stages:
            self._resolve_stage_id = stages[0]["id"]
            _log.debug("resolve stage: is_resolve=True → %s", stages[0]["name"])
            return self._resolve_stage_id

        # Fallback 1: search by name "Resuelto" or "Cerrado"
        fallback = await self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[["active", "=", True], "|",
              ["name", "ilike", "Resuelto"],
              ["name", "ilike", "Cerrado"]]],
            {"fields": ["id", "name", "sequence"], "order": "sequence desc", "limit": 1},
        )
        if fallback:
            self._resolve_stage_id = fallback[0]["id"]
            _log.debug("resolve stage: name fallback → %s", fallback[0]["name"])
            return self._resolve_stage_id

        # Fallback 2: stage with highest sequence (terminal stage)
        stages_all = await self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name", "sequence"], "order": "sequence desc", "limit": 1},
        )
        if stages_all:
            self._resolve_stage_id = stages_all[0]["id"]
            _log.debug("resolve stage: sequence fallback → %s", stages_all[0]["name"])
            return self._resolve_stage_id

        raise RuntimeError(
            "No existe ningún estado con 'is_resolve=True' ni llamado 'Resuelto'/'Cerrado' en Odoo. "
            "Por favor configura un estado de Resolución en el módulo Helpdesk."
        )

    async def _get_start_stage_id(self) -> int:
        """Returns the ID of the stage with is_start=True. Cached after first call."""
        if self._start_stage_id:
            return self._start_stage_id

        stages = await self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[["is_start", "=", True], ["active", "=", True]]],
            {"fields": ["id", "name"], "limit": 1},
        )
        if stages:
            self._start_stage_id = stages[0]["id"]
            return self._start_stage_id

        # Fallback: search by name "Abierto" (production may have no is_start=True)
        fallback = await self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[["name", "ilike", "Abierto"], ["active", "=", True]]],
            {"fields": ["id", "name"], "limit": 1},
        )
        if fallback:
            self._start_stage_id = fallback[0]["id"]
            return self._start_stage_id

        # Ultimate fallback: stage with lowest sequence (should be the start stage)
        stages_all = await self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name", "sequence"], "order": "sequence asc", "limit": 1},
        )
        if stages_all:
            self._start_stage_id = stages_all[0]["id"]
            return self._start_stage_id

        raise RuntimeError(
            "No existe ningún estado con 'is_start=True' ni llamado 'Abierto' en Odoo. "
            "Por favor configura un estado de Inicio en el módulo Helpdesk."
        )

    # ── Ticket operations ────────────────────────────────────────────────────

    async def create_ticket(self, payload: dict, user_id: int) -> dict:
        """
        Creates a ticket in Odoo.

        Resolves partner_id from user_id automatically (required field in Odoo).
        Sets usuario_solicitante_id explicitly (onchange doesn't fire via JSON-RPC).
        Sends system_equipment as a standalone Char field (ITS_Helpdesk_custom).
        Wraps text fields (descripcion) as HTML for fields.Html compatibility.
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
        odoo_vals = {
            "asunto":                 payload["asunto"],
            "descripcion":            self._text_to_html(payload.get("descripcion", "")),
            "ticket_type_id":         payload["ticket_type_id"],
            "category_id":            payload["category_id"],
            "urgency_id":             payload["urgency_id"],
            "impact_id":              payload["impact_id"],
            "priority_id":            payload["priority_id"],
            "partner_id":             partner_id,
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
        # FASE 1: Set inicio_falla at ticket creation (matches resolve wizard behavior)
        from datetime import datetime
        odoo_vals["inicio_falla"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        # FASE 3: Origin and solicitud fields
        if payload.get("origin_id"):
            odoo_vals["origin_id"] = payload["origin_id"]
        if payload.get("affected_user_name"):
            odoo_vals["affected_user_name"] = payload["affected_user_name"]
        if payload.get("contact_info"):
            odoo_vals["contact_info"] = payload["contact_info"]
        if payload.get("anydesk_id"):
            odoo_vals["anydesk_id"] = payload["anydesk_id"]
        if payload.get("availability_datetime"):
            odoo_vals["availability_datetime"] = payload["availability_datetime"]
        if payload.get("requester_type"):
            odoo_vals["requester_type"] = payload["requester_type"]

        # 4. Create and return
        ticket_id = await self._call_kw("helpdesk.ticket.base", "create", [odoo_vals])
        ticket = await self._call_kw(
            "helpdesk.ticket.base", "read",
            [[ticket_id]],
            {"fields": ["name"]},
        )
        return {
            "success":     True,
            "ticket_name": ticket[0]["name"],
            "ticket_id":   ticket_id,
        }

    async def get_tickets_by_creator(self, user_id: int) -> list:
        """
        Returns open tickets created by or for the given user.

        Filters out closed/resolved stages (stage_id.is_close=False) so that
        _fetch_creator_context only injects active tickets into the system prompt.
        Consistent with get_tickets_by_assignee which has the same filter.

        FASE 4: includes category_id and ticket_type_id for smarter duplicate
        detection in _fetch_creator_context (UX-4).
        """
        return await self._call_kw(
            "helpdesk.ticket.base", "search_read",
            [[["stage_id.is_close", "=", False],
              "|",
              ["creado_por", "=", user_id],
              ["usuario_solicitante_id", "=", user_id]]],
            {"fields": [
                "name", "asunto", "stage_id", "urgency_id",
                "ticket_type_id", "category_id", "fecha_creacion",
            ]},
        )

    async def get_tickets_by_assignee(self, user_id: int) -> list:
        """Returns tickets currently assigned to the given agent.
        
        FASE 5: includes SLA and approval fields for resolver context prefetch.
        """
        return await self._call_kw(
            "helpdesk.ticket.base", "search_read",
            [[["asignado_a", "=", user_id], ["stage_id.is_close", "=", False]]],
            {"fields": [
                "name", "asunto", "stage_id", "urgency_id", "priority_id",
                "ticket_type_id", "category_id", "fecha_creacion",
                "sla_status", "deadline_date", "is_about_to_expire",
                "approval_status", "origin_id",
                "agent_group_id",  # needed for resolver dashboard team context
            ]},
        )

    async def get_ticket_detail(self, ticket_id: int, user_id: int, role: str) -> dict:
        """Returns full ticket details with SLA, approval, KPI and satisfaction fields.
        
        HTML fields (descripcion, causa_raiz, motivo_resolucion) are stripped to plain text
        so the LLM receives clean, readable content without HTML tags.
        """
        tickets = await self._call_kw(
            "helpdesk.ticket.base", "read",
            [[ticket_id]],
            {"fields": [
                "name", "asunto", "descripcion", "causa_raiz", "motivo_resolucion",
                "stage_id", "ticket_type_id", "category_id", "subcategory_id", "element_id",
                "priority_id", "urgency_id", "impact_id",
                "partner_id", "asignado_a", "agent_group_id",
                "sla_id", "deadline_date", "deadline_n1_date", "deadline_n2_date",
                "sla_status", "is_about_to_expire", "is_paused",
                "fecha_creacion", "fecha_cierre", "ultima_modificacion",
                "inicio_falla", "fin_falla", "fecha_asignacion",
                "approval_status", "approval_date", "approval_comment",
                "approval_line_ids",  # FASE 2: multi-approver lines
                "satisfaction_rating", "satisfaction_comment", "satisfaction_date",
                "resolucion_nivel",  # FASE 4: N1/N2 resolution level
                "sla_group_n1_id", "sla_group_n2_id",
                "ticket_parent_id", "ticket_child_ids",  # Parent-child hierarchy
            ]},
        )
        if not tickets:
            return {"error": f"Ticket {ticket_id} not found"}
        
        ticket = tickets[0]
        # Strip HTML from text fields — LLM doesn't need <p> and <br> tags
        html_fields = ["descripcion", "causa_raiz", "motivo_resolucion"]
        for field in html_fields:
            if ticket.get(field):
                ticket[field] = self._strip_html(ticket[field])
        
        # Resolve parent-child hierarchy to readable names for the LLM
        if ticket.get("ticket_parent_id"):
            parent = ticket["ticket_parent_id"]
            if isinstance(parent, (list, tuple)) and len(parent) >= 2:
                ticket["parent_ticket_name"] = parent[1]
        
        if ticket.get("ticket_child_ids"):
            children = ticket["ticket_child_ids"]
            if isinstance(children, list) and len(children) > 0:
                child_info = await self._call_kw(
                    "helpdesk.ticket.base", "search_read",
                    [[["id", "in", children]]],
                    {"fields": ["id", "name", "asunto", "stage_id"]},
                )
                ticket["child_tickets"] = []
                for c in child_info:
                    ticket["child_tickets"].append({
                        "ticket_id": c["id"],
                        "name": c.get("name", ""),
                        "asunto": c.get("asunto", ""),
                        "stage": c["stage_id"][1] if isinstance(c.get("stage_id"), list) else "",
                    })
        
        return ticket

    async def resolve_ticket(self, ticket_id: int, motivo_resolucion: str,
                       causa_raiz: str, user_id: int) -> dict:
        """
        Resolves a ticket: sets resolution fields AND moves to the resolve stage.
        The stage change is mandatory — Odoo does not auto-transition.
        fin_falla, last_reply_by, last_staff_reply_date mirror the resolve wizard behavior.
        
        FASE 1: Sets inicio_falla if not already set (required for production MTTN tracking).
        FASE 4: resolucion_nivel is auto-computed by Odoo on stage change.
        GAP 1: Validates causa_raiz and motivo_resolucion have >=10 real characters
               (matches Odoo resolve/close wizard behavior — tools.html2plaintext).
        """
        # ── GAP 1: Validate minimum content (matches Odoo resolve wizard) ─────
        plain_causa = self._strip_html(causa_raiz)
        plain_motivo = self._strip_html(motivo_resolucion)

        if len(plain_causa) < 10:
            raise ValueError(
                f"La Causa Raíz debe tener al menos 10 caracteres reales "
                f"(sin contar etiquetas HTML). "
                f"Texto actual: {len(plain_causa)} caracter(es). "
                f"Por favor elabora una explicación más detallada de qué causó el problema."
            )
        if len(plain_motivo) < 10:
            raise ValueError(
                f"El Motivo de Resolución debe tener al menos 10 caracteres reales "
                f"(sin contar etiquetas HTML). "
                f"Texto actual: {len(plain_motivo)} caracter(es). "
                f"Por favor describe con más detalle cómo se resolvió el ticket."
            )

        from datetime import datetime
        resolve_stage_id = await self._get_resolve_stage_id()
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Read current inicio_falla — set if not already present
        current = await self._call_kw(
            "helpdesk.ticket.base", "read",
            [[ticket_id]],
            {"fields": ["inicio_falla"]},
        )
        update_vals = {
            "motivo_resolucion":     self._text_to_html(motivo_resolucion),
            "causa_raiz":            self._text_to_html(causa_raiz),
            "stage_id":              resolve_stage_id,
            "fin_falla":             now,
            "last_reply_by":         "staff",
            "last_staff_reply_date": now,
        }
        if current and not current[0].get("inicio_falla"):
            update_vals["inicio_falla"] = now

        await self._call_kw(
            "helpdesk.ticket.base", "write",
            [[ticket_id], update_vals],
        )
        return {"success": True, "ticket_id": ticket_id}

    async def update_ticket(self, ticket_id: int, fields: dict, user_id: int) -> dict:
        """Updates arbitrary ticket fields using Odoo technical field names.

        HTML fields (descripcion, causa_raiz, motivo_resolucion) are automatically
        wrapped with _text_to_html() before sending to Odoo to prevent rendering
        issues in the Chatter and resolution wizards.
        """
        # Wrap HTML fields if present in the update payload
        html_fields = ["descripcion", "causa_raiz", "motivo_resolucion"]
        for field in html_fields:
            if field in fields:
                fields[field] = self._text_to_html(str(fields[field]))
        await self._call_kw("helpdesk.ticket.base", "write", [[ticket_id], fields])
        return {"success": True, "ticket_id": ticket_id}

    async def add_note(self, ticket_id: int, note: str, user_id: int) -> dict:
        """
        Adds an internal note to a ticket via Odoo's message_post.
        
        Uses subtype_id=1 ('Note') to create an internal note visible to
        agents/supervisors but not end users (portal/customers).

        The note is stored as a mail.message linked to the ticket and
        appears in the Odoo Chatter under 'Internal Notes'.
        """
        try:
            message_id = await self._call_kw(
                "helpdesk.ticket.base", "message_post",
                [[ticket_id]],
                {
                    "body": note,
                    "message_type": "comment",
                    "subtype_id": 1,  # mt_note — internal note, not visible to portal
                },
            )
            return {"success": True, "message_id": message_id}
        except Exception as exc:
            _log.error("add_note failed: %s", exc)
            return {"success": False, "error": str(exc)}

    async def get_all_tickets(self, filters: dict = None, limit: int = 15, offset: int = 0) -> list:
        """Returns paginated tickets ordered by creation date (most recent first)."""
        domain = []
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
                "sla_status", "deadline_date", "deadline_n1_date", "deadline_n2_date",
                "is_about_to_expire", "is_paused",
                "approval_status", "fecha_asignacion",
            ], "order": "fecha_creacion desc", "limit": limit, "offset": offset},
        )

    async def _is_helpdesk_user(self, user_id: int) -> bool:
        """Verifica que el usuario pertenezca a un grupo de helpdesk.
        
        Un usuario válido para asignación debe tener al menos uno de:
        - group_helpdesk_agent (Agente)
        - group_helpdesk_manager (Gestor)  
        - group_helpdesk_admin (Admin)
        
        Esto evita asignar tickets a usuarios sin permisos de helpdesk
        (ej: usuarios de RRHH, finanzas, o externos).
        """
        groups = await self._call_kw(
            "res.users", "search_read",
            [[["id", "=", user_id]]],
            {"fields": ["groups_id"]},
        )
        if not groups:
            return False
        
        valid_names = {
            "Helpdesk Agente",
            "Helpdesk Gestor", 
            "Helpdesk Admin",
            "Helpdesk Solicitante BCC Solo Lectura",
            "Helpdesk Solicitante",
        }
        
        user_group_ids = groups[0].get("groups_id", [])
        if not user_group_ids:
            return False
        
        # Verificar que al menos un grupo del usuario esté en los válidos
        all_groups = await self._call_kw(
            "res.groups", "search_read",
            [[["id", "in", user_group_ids], ["name", "in", list(valid_names)]]],
            {"fields": ["id", "name"]},
        )
        return len(all_groups) > 0

    async def assign_ticket(self, ticket_id: int, assignee_id: int,
                      agent_group_id: int, user_id: int) -> dict:
        """Assigns a ticket to an agent and agent group.
        
        FASE 1: Sets fecha_asignacion on first assignment (if not already set).
        This enables MTTN (Mean Time To Assign) tracking in production.
        BUG-FIX 2026-05-25: Valida que el asignado pertenezca a un grupo helpdesk.
        """
        # Validar que el asignado tenga permisos de helpdesk
        if not await self._is_helpdesk_user(assignee_id):
            return {
                "success": False,
                "error": f"El usuario {assignee_id} no pertenece a ningún grupo de helpdesk "
                         f"(Agente, Gestor o Admin). No se puede asignar el ticket."
            }
        
        vals = {"asignado_a": assignee_id}
        if agent_group_id:
            vals["agent_group_id"] = agent_group_id

        # Set fecha_asignacion on first assignment for MTTN tracking
        current = await self._call_kw(
            "helpdesk.ticket.base", "read",
            [[ticket_id]],
            {"fields": ["fecha_asignacion"]},
        )
        if current and not current[0].get("fecha_asignacion"):
            from datetime import datetime
            vals["fecha_asignacion"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        await self._call_kw("helpdesk.ticket.base", "write", [[ticket_id], vals])
        return {"success": True, "ticket_id": ticket_id}

    async def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """
        Reopens a resolved/closed ticket by moving it back to the start stage.
        Appends the reopen reason to motivo_resolucion preserving the original
        resolution text for audit trail.
        """
        start_stage_id = await self._get_start_stage_id()

        # Fix: leer el valor actual antes de sobrescribir para preservar el historial.
        # Sobrescribir motivo_resolucion borraba la resolución original — rompe audit trail.
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
                "stage_id":          start_stage_id,
                "motivo_resolucion": new_motivo,
                "fecha_cierre":      False,
            }],
        )
        return {"success": True, "ticket_id": ticket_id}

    async def delete_ticket(self, ticket_id: int, user_id: int) -> dict:
        # SECURITY: Implemented but delete_ticket tool is excluded from all role tool lists.
        await self._call_kw("helpdesk.ticket.base", "unlink", [[ticket_id]])
        return {"success": True}

    async def approve_ticket(self, ticket_id: int, user_id: int) -> dict:
        """
        Approves a pending ticket using the multi-approver line system (FASE 2).

        Production uses helpdesk.ticket.approval lines, NOT a simple approval_status field.
        1. Find first approval line for this user with status='pending'
        2. Update that line to 'approved' with current timestamp
        3. The custom model's write() auto-updates global approval_status from lines

        Fallback: if no pending line found for this user, falls back to legacy
        approval_status write (for migrated tickets that predate approval lines).
        """
        from datetime import datetime

        # Search for pending approval line for this user
        pending = await self._call_kw(
            "helpdesk.ticket.approval", "search_read",
            [[
                ["ticket_id", "=", ticket_id],
                ["approver_id", "=", user_id],
                ["status", "=", "pending"],
            ]],
            {"fields": ["id"], "limit": 1},
        )

        if pending:
            # Update the pending approval line — model custom propagates to global
            await self._call_kw(
                "helpdesk.ticket.approval", "write",
                [[pending[0]["id"]], {
                    "status": "approved",
                    "approval_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                }],
            )
        else:
            # Fallback: legacy approval_status write for tickets without lines
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
        Rejects a pending ticket using the multi-approver line system (FASE 2).

        Same flow as approve_ticket but sets status='rejected' and stores the reason.
        Falls back to legacy approval_status write if no pending line found.
        """
        from datetime import datetime

        # Search for pending approval line for this user
        pending = await self._call_kw(
            "helpdesk.ticket.approval", "search_read",
            [[
                ["ticket_id", "=", ticket_id],
                ["approver_id", "=", user_id],
                ["status", "=", "pending"],
            ]],
            {"fields": ["id"], "limit": 1},
        )

        if pending:
            # Update the pending approval line — model custom propagates to global
            await self._call_kw(
                "helpdesk.ticket.approval", "write",
                [[pending[0]["id"]], {
                    "status": "rejected",
                    "approval_date": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "comment": reason,
                }],
            )
        else:
            # Fallback: legacy direct write for tickets without lines
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
        return await self._call_kw(
            "helpdesk.ticket.type", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name"], "order": "sequence"},
        )

    async def get_categories(self, parent_id: int = None) -> list:
        """
        Returns categories from the 3-level hierarchy.
            parent_id=None  → Level 1 root categories
            parent_id=<id>  → Children of that category (L2 or L3)
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
        return await self._call_kw(
            "helpdesk.ticket.urgency", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name"], "order": "sequence"},
        )

    async def get_impact_levels(self) -> list:
        return await self._call_kw(
            "helpdesk.ticket.impact", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name"], "order": "sequence"},
        )

    async def get_priority_levels(self) -> list:
        return await self._call_kw(
            "helpdesk.ticket.priority", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name"], "order": "sequence"},
        )

    async def get_stages(self) -> list:
        """
        Returns all active stages with their workflow flags.
        The agent uses is_resolve, is_start, is_close, is_pause to make decisions.
        """
        return await self._call_kw(
            "helpdesk.ticket.stage", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name", "is_start", "is_resolve", "is_close", "is_pause"],
             "order": "sequence"},
        )

    async def get_agent_groups(self) -> list:
        return await self._call_kw(
            "helpdesk.agent.group", "search_read",
            [[]],
            {"fields": ["id", "name"]},
        )

    async def get_resolvers(self) -> list:
        """
        Returns users that belong to helpdesk groups (Agent, Manager, Admin).
        Only these users can be assigned tickets.
        """
        return await self._call_kw(
            "res.users", "search_read",
            [[
                ["share", "=", False],
                "|",
                ["groups_id.full_name", "ilike", "Helpdesk Agente"],
                "|",
                ["groups_id.full_name", "ilike", "Helpdesk Gestor"],
                ["groups_id.full_name", "ilike", "Helpdesk Admin"],
            ]],
            {"fields": ["id", "name", "login"]},
        )

    async def get_resolved_tickets(self) -> list:
        """
        Returns resolved tickets for RAG seeding.
        Fetches tickets in stages with is_resolve=True or is_close=True.
        """
        raw = await self._call_kw(
            "helpdesk.ticket.base", "search_read",
            [[["|",
               ["stage_id.is_resolve", "=", True],
               ["stage_id.is_close",   "=", True]]]],
            {"fields": [
                "id", "name", "ticket_type_id", "category_id",
                "descripcion", "motivo_resolucion", "causa_raiz",
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
                "causa_raiz":        t.get("causa_raiz", ""),
            })
        return result

    # ── FASE 2: Approval lines ─────────────────────────────────────────────

    async def get_approval_lines(self, ticket_id: int) -> list:
        """
        Returns all approval lines for a ticket (multi-approver system).
        Used by supervisor to see approval progress and who approved/rejected.
        """
        lines = await self._call_kw(
            "helpdesk.ticket.approval", "search_read",
            [[["ticket_id", "=", ticket_id]]],
            {"fields": [
                "id", "approver_id", "role", "status",
                "approval_date", "comment", "attachment_ids",
            ], "order": "create_date desc"},
        )
        result = []
        for line in lines:
            approver_id = line.get("approver_id")
            result.append({
                "id":            line["id"],
                "approver_id":   approver_id[0] if isinstance(approver_id, list) else approver_id,
                "approver_name": approver_id[1] if isinstance(approver_id, list) and len(approver_id) > 1 else "",
                "role":          line.get("role", ""),
                "status":        line.get("status", ""),
                "approval_date": line.get("approval_date"),
                "comment":       line.get("comment", ""),
            })
        return result

    # ── FASE 3: Origins catalog ────────────────────────────────────────────

    async def get_origins(self) -> list:
        """Returns the ticket origin catalog (email, phone, web, in-person)."""
        return await self._call_kw(
            "helpdesk.ticket.origin", "search_read",
            [[["active", "=", True]]],
            {"fields": ["id", "name", "description"], "order": "sequence"},
        )

    # ── FASE 4: Audit log ─────────────────────────────────────────────────

    async def get_ticket_logs(self, ticket_id: int, limit: int = 50) -> list:
        """
        Returns audit history for a ticket from the Odoo Chatter.

        Tries two sources in order:
        1. helpdesk.ticket.log model (ITS custom audit trail)
        2. message_ids from mail.thread (Odoo native Chatter)

        Falls back to an empty list if neither source is available.
        """
        # ── Primary: helpdesk.ticket.log (ITS custom model) ─────────────────
        try:
            logs = await self._call_kw(
                "helpdesk.ticket.log", "search_read",
                [[["ticket_id", "=", ticket_id]]],
                {"fields": [
                    "id", "create_date", "user_id", "change_type",
                    "description", "field_label", "old_value", "new_value",
                    "stage_id_from", "stage_id_to",
                ], "order": "create_date desc", "limit": limit},
            )
            result = []
            for log in logs:
                user = log.get("user_id")
                stage_from = log.get("stage_id_from")
                stage_to = log.get("stage_id_to")
                result.append({
                    "id":          log["id"],
                    "create_date": log.get("create_date"),
                    "user_id":     user[0] if isinstance(user, list) else user,
                    "user_name":   user[1] if isinstance(user, list) and len(user) > 1 else "",
                    "change_type": log.get("change_type", ""),
                    "description": log.get("description", ""),
                    "field_label": log.get("field_label"),
                    "old_value":   log.get("old_value"),
                    "new_value":   log.get("new_value"),
                    "stage_from":  stage_from[1] if isinstance(stage_from, list) and len(stage_from) > 1 else "",
                    "stage_to":    stage_to[1] if isinstance(stage_to, list) and len(stage_to) > 1 else "",
                })
            return result
        except Exception as exc:
            _log.debug("helpdesk.ticket.log not available: %s — falling back to message_ids", exc)

        # ── Fallback: message_ids from mail.thread ──────────────────────────
        try:
            ticket = await self._call_kw(
                "helpdesk.ticket.base", "read",
                [[ticket_id]],
                {"fields": ["message_ids"]},
            )
            if not ticket or not ticket[0].get("message_ids"):
                return []

            message_ids = ticket[0]["message_ids"]
            if not message_ids:
                return []

            # Read message details (limit to most recent)
            recent_ids = message_ids[-min(limit, len(message_ids)):]
            messages = await self._call_kw(
                "mail.message", "search_read",
                [[["id", "in", recent_ids]]],
                {"fields": [
                    "id", "date", "author_id", "subject", "body",
                    "message_type", "subtype_id",
                ], "order": "date desc", "limit": limit},
            )

            result = []
            for msg in messages:
                author = msg.get("author_id")
                msg_type = msg.get("message_type", "")
                result.append({
                    "id":          msg["id"],
                    "create_date": msg.get("date"),
                    "user_id":     author[0] if isinstance(author, list) else author,
                    "user_name":   author[1] if isinstance(author, list) and len(author) > 1 else "",
                    "change_type": msg_type,
                    "description": msg.get("subject") or msg.get("body", "")[:200],
                    "field_label": None,
                    "old_value":   None,
                    "new_value":   None,
                    "stage_from":  "",
                    "stage_to":    "",
                    "_source":     "mail.message",
                })
            return result
        except Exception as exc:
            _log.debug("message_ids fallback also failed: %s", exc)

        return []

    # ── FASE 4: Knowledge base ─────────────────────────────────────────────

    async def get_knowledge_articles(self, query: str, limit: int = 10) -> list:
        """
        Searches knowledge base articles by name, keywords, or body content.
        Used by supervisor and resolver to find reference solutions.
        """
        articles = await self._call_kw(
            "helpdesk.knowledge", "search_read",
            [[["active", "=", True],
              "|", "|",
              ["name", "ilike", query],
              ["keywords", "ilike", query],
              ["body", "ilike", query]]],
            {"fields": [
                "id", "name", "category_id", "keywords", "view_count",
            ], "order": "view_count desc", "limit": limit},
        )
        result = []
        for a in articles:
            cat = a.get("category_id")
            result.append({
                "id":       a["id"],
                "name":     a.get("name", ""),
                "category": cat[1] if isinstance(cat, list) and len(cat) > 1 else "",
                "keywords": a.get("keywords", ""),
            })
        return result

    async def get_all_knowledge_articles(self) -> list:
        """
        Returns ALL active knowledge base articles for RAG seeding.
        Includes body content (the actual article text) for embedding.
        """
        articles = await self._call_kw(
            "helpdesk.knowledge", "search_read",
            [[["active", "=", True]]],
            {"fields": [
                "id", "name", "body", "category_id", "keywords",
            ], "limit": 500},
        )
        result = []
        for a in articles:
            cat = a.get("category_id")
            result.append({
                "id":       a["id"],
                "name":     a.get("name", ""),
                "body":     a.get("body", ""),
                "category": cat[1] if isinstance(cat, list) and len(cat) > 1 else "",
                "keywords": a.get("keywords", ""),
            })
        return result
