"""
Background task scheduler for proactive monitoring.
All scans use Odoo ORM / PostgreSQL directly — ZERO LLM token consumption.

Architecture:
  SARAScheduler runs as an asyncio background task started during FastAPI lifespan.
  It periodically scans Odoo for SLA-critical tickets and stores alerts in PostgreSQL.
  The supervisor sees alert counts in their context and can query GET /agent/alerts.

This module is designed to be framework-agnostic: it depends only on the ticket port
interface, not on FastAPI or LangChain internals.
"""

from __future__ import annotations

import logging
import asyncio
from datetime import datetime, timedelta, timezone

import psycopg

from config.settings import settings

_log = logging.getLogger("sara.scheduler")


class SARAScheduler:
    """
    Periodic background scanner for proactive alerting.

    Responsibilities:
      - SLA scan: every N minutes, check Odoo for tickets about to expire
      - Store alerts in sla_alerts PostgreSQL table (deduplicated)
      - Expose unacknowledged alert count for supervisor context injection

    All queries are SQL or Odoo ORM — zero LLM token cost.
    """

    def __init__(self, ticket_port, interval_min: int = 5,
                 escalation_interval_min: int = 60):
        """
        Args:
            ticket_port: ITicketPort implementation (OdooAdapter or ExpressAdapter).
            interval_min: minutes between SLA scans.
            escalation_interval_min: minutes between escalation reminder scans.
        """
        self._port = ticket_port
        self._pg_dsn = settings.postgres_dsn
        self._interval = interval_min * 60
        self._escalation_interval = escalation_interval_min * 60
        self._sla_task: asyncio.Task | None = None
        self._esc_task: asyncio.Task | None = None
        self._table_ready = False

    # ── Lifecycle ───────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Starts the background scan loop. Must be called after port init."""
        if not self._pg_dsn:
            _log.warning(
                "Scheduler: POSTGRES_DSN is empty — background scans disabled."
            )
            return

        await self._ensure_tables()
        self._table_ready = True
        _log.info(
            "Scheduler started — SLA every %d min, escalation every %d min. "
            "NOTE: SLA alerts only trigger when tickets have deadline_date set in Odoo.",
            self._interval // 60, self._escalation_interval // 60,
        )
        # Run first scans immediately, then loop
        self._sla_task = asyncio.create_task(self._sla_loop())
        self._esc_task = asyncio.create_task(self._escalation_loop())

    async def stop(self) -> None:
        """Gracefully cancels background tasks."""
        for task in (self._sla_task, self._esc_task):
            if task:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        _log.info("Scheduler stopped.")

    # ── SLA loop ────────────────────────────────────────────────────────────

    async def _sla_loop(self) -> None:
        """Infinite loop: SLA scan → sleep → repeat."""
        while True:
            try:
                await self._scan_sla_alerts()
            except asyncio.CancelledError:
                break
            except Exception:
                _log.exception("SLA scan failed")
            await asyncio.sleep(self._interval)

    # ── Escalation loop ─────────────────────────────────────────────────────

    async def _escalation_loop(self) -> None:
        """Infinite loop: escalation scan → long sleep → repeat."""
        # Wait 2 minutes initially — give the system time to settle
        await asyncio.sleep(120)
        while True:
            try:
                await self._scan_escalation()
            except asyncio.CancelledError:
                break
            except Exception:
                _log.exception("Escalation scan failed")
            await asyncio.sleep(self._escalation_interval)

    async def _scan_escalation(self) -> int:
        """Delegates to EscalationReminder for stalled ticket detection."""
        from core.escalation import EscalationReminder
        reminder = EscalationReminder(self._port)
        return await reminder.check_and_remind()

    # ── Table management ────────────────────────────────────────────────────

    async def _ensure_tables(self) -> None:
        """Creates sla_alerts, escalation_reminders, and ticket_templates tables."""
        async with await psycopg.AsyncConnection.connect(self._pg_dsn) as conn:
            # SLA alerts
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS sla_alerts (
                    id              SERIAL PRIMARY KEY,
                    ticket_id       INTEGER NOT NULL,
                    ticket_name     TEXT,
                    alert_type      TEXT NOT NULL
                        CHECK(alert_type IN ('expires_soon', 'expired')),
                    deadline        TIMESTAMPTZ,
                    assigned_to     INTEGER,
                    assigned_name   TEXT,
                    created_at      TIMESTAMPTZ DEFAULT NOW(),
                    acknowledged_by INTEGER,
                    acknowledged_at TIMESTAMPTZ
                )
            """)
            # Partial index for fast unacknowledged query
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_sla_alerts_unack
                ON sla_alerts (created_at)
                WHERE acknowledged_by IS NULL
            """)
            # Ticket templates
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS ticket_templates (
                    id              SERIAL PRIMARY KEY,
                    name            TEXT NOT NULL,
                    description     TEXT DEFAULT '',
                    keywords        TEXT DEFAULT '',
                    ticket_type_id  INTEGER,
                    category_id     INTEGER,
                    urgency_id      INTEGER,
                    impact_id       INTEGER,
                    priority_id     INTEGER,
                    is_active       BOOLEAN DEFAULT TRUE,
                    created_at      TIMESTAMPTZ DEFAULT NOW()
                )
            """)
            await conn.commit()
            _log.debug("All scheduler tables verified.")

        # Create escalation reminders table
        try:
            from core.escalation import ensure_escalation_tables
            await ensure_escalation_tables(self._pg_dsn)
        except Exception:
            _log.warning("Escalation table creation skipped.")

        # Seed template data from catalog (idempotent)
        try:
            from tools.template_tools import seed_templates
            inserted = await seed_templates(self._port)
            if inserted > 0:
                _log.info("Seeded %d ticket template(s)", inserted)
        except Exception:
            _log.warning("Template seeding skipped — backend may not be ready yet.")

    # ── SLA scan ────────────────────────────────────────────────────────────

    async def _scan_sla_alerts(self) -> int:
        """
        Queries the ticket backend for SLA-critical tickets and stores new alerts.

        A ticket is considered SLA-critical when:
          - deadline_date is in the past  → alert_type = 'expired'
          - deadline_date <= now + 30 min → alert_type = 'expires_soon'

        Already-alerted tickets (same ticket_id + still unacknowledged) are
        skipped to avoid flooding the alerts table.

        Returns:
            Number of new alerts created (0 if nothing new).
        """
        try:
            tickets = await self._port.get_all_tickets(filters=None, limit=200)
        except Exception:
            _log.debug("SLA scan: backend unreachable — skipping cycle")
            return 0

        if not tickets:
            return 0

        now = datetime.now(timezone.utc)
        threshold = now + timedelta(minutes=30)
        inserted = 0

        async with await psycopg.AsyncConnection.connect(self._pg_dsn) as conn:
            for ticket in tickets:
                deadline_str = ticket.get("deadline_date")
                if not deadline_str:
                    continue  # Ticket has no SLA deadline — skip

                # Parse deadline (ISO 8601 with or without timezone)
                deadline = _parse_iso(deadline_str, now)
                if deadline is None:
                    continue

                # Classify
                if deadline < now:
                    alert_type = "expired"
                elif deadline <= threshold:
                    alert_type = "expires_soon"
                else:
                    continue  # Not critical yet

                ticket_id_num = _extract_id(ticket)
                if ticket_id_num is None:
                    continue

                ticket_name = ticket.get("name", str(ticket_id_num))

                # Dedup: skip if an unacknowledged alert already exists for this ticket
                existing = await conn.execute(
                    "SELECT 1 FROM sla_alerts "
                    "WHERE ticket_id = %s AND alert_type = %s AND acknowledged_by IS NULL "
                    "LIMIT 1",
                    [ticket_id_num, alert_type],
                )
                if await existing.fetchone():
                    continue

                # Resolve assignee name
                assignee = ticket.get("asignado_a")
                assigned_id = None
                assigned_name = None
                if isinstance(assignee, (list, tuple)) and len(assignee) >= 2:
                    assigned_id = assignee[0]
                    assigned_name = assignee[1]

                # Insert alert
                await conn.execute(
                    """
                    INSERT INTO sla_alerts
                        (ticket_id, ticket_name, alert_type, deadline,
                         assigned_to, assigned_name)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """,
                    [ticket_id_num, ticket_name, alert_type, deadline,
                     assigned_id, assigned_name],
                )
                inserted += 1

        if inserted:
            await conn.commit()
            _log.info("SLA scan: %d new alert(s)", inserted)
        else:
            _log.debug("SLA scan: 0 alerts — all tickets within SLA or no SLA configured")

        return inserted

    # ── Public helpers ──────────────────────────────────────────────────────

    async def get_unacknowledged_count(self) -> int:
        """Returns count of unacknowledged SLA alerts for supervisor context."""
        if not self._table_ready or not self._pg_dsn:
            return 0
        try:
            async with await psycopg.AsyncConnection.connect(self._pg_dsn) as conn:
                row = await conn.execute(
                    "SELECT COUNT(*) FROM sla_alerts WHERE acknowledged_by IS NULL"
                )
                count = (await row.fetchone())[0]
            return count
        except Exception:
            _log.debug("Could not query sla_alerts — table may not exist yet")
            return 0


# ── Module-level helpers ────────────────────────────────────────────────────

def _parse_iso(value: str, fallback_tz=timezone.utc) -> datetime | None:
    """Parses an ISO datetime string with optional timezone into a datetime object."""
    if not value:
        return None
    raw = str(value).strip()
    # Normalise trailing Z → +00:00
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=fallback_tz)
        return dt
    except (ValueError, TypeError):
        return None


def _extract_id(ticket: dict) -> int | None:
    """Extracts the numeric ticket ID from a ticket dict (Odoo or Express format)."""
    tid = ticket.get("id")
    if tid is not None:
        try:
            return int(tid)
        except (TypeError, ValueError):
            pass

    # Fallback: try to parse from ticket_name (e.g. "INC-002839" → 2839)
    name = ticket.get("name", "")
    if isinstance(name, str) and name.upper().startswith(("INC-", "SR-", "TCK-")):
        try:
            return int(name.split("-", 1)[1])
        except (IndexError, ValueError):
            pass

    return None
