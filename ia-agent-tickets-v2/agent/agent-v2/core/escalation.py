"""
Escalation reminders — detect stalled tickets and notify agents.

Principle: NEVER reassign without consent. This module sends reminders
via internal ticket notes and Odoo activities. It NEVER calls assign_ticket.

Reminder levels:
  1. Agent reminder (4h of inactivity) → note + Odoo activity for agent
  2. Supervisor escalation (6h total, 2h after first reminder) → note for supervisor

Zero LLM tokens — all logic is timestamp-based comparisons.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

import psycopg
from config.settings import settings

_log = logging.getLogger("sara.escalation")


class EscalationReminder:
    """
    Detects tickets stalled for too long and sends reminders.

    Constraints:
      - No automatic reassignment — the agent/supervisor decides.
      - Reminders are idempotent — one per ticket per level.
      - Zero LLM token cost — pure SQL + Odoo ORM.
    """

    AGENT_THRESHOLD_HOURS = settings.escalation_agent_hours        # Notify agent after N hours without activity
    SUPERVISOR_THRESHOLD_HOURS = settings.escalation_supervisor_hours  # Notify supervisor after N hours total

    def __init__(self, ticket_port):
        self._port = ticket_port
        self._pg_dsn = settings.postgres_dsn

    async def check_and_remind(self) -> int:
        """
        Scans active tickets for inactivity and sends reminders.

        Activity is measured from the LATEST of:
          - fecha_asignacion (when ticket was assigned)
          - ultima_modificacion (last write to the ticket)

        Returns:
            Number of new reminders sent (0 if none needed).
        """
        if not self._pg_dsn:
            return 0

        try:
            tickets = await self._port.get_all_tickets(filters=None, limit=settings.escalation_scan_limit)
        except (ConnectionError, TimeoutError) as exc:
            # Backend unreachable or slow — skip this scan, retry on next tick.
            _log.debug("Escalation scan: backend unreachable — skipping (%s)", exc)
            return 0

        now = datetime.now(timezone.utc)
        sent = 0

        async with await psycopg.AsyncConnection.connect(self._pg_dsn) as conn:
            for ticket in tickets:
                # Only check open + assigned tickets
                stage = ticket.get("stage_id")
                stage_name = stage[1] if isinstance(stage, (list, tuple)) and len(stage) > 1 else ""
                if _is_closed(stage_name):
                    continue

                assignee = ticket.get("asignado_a")
                if not assignee:
                    continue  # Unassigned — supervisor sees these in dashboard

                assignee_id = assignee[0] if isinstance(assignee, (list, tuple)) else None
                if not assignee_id:
                    continue

                # Calculate inactivity
                last_activity = _get_last_activity(ticket)
                if last_activity is None:
                    continue  # No timestamps — can't measure

                idle_hours = (now - last_activity).total_seconds() / 3600

                ticket_id = _extract_ticket_id(ticket)
                ticket_name = ticket.get("name", str(ticket_id))

                # Check existing reminder for this ticket
                existing = await conn.execute(
                    "SELECT id, reminder_level FROM escalation_reminders "
                    "WHERE ticket_id = %s AND resolved_at IS NULL "
                    "ORDER BY reminder_level DESC LIMIT 1",
                    [ticket_id],
                )
                row = await existing.fetchone()
                existing_level = row[1] if row else 0

                # Level 1: agent reminder at 4h
                if idle_hours >= self.AGENT_THRESHOLD_HOURS and existing_level < 1:
                    await _send_agent_reminder(
                        self._port, conn, ticket_id, ticket_name,
                        assignee_id, int(idle_hours), 1,
                    )
                    sent += 1
                    continue

                # Level 2: supervisor escalation at 6h (after agent was reminded)
                if idle_hours >= self.SUPERVISOR_THRESHOLD_HOURS and existing_level == 1:
                    await _send_supervisor_escalation(
                        self._port, conn, ticket_id, ticket_name,
                        assignee_id, int(idle_hours), 2,
                    )
                    sent += 1

            if sent:
                await conn.commit()

        if sent:
            _log.info("Escalation scan: %d new reminder(s) sent", sent)

        return sent


# ── Helpers ────────────────────────────────────────────────────────────────

def _is_closed(stage_name: str) -> bool:
    """True if the stage name indicates the ticket is resolved/closed."""
    if not stage_name:
        return False
    name = stage_name.lower()
    return any(
        word in name
        for word in ("resuelto", "cerrado", "cancelado", "resolved", "closed")
    )


def _get_last_activity(ticket: dict) -> datetime | None:
    """
    Returns the most recent activity timestamp (UTC-aware).

    Considers: fecha_asignacion, ultima_modificacion, fecha_creacion.
    Newest wins — this is the last moment someone touched the ticket.
    """
    candidates: list[datetime | None] = []

    for field in ("fecha_asignacion", "ultima_modificacion", "fecha_creacion"):
        val = ticket.get(field)
        if val and isinstance(val, str):
            try:
                # Try ISO format
                raw = val.strip().replace("Z", "+00:00")
                dt = datetime.fromisoformat(raw)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                candidates.append(dt)
            except (ValueError, TypeError):
                pass

    if not candidates:
        return None

    return max(
        [c for c in candidates if c is not None],
        key=lambda d: d,
    )


def _extract_ticket_id(ticket: dict) -> int | None:
    """Extracts numeric ticket ID from Odoo-style dict."""
    tid = ticket.get("id")
    if tid is not None:
        try:
            return int(tid)
        except (TypeError, ValueError):
            pass
    # Fallback: parse from name
    name = ticket.get("name", "")
    if isinstance(name, str) and name.upper().startswith(("INC-", "SR-", "TCK-")):
        try:
            return int(name.split("-", 1)[1])
        except (IndexError, ValueError):
            pass
    return None


async def _send_agent_reminder(
    port, conn, ticket_id: int, ticket_name: str,
    assignee_id: int, idle_hours: int, level: int,
) -> None:
    """Sends a reminder to the agent and records it."""
    note = (
        f"⏰ Recordatorio automático: este ticket lleva {idle_hours}h sin actividad. "
        f"Si no podés atenderlo, contactá a tu supervisor para reasignarlo. "
        f"Si ya lo estás trabajando, ignorá este mensaje."
    )
    try:
        # 1. Add internal note to ticket (visible to agent + supervisor)
        await port.add_note(ticket_id, note, assignee_id)

        # 2. Record reminder in DB (dedup)
        await conn.execute(
            """
            INSERT INTO escalation_reminders (ticket_id, assignee_id, reminder_level)
            VALUES (%s, %s, %s)
            ON CONFLICT (ticket_id) DO UPDATE
            SET reminder_level = EXCLUDED.reminder_level,
                reminded_at = NOW(),
                resolved_at = NULL
            """,
            [ticket_id, assignee_id, level],
        )
        _log.info(
            "Level 1 reminder: %s → agent %s (%dh idle)",
            ticket_name, assignee_id, idle_hours,
        )
    except (psycopg.Error, ConnectionError) as exc:
        # DB or backend error — log and continue. Next scan will retry.
        _log.warning(
            "Failed to send agent reminder for %s: %s", ticket_name, exc,
        )


async def _send_supervisor_escalation(
    port, conn, ticket_id: int, ticket_name: str,
    assignee_id: int, idle_hours: int, level: int,
) -> None:
    """Notifies the supervisor about a ticket that hasn't been addressed."""
    note = (
        f"🚨 Escalación: {ticket_name} lleva {idle_hours}h sin actividad. "
        f"Agente asignado: ID {assignee_id}. "
        f"Se notificó al agente hace {idle_hours - 2}h. Considerá reasignar."
    )
    try:
        # Add note visible to supervisor (no specific user — goes to Chatter)
        await port.add_note(ticket_id, note, assignee_id)

        # Update reminder level
        await conn.execute(
            """
            UPDATE escalation_reminders
            SET reminder_level = %s, reminded_at = NOW(), resolved_at = NULL
            WHERE ticket_id = %s
            """,
            [level, ticket_id],
        )
        _log.info(
            "Level 2 escalation: %s → supervisor notified (%dh idle)",
            ticket_name, idle_hours,
        )
    except (psycopg.Error, ConnectionError) as exc:
        # DB or backend error — log and continue. Next scan will retry.
        _log.warning(
            "Failed to escalate %s: %s", ticket_name, exc,
        )


# ── Table management (called from scheduler) ────────────────────────────────

async def ensure_escalation_tables(pg_dsn: str) -> None:
    """Creates the escalation_reminders table."""
    if not pg_dsn:
        return
    try:
        async with await psycopg.AsyncConnection.connect(pg_dsn) as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS escalation_reminders (
                    id              SERIAL PRIMARY KEY,
                    ticket_id       INTEGER NOT NULL UNIQUE,
                    assignee_id     INTEGER,
                    reminder_level  INTEGER DEFAULT 1
                        CHECK(reminder_level IN (1, 2)),
                    reminded_at     TIMESTAMPTZ DEFAULT NOW(),
                    resolved_at     TIMESTAMPTZ
                )
            """)
            await conn.commit()
            _log.debug("escalation_reminders table verified.")
    except psycopg.Error as exc:
        _log.warning("Could not create escalation_reminders table: %s", exc)
