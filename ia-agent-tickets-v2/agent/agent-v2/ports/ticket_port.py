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
    def create_ticket(self, payload: dict, user_id: int) -> dict:
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
    def get_tickets_by_creator(self, user_id: int) -> list:
        """Returns all tickets created by the given user."""

    @abstractmethod
    def get_tickets_by_assignee(self, user_id: int) -> list:
        """Returns all tickets assigned to the given user."""

    @abstractmethod
    def get_ticket_detail(self, ticket_id: int, user_id: int, role: str) -> dict:
        """Returns full ticket details including SLA, stage, and assignment info."""

    @abstractmethod
    def resolve_ticket(self, ticket_id: int, motivo_resolucion: str,
                       causa_raiz: str, user_id: int) -> dict:
        """
        Mark ticket as resolved.
        Sets motivo_resolucion and causa_raiz, then moves to resolve stage.
        """

    @abstractmethod
    def update_ticket(self, ticket_id: int, fields: dict, user_id: int) -> dict:
        """Update arbitrary ticket fields. fields uses Odoo technical names."""

    @abstractmethod
    def get_all_tickets(self, filters: dict = None) -> list:
        """
        Returns all tickets. Optional filters dict supports:
            stage_id, urgency_id, priority_id, asignado_a, category_id
        """

    @abstractmethod
    def assign_ticket(self, ticket_id: int, assignee_id: int,
                      agent_group_id: int, user_id: int) -> dict:
        """Assign ticket to an agent and optionally set agent group."""

    @abstractmethod
    def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """Reopen a resolved or closed ticket."""

    # SECURITY: delete_ticket is defined in the interface but intentionally
    # excluded from all role tool lists until an authorization layer is in place.
    # To enable: add delete_ticket to get_supervisor_tools() in tools/ticket_tools.py
    @abstractmethod
    def delete_ticket(self, ticket_id: int, user_id: int) -> dict:
        """Permanently delete a ticket. Requires supervisor role."""

    # ── Catalog queries ──────────────────────────────────────────────────────

    @abstractmethod
    def get_resolvers(self) -> list:
        """Returns all users with resolver/agent role."""

    @abstractmethod
    def get_agent_groups(self) -> list:
        """Returns all available agent groups (helpdesk_agent_group)."""

    @abstractmethod
    def get_ticket_types(self) -> list:
        """
        Returns available ticket types.
        Each item: {"id": int, "name": str}
        Example: [{"id": 1, "name": "Incidente"}, ...]
        """

    @abstractmethod
    def get_categories(self, parent_id: int = None) -> list:
        """
        Returns categories from the 3-level hierarchy.
            parent_id=None  → Level 1 categories
            parent_id=<id>  → Children of that category (L2 or L3)
        Each item: {"id": int, "name": str, "full_name": str, "level": int}
        """

    @abstractmethod
    def get_urgency_levels(self) -> list:
        """Returns urgency catalog. Each item: {"id": int, "name": str}"""

    @abstractmethod
    def get_impact_levels(self) -> list:
        """Returns impact catalog. Each item: {"id": int, "name": str}"""

    @abstractmethod
    def get_priority_levels(self) -> list:
        """Returns priority catalog. Each item: {"id": int, "name": str}"""

    @abstractmethod
    def get_stages(self) -> list:
        """
        Returns workflow stages with their flags.
        Each item: {
            "id": int, "name": str,
            "is_start": bool, "is_resolve": bool,
            "is_close": bool, "is_pause": bool
        }
        """

    @abstractmethod
    def get_resolved_tickets(self) -> list:
        """
        Returns resolved tickets for RAG seeding.
        Each item must contain: ticket_id, ticket_type, category, description,
                                motivo_resolucion (resolution text)
        """
