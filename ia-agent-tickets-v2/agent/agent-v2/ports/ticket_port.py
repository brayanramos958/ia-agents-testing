"""
Abstract interface for all ticket system operations.

Adapters implement this interface. The agent core only knows this contract —
it never imports from any specific adapter.

Field names follow the real Odoo Helpdesk schema (campos-modulo-helpdesk.md).

ARCHITECTURE NOTE (Fase 8 — async migration):
    All methods are `async def`. This is intentional and required for:
    1. Native asyncio support in LangGraph 1.1+ (no thread pool bottleneck)
    2. httpx.AsyncClient connection pooling (50 connections per process)
    3. Concurrent Odoo RPCs via `asyncio.gather()` (e.g. operation metrics)
    4. Future support for streaming and SSE without run_in_executor

    All concrete adapters (OdooAdapter, ExpressAdapter, HttpAdapter) MUST
    implement these as `async def`. Do NOT add `asyncio.to_thread()` inside
    the adapter — the goal is to remove the thread pool entirely.
"""

from abc import ABC, abstractmethod


class ITicketPort(ABC):

    # ── Ticket operations ────────────────────────────────────────────────────

    @abstractmethod
    async def create_ticket(self, payload: dict, user_id: int) -> dict:
        """
        Create a new ticket.

        Args:
            payload: Ticket data. Expected keys (Odoo field names):
                asunto              str   — ticket subject/title
                descripcion         str   — full problem description
                ticket_type_id      int   — FK to helpdesk.ticket.type
                category_id         int   — FK to helpdesk.category (level 1)
                subcategory_id      int   — FK to helpdesk.category (level 2, optional)
                element_id          int   — FK to helpdesk.category (level 3, optional)
                urgency_id          int   — FK to helpdesk.ticket.urgency
                impact_id           int   — FK to helpdesk.ticket.impact
                priority_id         int   — FK to helpdesk.ticket.priority
                system_equipment    str   — device or software name (optional)
                                            NOTE: not a real Odoo field — adapters map
                                            this value into descripcion as a suffix.
                partner_id is NOT passed by the caller — each adapter resolves it
                internally from user_id (res.users → partner_id).
            user_id: Odoo res.users ID of the ticket creator.

        Returns:
            dict: On success: ``{"success": True, "ticket_name": "TCK-0001", "ticket_id": int}``.
                  On failure: ``{"success": False, "error": str}``.

        Raises:
            RuntimeError: On backend errors (Odoo RPC failure, auth error, etc.).
        """

    @abstractmethod
    async def get_tickets_by_creator(self, user_id: int) -> list:
        """
        Return all open tickets created by or for the given user.

        Args:
            user_id: Odoo res.users ID.

        Returns:
            list[dict]: Ticket records with at minimum the fields:
                name, asunto, stage_id, urgency_id, ticket_type_id,
                fecha_creacion, partner_id.
        """

    @abstractmethod
    async def get_tickets_by_assignee(self, user_id: int) -> list:
        """
        Return all tickets currently assigned to the given agent.

        Args:
            user_id: Odoo res.users ID of the assignee.

        Returns:
            list[dict]: Ticket records with at minimum:
                name, asunto, stage_id, urgency_id, priority_id,
                ticket_type_id, partner_id, fecha_creacion.
        """

    @abstractmethod
    async def get_ticket_detail(self, ticket_id: int, user_id: int, role: str) -> dict:
        """
        Return full ticket details including SLA, stage, and assignment info.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            user_id: Caller's user ID (for authorization checks).
            role: Caller's role (``"creador"``, ``"resueltor"``, ``"supervisor"``).

        Returns:
            dict: Ticket record with all relevant fields, or
                  ``{"error": str}`` if not found.
        """

    @abstractmethod
    async def resolve_ticket(self, ticket_id: int, motivo_resolucion: str,
                             causa_raiz: str, user_id: int) -> dict:
        """
        Mark ticket as resolved.

        Sets ``motivo_resolucion`` and ``causa_raiz``, then moves the ticket to
        the resolve stage. The stage change is mandatory — Odoo does not
        auto-transition.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            motivo_resolucion: Resolution text (min 10 chars enforced by Odoo).
            causa_raiz: Root cause analysis text.
            user_id: Resolver's user ID.

        Returns:
            dict: ``{"success": True, "ticket_id": int}`` or
                  ``{"success": False, "error": str}``.
        """

    @abstractmethod
    async def update_ticket(self, ticket_id: int, fields: dict, user_id: int) -> dict:
        """
        Update arbitrary ticket fields using Odoo technical field names.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            fields: Dict of Odoo field names to values.
            user_id: Caller's user ID (for audit trail).

        Returns:
            dict: ``{"success": True, "ticket_id": int}`` or error dict.
        """

    @abstractmethod
    async def get_all_tickets(self, filters: dict | None = None) -> list:
        """
        Return all open/active tickets by default.

        To include closed tickets, pass filters that explicitly override the
        default ``stage_id.is_close = False`` filter.

        Args:
            filters: Optional dict supporting Odoo field names:
                stage_id, urgency_id, priority_id, asignado_a, category_id.

        Returns:
            list[dict]: At most 50 tickets by default. Use filters for narrower views.
        """

    @abstractmethod
    async def assign_ticket(self, ticket_id: int, assignee_id: int,
                            agent_group_id: int, user_id: int) -> dict:
        """
        Assign ticket to an agent and optionally set agent group.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            assignee_id: Odoo res.users ID of the assignee.
            agent_group_id: Odoo helpdesk.agent.group ID (``0`` to skip).
            user_id: Supervisor's user ID.

        Returns:
            dict: ``{"success": True, "ticket_id": int}`` or error dict.
        """

    @abstractmethod
    async def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """
        Reopen a resolved or closed ticket.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            reason: Reopen reason (stored for audit trail).
            user_id: Supervisor's user ID.

        Returns:
            dict: ``{"success": True, "ticket_id": int}`` or error dict.
        """

    @abstractmethod
    async def approve_ticket(self, ticket_id: int, user_id: int) -> dict:
        """
        Approve a pending ticket so the resolver can proceed.

        Sets ``approval_status`` to ``"approved"`` and ``approval_date`` to now.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            user_id: Supervisor's user ID.

        Returns:
            dict: ``{"success": bool, ...}``.
        """

    @abstractmethod
    async def reject_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """
        Reject a pending ticket.

        Sets ``approval_status`` to ``"rejected"`` and stores the rejection
        reason in ``approval_comment``.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            reason: Rejection reason.
            user_id: Supervisor's user ID.

        Returns:
            dict: ``{"success": bool, ...}``.
        """

    # SECURITY: delete_ticket is defined in the interface but intentionally
    # excluded from all role tool lists until an authorization layer is in place.
    # To enable: add delete_ticket to get_supervisor_tools() in tools/ticket_tools.py
    @abstractmethod
    async def delete_ticket(self, ticket_id: int, user_id: int) -> dict:
        """
        Permanently delete a ticket. Requires supervisor role.

        SECURITY: Tool is currently excluded from all role tool lists.

        Args:
            ticket_id: Odoo helpdesk.ticket.base ID.
            user_id: Supervisor's user ID.

        Returns:
            dict: ``{"success": bool, ...}``.
        """

    # ── Catalog queries ──────────────────────────────────────────────────────

    @abstractmethod
    async def get_resolvers(self) -> list:
        """
        Return all users with resolver/agent role.

        Returns:
            list[dict]: Each item has ``id``, ``name``, ``login``.
        """

    @abstractmethod
    async def get_agent_groups(self) -> list:
        """
        Return all available agent groups (``helpdesk_agent_group``).

        Returns:
            list[dict]: Each item has ``id``, ``name``.
        """

    @abstractmethod
    async def get_ticket_types(self) -> list:
        """
        Return available ticket types.

        Returns:
            list[dict]: Each item: ``{"id": int, "name": str}``.
            Example: ``[{"id": 1, "name": "Incidente"}, ...]``.
        """

    @abstractmethod
    async def get_categories(self, parent_id: int | None = None) -> list:
        """
        Return categories from the 3-level hierarchy.

        Args:
            parent_id: If ``None``, returns Level 1 categories. Otherwise returns
                       children of that category (Level 2 or Level 3).

        Returns:
            list[dict]: Each item: ``{"id": int, "name": str, "full_name": str, "level": int}``.
        """

    @abstractmethod
    async def get_urgency_levels(self) -> list:
        """
        Return urgency catalog.

        Returns:
            list[dict]: Each item: ``{"id": int, "name": str}``.
        """

    @abstractmethod
    async def get_impact_levels(self) -> list:
        """
        Return impact catalog.

        Returns:
            list[dict]: Each item: ``{"id": int, "name": str}``.
        """

    @abstractmethod
    async def get_priority_levels(self) -> list:
        """
        Return priority catalog.

        Returns:
            list[dict]: Each item: ``{"id": int, "name": str}``.
        """

    @abstractmethod
    async def get_stages(self) -> list:
        """
        Return workflow stages with their flags.

        Returns:
            list[dict]: Each item:
                ``{"id": int, "name": str, "is_start": bool, "is_resolve": bool,
                "is_close": bool, "is_pause": bool}``.
        """

    @abstractmethod
    async def get_resolved_tickets(self) -> list:
        """
        Return resolved tickets for RAG seeding.

        Returns:
            list[dict]: Each item must contain:
                ticket_id, ticket_type, category, description, motivo_resolucion.
        """

    # ── Operation metrics (Phase 1) ───────────────────────────────────────────

    @abstractmethod
    async def get_operation_metrics(self) -> dict:
        """
        Return operational metrics computed from the ticket system.

        Used by ``GET /agent/metrics`` — populates the ``"operation"`` section.

        Returns:
            dict: Operational KPIs with keys:
                avg_time_to_assign_hours (float):
                    Mean hours between ticket creation and approval.
                avg_time_to_resolve_hours (float):
                    Mean hours between ticket creation and resolution.
                tickets_by_category (list[dict]):
                    ``[{"category": str, "count": int}, ...]`` top 10.
                tickets_by_urgency (list[dict]):
                    ``[{"urgency": str, "count": int}, ...]``.
                approval_rate (dict):
                    ``{"approved": int, "rejected": int, "pending": int}``.
                reopen_rate (float):
                    Ratio of tickets that were resolved then reopened.
        """
