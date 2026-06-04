"""
PostgreSQL adapter — FUTURE / SKELETON.

Direct database access for enterprise environments where the REST API
is not available or too slow for bulk operations.

All methods raise NotImplementedError with the required SQL query documented.
An enterprise developer fills these in when direct DB access is granted.

Dependencies to install when implementing:
    uv add psycopg2-binary
    # or: uv add asyncpg  (if switching to async)

Odoo table names used:
    helpdesk_ticket           — main ticket table
    helpdesk_ticket_stage     — workflow stages
    helpdesk_category         — 3-level category tree
    helpdesk_urgency          — urgency catalog
    helpdesk_impact           — impact catalog
    helpdesk_priority         — priority catalog
    helpdesk_ticket_type      — ticket type catalog
    helpdesk_agent_group      — agent groups
    res_users                 — system users (agents, supervisors)
    res_partner               — contacts (requestors)
"""

from ports.ticket_port import ITicketPort


class PostgresAdapter(ITicketPort):
    """
    Direct PostgreSQL access to Odoo Helpdesk tables.
    All methods are stubs pending enterprise DB access credentials.
    """

    def __init__(self, connection_string: str):
        """
        Args:
            connection_string: PostgreSQL DSN.
                Example: "postgresql://user:password@host:5432/odoo_db"
                Set via POSTGRES_URL env var in settings.py when activating.
        """
        self._conn_str = connection_string
        # TODO: Initialize connection pool here when implementing
        # import psycopg2
        # self._pool = psycopg2.connect(connection_string)

    def create_ticket(self, payload: dict, user_id: int) -> dict:
        """
        Required SQL:
            INSERT INTO helpdesk_ticket
                (asunto, descripcion, ticket_type_id, category_id, subcategory_id,
                 element_id, urgency_id, impact_id, priority_id, partner_id,
                 affected_user_id, system_equipment, usuario_solicitante_id,
                 create_uid, write_uid, create_date, write_date)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, NOW(), NOW())
            RETURNING id, name
        """
        raise NotImplementedError("PostgresAdapter.create_ticket not yet implemented")

    def get_tickets_by_creator(self, user_id: int) -> list:
        """
        Required SQL:
            SELECT id, name, asunto, stage_id, urgency_id, priority_id,
                   asignado_a, create_date
            FROM helpdesk_ticket
            WHERE usuario_solicitante_id = %s
            ORDER BY create_date DESC
        """
        raise NotImplementedError

    def get_tickets_by_assignee(self, user_id: int) -> list:
        """
        Required SQL:
            SELECT id, name, asunto, stage_id, urgency_id, priority_id,
                   usuario_solicitante_id, create_date
            FROM helpdesk_ticket
            WHERE asignado_a = %s
            ORDER BY create_date DESC
        """
        raise NotImplementedError

    def get_ticket_detail(self, ticket_id: int, user_id: int, role: str) -> dict:
        """
        Required SQL:
            SELECT t.*, s.name as stage_name, s.is_resolve, s.is_close,
                   u.name as urgency_name, i.name as impact_name,
                   p.name as priority_name, c.full_name as category_full_name,
                   tt.name as ticket_type_name
            FROM helpdesk_ticket t
            LEFT JOIN helpdesk_ticket_stage s ON s.id = t.stage_id
            LEFT JOIN helpdesk_urgency u ON u.id = t.urgency_id
            LEFT JOIN helpdesk_impact i ON i.id = t.impact_id
            LEFT JOIN helpdesk_priority p ON p.id = t.priority_id
            LEFT JOIN helpdesk_category c ON c.id = t.category_id
            LEFT JOIN helpdesk_ticket_type tt ON tt.id = t.ticket_type_id
            WHERE t.id = %s
        """
        raise NotImplementedError

    def resolve_ticket(self, ticket_id: int, motivo_resolucion: str,
                       causa_raiz: str, user_id: int) -> dict:
        """
        Required SQL (two steps):
        1. Get resolve stage ID:
            SELECT id FROM helpdesk_ticket_stage WHERE is_resolve = TRUE LIMIT 1

        2. Update ticket:
            UPDATE helpdesk_ticket
            SET motivo_resolucion = %s,
                causa_raiz = %s,
                stage_id = %s,
                fin_falla = NOW(),
                write_uid = %s,
                write_date = NOW()
            WHERE id = %s
        """
        raise NotImplementedError

    def update_ticket(self, ticket_id: int, fields: dict, user_id: int) -> dict:
        """
        Dynamic UPDATE. Build SET clause from fields dict.
        Always set write_uid = %s and write_date = NOW().
        """
        raise NotImplementedError

    def get_all_tickets(self, filters: dict = None) -> list:
        """
        Required SQL (base):
            SELECT id, name, asunto, stage_id, urgency_id, priority_id,
                   asignado_a, usuario_solicitante_id, category_id, create_date
            FROM helpdesk_ticket
            WHERE active = TRUE
            [AND stage_id = %s] [AND urgency_id = %s] ...
            ORDER BY create_date DESC
        Filters are appended dynamically from the filters dict.
        """
        raise NotImplementedError

    def assign_ticket(self, ticket_id: int, assignee_id: int,
                      agent_group_id: int, user_id: int) -> dict:
        """
        Required SQL:
            UPDATE helpdesk_ticket
            SET asignado_a = %s,
                agent_group_id = %s,
                fecha_asignacion = NOW(),
                write_uid = %s,
                write_date = NOW()
            WHERE id = %s
        Also set stage to the 'assigned' stage if one exists.
        """
        raise NotImplementedError

    def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict:
        """
        Required SQL:
        1. Get start stage:
            SELECT id FROM helpdesk_ticket_stage WHERE is_start = TRUE LIMIT 1
        2. Update:
            UPDATE helpdesk_ticket
            SET stage_id = %s,
                causa_raiz = %s,
                fin_falla = NULL,
                write_uid = %s,
                write_date = NOW()
            WHERE id = %s
        """
        raise NotImplementedError

    def delete_ticket(self, ticket_id: int, user_id: int) -> dict:
        """
        SECURITY: Disabled pending authorization layer.

        Required SQL when authorized:
            DELETE FROM helpdesk_ticket WHERE id = %s
        Also delete related: helpdesk_ticket_log, approval lines, etc.
        """
        # SECURITY: delete_ticket tool is excluded from all role tool lists.
        # This method stays as a stub until the authorization layer is implemented.
        raise NotImplementedError("PostgresAdapter.delete_ticket not yet implemented")

    # ── Catalog queries ──────────────────────────────────────────────────────

    def get_resolvers(self) -> list:
        """
        Required SQL:
            SELECT u.id, u.name
            FROM res_users u
            JOIN res_groups_users_rel r ON r.uid = u.id
            WHERE r.gid = (SELECT id FROM res_groups WHERE name = 'Helpdesk Agent')
        """
        raise NotImplementedError

    def get_agent_groups(self) -> list:
        """
        Required SQL:
            SELECT id, name FROM helpdesk_agent_group WHERE active = TRUE
        """
        raise NotImplementedError

    def get_ticket_types(self) -> list:
        """
        Required SQL:
            SELECT id, name FROM helpdesk_ticket_type WHERE active = TRUE ORDER BY name
        """
        raise NotImplementedError

    def get_categories(self, parent_id: int = None) -> list:
        """
        Required SQL:
            SELECT id, name, full_name, level, parent_id
            FROM helpdesk_category
            WHERE parent_id IS [NOT] NULL [AND parent_id = %s]
            ORDER BY sequence, name
        """
        raise NotImplementedError

    def get_urgency_levels(self) -> list:
        """
        Required SQL:
            SELECT id, name FROM helpdesk_urgency ORDER BY sequence
        """
        raise NotImplementedError

    def get_impact_levels(self) -> list:
        """
        Required SQL:
            SELECT id, name FROM helpdesk_impact ORDER BY sequence
        """
        raise NotImplementedError

    def get_priority_levels(self) -> list:
        """
        Required SQL:
            SELECT id, name FROM helpdesk_priority ORDER BY sequence
        """
        raise NotImplementedError

    def get_stages(self) -> list:
        """
        Required SQL:
            SELECT id, name, is_start, is_resolve, is_close, is_pause
            FROM helpdesk_ticket_stage
            ORDER BY sequence
        """
        raise NotImplementedError

    def get_resolved_tickets(self) -> list:
        """
        Required SQL:
            SELECT t.id, t.name, tt.name as ticket_type, c.name as category,
                   t.descripcion, t.motivo_resolucion
            FROM helpdesk_ticket t
            LEFT JOIN helpdesk_ticket_type tt ON tt.id = t.ticket_type_id
            LEFT JOIN helpdesk_category c ON c.id = t.category_id
            JOIN helpdesk_ticket_stage s ON s.id = t.stage_id
            WHERE s.is_resolve = TRUE OR s.is_close = TRUE
              AND t.motivo_resolucion IS NOT NULL
              AND t.motivo_resolucion != ''
        """
        raise NotImplementedError
