"""
Abstract interface for all ticket system operations.

Adapters implement this interface. The agent core only knows this contract —
it never imports from any specific adapter.

Field names follow the real Odoo Helpdesk schema (campos-modulo-helpdesk.md).
"""

from abc import ABC, abstractmethod


class ITicketPort(ABC):

    # ── Ticket operations ────────────────────────────────────────────────────

    @abstractmethod
    async def create_ticket(self, payload: dict, user_id: int) -> dict:
        """
        Create a new ticket.

        Expected payload keys (Odoo field names):
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

        Returns:
            {"success": True, "ticket_name": "TCK-0001", "ticket_id": int}
            {"success": False, "error": str}
        """

    @abstractmethod
    async def get_tickets_by_creator(self, user_id: int) -> list:
        """Returns all tickets created by the given user."""

    @abstractmethod
    async def get_tickets_by_assignee(self, user_id: int) -> list:
        """Returns all tickets assigned to the given user."""

    @abstractmethod
    async def get_ticket_detail(self, ticket_id: int, user_id: int, role: str) -> dict:
        """Returns full ticket details including SLA, stage, and assignment info."""

    @abstractmethod
    async def resolve_ticket(self, ticket_id: int, motivo_resolucion: str,
                       causa_raiz: str, user_id: int) -> dict:
        """
        Mark ticket as resolved.
        Sets motivo_resolucion and causa_raiz, then moves to resolve stage.
        """

    @abstractmethod
    async def update_ticket(self, ticket_id: int, fields: dict, user_id: int) -> dict:
        """Update arbitrary ticket fields. fields uses Odoo technical names."""

    @abstractmethod
    async def get_all_tickets(self, filters: dict = None, limit: int = 15, offset: int = 0) -> list:
        """
        Returns tickets with pagination support.
        
        Args:
            filters: Optional dict with Odoo field names (stage_id, asignado_a, etc.)
            limit:  Max number of tickets to return (default 15)
            offset: Number of tickets to skip (0 = first page)
            
        Tickets are ordered by fecha_creacion desc (most recent first).
        """

    @abstractmethod
    async def assign_ticket(self, ticket_id: int, assignee_id: int,
                      agent_group_id: int, user_id: int) -> dict:
        """Assign ticket to an agent and optionally set agent group."""

    @abstractmethod
    async def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """Reopen a resolved or closed ticket."""

    @abstractmethod
    async def approve_ticket(self, ticket_id: int, user_id: int) -> dict:
        """
        Approve a pending ticket so the resolver can proceed.
        Sets approval_status to "approved".
        Returns: {"success": bool}
        """

    @abstractmethod
    async def reject_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """
        Reject a pending ticket.
        Sets approval_status to "rejected" and stores the rejection reason.
        Returns: {"success": bool}
        """

    # SECURITY: delete_ticket is defined in the interface but intentionally
    # excluded from all role tool lists until an authorization layer is in place.
    # To enable: add delete_ticket to get_supervisor_tools() in tools/ticket_tools.py
    @abstractmethod
    async def delete_ticket(self, ticket_id: int, user_id: int) -> dict:
        """Permanently delete a ticket. Requires supervisor role."""

    # ── Catalog queries ──────────────────────────────────────────────────────

    @abstractmethod
    async def get_resolvers(self) -> list:
        """Returns all users with resolver/agent role."""

    @abstractmethod
    async def get_agent_groups(self) -> list:
        """Returns all available agent groups (helpdesk_agent_group)."""

    @abstractmethod
    async def get_ticket_types(self) -> list:
        """
        Returns available ticket types.
        Each item: {"id": int, "name": str}
        Example: [{"id": 1, "name": "Incidente"}, ...]
        """

    @abstractmethod
    async def get_categories(self, parent_id: int = None) -> list:
        """
        Returns categories from the 3-level hierarchy.
            parent_id=None  → Level 1 categories
            parent_id=<id>  → Children of that category (L2 or L3)
        Each item: {"id": int, "name": str, "full_name": str, "level": int}
        """

    @abstractmethod
    async def get_urgency_levels(self) -> list:
        """Returns urgency catalog. Each item: {"id": int, "name": str}"""

    @abstractmethod
    async def get_impact_levels(self) -> list:
        """Returns impact catalog. Each item: {"id": int, "name": str}"""

    @abstractmethod
    async def get_priority_levels(self) -> list:
        """Returns priority catalog. Each item: {"id": int, "name": str}"""

    @abstractmethod
    async def get_stages(self) -> list:
        """
        Returns workflow stages with their flags.
        Each item: {
            "id": int, "name": str,
            "is_start": bool, "is_resolve": bool,
            "is_close": bool, "is_pause": bool
        }
        """

    @abstractmethod
    async def get_resolved_tickets(self) -> list:
        """
        Returns resolved tickets for RAG seeding.
        Each item must contain: ticket_id, ticket_type, category, description,
                                motivo_resolucion (resolution text)
        """

    # ── FASE 2: Approval lines ────────────────────────────────────────────

    @abstractmethod
    async def get_approval_lines(self, ticket_id: int) -> list:
        """
        Returns approval lines for a ticket (multi-approver system).
        Each item: {
            "id": int, "approver_id": int, "approver_name": str,
            "role": str, "status": str, "approval_date": str,
            "comment": str
        }
        """

    # ── FASE 3: Origins catalog ───────────────────────────────────────────

    @abstractmethod
    async def get_origins(self) -> list:
        """
        Returns ticket origin catalog.
        Each item: {"id": int, "name": str, "description": str}
        """

    # ── FASE 4: Audit log ─────────────────────────────────────────────────

    @abstractmethod
    async def get_ticket_logs(self, ticket_id: int, limit: int = 50) -> list:
        """
        Returns audit logs for a ticket (history of changes).
        Each item: {
            "id": int, "create_date": str, "user_id": int, "user_name": str,
            "change_type": str, "description": str,
            "field_label": str, "old_value": str, "new_value": str,
            "stage_from": str, "stage_to": str
        }
        """

    # ── FASE 4: Knowledge base ────────────────────────────────────────────

    @abstractmethod
    async def get_knowledge_articles(self, query: str, limit: int = 10) -> list:
        """
        Searches knowledge base articles matching the query.
        Each item: {"id": int, "name": str, "category": str, "keywords": str}
        """

    @abstractmethod
    async def get_all_knowledge_articles(self) -> list:
        """
        Returns ALL active knowledge base articles for RAG seeding.
        Each item: {"id": int, "name": str, "body": str, "category": str, "keywords": str}
        """

    # ── FASE 5: Internal notes ─────────────────────────────────────────────

    @abstractmethod
    async def add_note(self, ticket_id: int, note: str, user_id: int) -> dict:
        """
        Adds an internal note (comment) to a ticket without changing its state.

        In Odoo: calls message_post with message_type='comment' (internal note).
        Internal notes are visible to agents/supervisors but not to end users.

        Args:
            ticket_id: Numeric ticket ID
            note: Plain text note content
            user_id: Author of the note (agent/supervisor)

        Returns:
            {"success": True, "message_id": int}
            {"success": False, "error": str}
        """
