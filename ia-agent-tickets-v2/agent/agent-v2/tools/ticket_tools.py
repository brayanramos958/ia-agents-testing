"""
Ticket operation tools for the LangGraph agent.

Tools delegate to ITicketPort — they never call any HTTP endpoint directly.
Each role gets a different subset via get_*_tools() functions.

Delete is implemented here but EXCLUDED from all tool lists.
"""

import json
import re as _re
from typing import Optional, Union

import httpx
from langchain_core.tools import tool
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_not_exception_type
from ports.ticket_port import ITicketPort
from ports.rag_port import IRAGPort
from core.security import wrap_external_data  # Capa 3: framing anti-inyección

# Errores que indican backend caído — no tiene sentido reintentar.
_BACKEND_DOWN_ERRORS = (
    ConnectionError,
    ConnectionRefusedError,
    httpx.ConnectError,
    httpx.RemoteProtocolError,
)

# Patrón Resiliencia: Reintenta hasta 3 veces ante intermitencias transitorias.
# No reintenta si el backend está claramente caído (errores de conexión).
backend_retry = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_not_exception_type(_BACKEND_DOWN_ERRORS),
    reraise=True
)

# Injected at application startup via set_ticket_port()
_port: ITicketPort = None
_rag_port: IRAGPort = None


async def _resolve_id(value: str, field: str, catalog_fn) -> int:
    """
    Resolves a catalog field value to a numeric ID.

    - If value is already numeric: converts and returns directly (zero overhead).
    - If value is a name string: searches the catalog by name (case-insensitive)
      and returns the matching ID without an extra LLM round-trip.
    - If the name is not found in the catalog: raises ValueError with the
      available options so the error is actionable.
    """
    try:
        return int(value)
    except (ValueError, TypeError):
        items = await catalog_fn()
        name_lower = str(value).lower().strip()
        match = next(
            (item for item in items if item.get("name", "").lower().strip() == name_lower),
            None,
        )
        if match:
            return match["id"]
        available = [item.get("name", "") for item in items]
        raise ValueError(
            f"'{field}': '{value}' no es un ID numérico ni coincide con ningún valor "
            f"del catálogo. Opciones disponibles: {available}"
        )


def _slim_ticket(t: dict) -> dict:
    """Returns only key fields for list views — keeps tool responses compact.
    FASE 4: includes SLA and approval fields for dashboard visibility."""
    stage = t.get("stage_id")
    return {
        "id":      t.get("id"),
        "name":    t.get("name"),
        "asunto":  t.get("asunto"),
        "stage":   stage[1] if isinstance(stage, list) and len(stage) > 1 else stage,
        "urgency": t.get("urgency_id"),
        "sla_status":       t.get("sla_status"),
        "is_about_to_expire": t.get("is_about_to_expire"),
        "deadline_date":    t.get("deadline_date"),
        "approval_status":  t.get("approval_status"),
    }


def _parse_ticket_id(value: Union[int, str]) -> int:
    """Accepts numeric ID (5) or ticket name with any prefix ('TCK-0005', 'ITS-00010', 'INC-00008', 'SR-00007') → returns int."""
    try:
        candidate = int(value)
        if candidate > 0:
            return candidate
    except (ValueError, TypeError):
        pass

    s = str(value).strip().upper()
    # Accept any alphanumeric prefix: TCK-, ITS-, INC-, SR-, etc.
    match = _re.match(r"^[A-Z]+-(\d+)$", s)
    if match:
        return int(match.group(1))
    raise ValueError(
        f"ticket_id '{value}' no es válido. "
        "Usa el ID numérico positivo (ej: 5) o el nombre completo (ej: ITS-00010, INC-00008, SR-00007)."
    )


def _safe_uid(llm_provided) -> int:
    """
    Returns the authenticated user_id from the request context.
    Falls back to the LLM-provided value only in test environments where
    the context var was never set (default=0 signals no active request).
    This prevents a malicious prompt from making the LLM impersonate another user.
    """
    from core.context import current_user_id as _uid_var
    ctx = _uid_var.get()
    return ctx if ctx else int(llm_provided)


def set_ticket_port(port: ITicketPort) -> None:
    global _port
    _port = port


def set_rag_port_for_tickets(rag_port: IRAGPort) -> None:
    """Provides RAG access so resolve_ticket can update the knowledge base."""
    global _rag_port
    _rag_port = rag_port


# ── Creator tools ─────────────────────────────────────────────────────────────

@tool
@backend_retry
async def create_ticket(
    asunto: str,
    ticket_type_id: Union[int, str],
    category_id: Union[int, str],
    urgency_id: Union[int, str],
    impact_id: Union[int, str],
    priority_id: Union[int, str],
    user_id: Union[int, str],
    descripcion: str = "",
    subcategory_id: Optional[Union[int, str]] = None,
    element_id: Optional[Union[int, str]] = None,
    system_equipment: str = "",
    origin_id: Optional[Union[int, str]] = None,
    affected_user_name: str = "",
    contact_info: str = "",
    anydesk_id: str = "",
    availability_datetime: str = "",
    requester_type: str = "",
) -> dict:
    """
    Creates a new support ticket.
    IMPORTANT: Always call suggest_solution BEFORE this tool.
    Only call this if the user confirmed no existing solution worked,
    or if no solution was found.

    Args:
        asunto: Short title of the ticket (required)
        descripcion: Full problem description (required)
        ticket_type_id: ID from get_ticket_types() (required)
        category_id: L1 category ID from get_categories() (required)
        urgency_id: ID from get_urgency_levels() (required)
        impact_id: ID from get_impact_levels() (required)
        priority_id: ID from get_priority_levels() (required)
        user_id: Current user's ID (required)
        subcategory_id: L2 category ID (optional)
        element_id: L3 category ID (optional)
        system_equipment: Device or software name affected (optional).
                         The adapter appends this to descripcion — it is not
                         a standalone Odoo field.
        origin_id: ID from get_origins() — how the ticket was reported (optional)
        affected_user_name: Name of the affected user if different from requester (optional)
        contact_info: Phone extension, alternative email for contact (optional)
        anydesk_id: AnyDesk remote access code (optional)
        availability_datetime: When the user is available for support (optional, ISO datetime)
        requester_type: 'internal' or 'external' (optional)
    """
    payload = {
        "asunto": asunto,
        "descripcion": descripcion,
        "ticket_type_id": await _resolve_id(ticket_type_id, "ticket_type_id", _port.get_ticket_types),
        "category_id":    await _resolve_id(category_id,    "category_id",    _port.get_categories),
        "subcategory_id": await _resolve_id(subcategory_id, "subcategory_id", _port.get_categories) if subcategory_id else None,
        "element_id":     await _resolve_id(element_id,     "element_id",     _port.get_categories) if element_id     else None,
        "urgency_id":     await _resolve_id(urgency_id,     "urgency_id",     _port.get_urgency_levels),
        "impact_id":      await _resolve_id(impact_id,      "impact_id",      _port.get_impact_levels),
        "priority_id":    await _resolve_id(priority_id,    "priority_id",    _port.get_priority_levels),
        "system_equipment": system_equipment,
    }
    # FASE 3: solicitud fields
    if origin_id:
        payload["origin_id"] = await _resolve_id(origin_id, "origin_id", _port.get_origins)
    if affected_user_name:
        payload["affected_user_name"] = affected_user_name
    if contact_info:
        payload["contact_info"] = contact_info
    if anydesk_id:
        payload["anydesk_id"] = anydesk_id
    if availability_datetime:
        payload["availability_datetime"] = availability_datetime
    if requester_type:
        payload["requester_type"] = requester_type

    result = await _port.create_ticket(payload, _safe_uid(user_id))

    # ── MON-1 auto-track: record every ticket created via SARA ──────────
    # Runs after create_ticket succeeds. Rating is None — the user may
    # update it later via record_agent_feedback. Errors are swallowed so
    # they never block the main flow.
    if result.get("success") and result.get("ticket_id"):
        try:
            from feedback.collector import FeedbackCollector
            collector = FeedbackCollector()
            await collector.record(
                ticket_id=result["ticket_id"],
                user_id=_safe_uid(user_id),
                rating=None,
                comment="Auto-tracked: ticket created via SARA",
                feedback_type="ticket_created",
                ticket_name=result.get("ticket_name", asunto),
            )
        except Exception:
            pass  # tracking failure must never block the ticket creation

    return result


@tool
@backend_retry
async def get_my_created_tickets(user_id: Union[int, str]) -> list:
    """
    Returns the most recent tickets created by the current user (up to 10).
    Shows: ticket name, subject, stage, urgency.
    For full details on a specific ticket, use get_ticket_detail.
    """
    tickets = await _port.get_tickets_by_creator(_safe_uid(user_id))
    limited = tickets[-10:] if len(tickets) > 10 else tickets
    result = [_slim_ticket(t) for t in limited]
    if len(tickets) > 10:
        result.append({"_note": f"Showing last 10 of {len(tickets)} tickets."})
    return result


# ── Dashboard tools (pre-processed summaries — saves tokens) ─────────────────

@tool
@backend_retry
async def get_resolver_dashboard(user_id: Union[int, str]) -> dict:
    """
    Returns a SUMMARY of the resolver's assigned tickets with team context.
    Use this FIRST before listing individual tickets — saves tokens.
    
    Returns:
        total: tickets assigned to you
        group_name: your team name (e.g. "Agentes SARA")
        group_total: total tickets in your team (all members)
        my_count: your tickets (same as total)
        sla_failed / sla_about_to_expire: SLA risk counts
        pending_approval: tickets blocked by supervisor
        ready: tickets you can work on now
        by_category: {category_name: count} breakdown
        by_urgency: {urgency_level: count} breakdown
        urgent_sample: top 5 most urgent tickets (slim)
    """
    uid = _safe_uid(user_id)
    tickets = await _port.get_tickets_by_assignee(uid)
    
    sla_failed = sum(1 for t in tickets if t.get("sla_status") == "failed")
    sla_expiring = sum(1 for t in tickets if t.get("is_about_to_expire"))
    pending_approval = sum(1 for t in tickets if t.get("approval_status") == "pending")
    ready = len(tickets) - pending_approval
    
    # ── Group context: find the resolver's group and count team tickets ──
    group_name = ""
    group_total = 0
    if tickets:
        first = tickets[0]
        g = first.get("agent_group_id", "")
        if isinstance(g, (list, tuple)) and len(g) >= 2:
            group_name = str(g[1])
            group_id = g[0]
        elif g:
            group_name = str(g)
            group_id = g
        else:
            group_id = None
        
        if group_name and group_id:
            try:
                group_tickets = await _port.get_all_tickets({"agent_group_id": group_id}, limit=1000)
                group_total = len(group_tickets)
            except Exception:
                group_total = 0
    
    # ── By category ──
    by_category = {}
    for t in tickets:
        cat = t.get("category_id", "")
        if isinstance(cat, (list, tuple)) and len(cat) >= 2:
            cat = str(cat[1])
        else:
            cat = str(cat) if cat else "Sin categoría"
        by_category[cat] = by_category.get(cat, 0) + 1
    
    # ── By urgency ──
    by_urgency = {}
    for t in tickets:
        urg = t.get("urgency_id", "")
        if isinstance(urg, (list, tuple)) and len(urg) >= 2:
            urg = str(urg[1])
        else:
            urg = str(urg) if urg else "Desconocida"
        by_urgency[urg] = by_urgency.get(urg, 0) + 1
    
    urgent = sorted(
        [t for t in tickets if t.get("sla_status") == "failed" or t.get("is_about_to_expire")],
        key=lambda t: (t.get("sla_status") != "failed", t.get("is_about_to_expire", False)),
    )[:5]
    
    return {
        "total": len(tickets),
        "group_name": group_name,
        "group_total": group_total,
        "my_count": len(tickets),
        "sla_failed": sla_failed,
        "sla_about_to_expire": sla_expiring,
        "pending_approval": pending_approval,
        "ready": ready,
        "by_category": by_category,
        "by_urgency": by_urgency,
        "urgent_sample": [_slim_ticket(t) for t in urgent] if urgent else [],
    }


@tool
@backend_retry
async def get_creator_dashboard(user_id: Union[int, str]) -> dict:
    """
    Returns a SUMMARY of the creator's tickets grouped by status.
    Use this FIRST to show the user their ticket situation — saves tokens.
    
    Returns:
        total: total tickets created
        resueltos: tickets already resolved (good news!)
        en_progreso: tickets being worked on
        abiertos: tickets just created, not yet assigned
        pendiente_aprobacion: tickets waiting for supervisor/jefe approval
        ultimo_resuelto: most recently resolved ticket {name, asunto} or null
    """
    uid = _safe_uid(user_id)
    tickets = await _port.get_tickets_by_creator(uid)
    
    resueltos = 0
    en_progreso = 0
    abiertos = 0
    pendiente = 0
    ultimo_resuelto = None
    
    for t in tickets:
        stage = t.get("stage_id", "")
        if isinstance(stage, (list, tuple)) and len(stage) >= 2:
            stage_name = str(stage[1]).lower()
        else:
            stage_name = str(stage).lower()
        
        approval = str(t.get("approval_status", "")).lower()
        
        if "resuelto" in stage_name or "cerrado" in stage_name:
            resueltos += 1
            if ultimo_resuelto is None:
                ultimo_resuelto = {
                    "name": t.get("name", ""),
                    "asunto": t.get("asunto", ""),
                }
        elif approval == "pending":
            pendiente += 1
        elif "abierto" in stage_name:
            abiertos += 1
        else:
            en_progreso += 1
    
    return {
        "total": len(tickets),
        "resueltos": resueltos,
        "en_progreso": en_progreso,
        "abiertos": abiertos,
        "pendiente_aprobacion": pendiente,
        "ultimo_resuelto": ultimo_resuelto,
    }


@tool
@backend_retry
async def get_supervisor_dashboard() -> dict:
    """
    Returns a SUMMARY of all tickets grouped by team and status (counts only).
    Use this FIRST as the supervisor dashboard — saves tokens.
    
    Returns:
        total: total tickets in system
        by_team: {group_name: count} grouped by agent_group_id
        by_sla: {status: count} SLA breakdown
        pending_approval: count waiting for approval
        urgent_sample: top 5 tickets with SLA breached or expiring
    """
    tickets = await _port.get_all_tickets({}, limit=1000)
    
    by_team = {}
    for t in tickets:
        group = t.get("agent_group_id", "")
        if isinstance(group, (list, tuple)) and len(group) >= 2:
            group = str(group[1])
        else:
            group = str(group) if group else "Sin asignar"
        by_team[group] = by_team.get(group, 0) + 1
    
    by_sla = {}
    for t in tickets:
        status = t.get("sla_status") or "unknown"
        by_sla[status] = by_sla.get(status, 0) + 1
    
    pending_approval = sum(1 for t in tickets if t.get("approval_status") == "pending")
    
    urgent = sorted(
        [t for t in tickets if t.get("sla_status") == "failed" or t.get("is_about_to_expire")],
        key=lambda t: (t.get("sla_status") != "failed",),
    )[:5]
    
    return {
        "total": len(tickets),
        "by_team": by_team,
        "by_sla": by_sla,
        "pending_approval": pending_approval,
        "urgent_sample": [_slim_ticket(t) for t in urgent] if urgent else [],
    }


# ── Resolver tools ────────────────────────────────────────────────────────────

@tool
@backend_retry
async def get_my_assigned_tickets(user_id: Union[int, str]) -> list:
    """
    Returns tickets currently assigned to the current resolver (up to 10).
    Shows: ticket name, subject, stage, urgency.
    For full details on a specific ticket, use get_ticket_detail.
    """
    tickets = await _port.get_tickets_by_assignee(_safe_uid(user_id))
    limited = tickets[-10:] if len(tickets) > 10 else tickets
    result = [_slim_ticket(t) for t in limited]
    if len(tickets) > 10:
        result.append({"_note": f"Showing last 10 of {len(tickets)} tickets."})
    return result


@tool
@backend_retry
async def resolve_ticket(
    ticket_id: Union[int, str],
    motivo_resolucion: str,
    causa_raiz: str,
    user_id: Union[int, str],
) -> dict:
    """
    Marks a ticket as resolved.
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID
        motivo_resolucion: Full description of how the problem was resolved
        causa_raiz: Root cause explanation (what caused the problem)
        user_id: Current resolver's user ID
    """
    uid = _safe_uid(user_id)
    tid = _parse_ticket_id(ticket_id)
    result = await _port.resolve_ticket(tid, motivo_resolucion, causa_raiz, uid)

    if result.get("success") and _rag_port:
        ticket = await _port.get_ticket_detail(tid, uid, "resueltor")
        await _rag_port.add_resolved_ticket(
            ticket_id=tid,
            ticket_name=ticket.get("name") or f"TCK-{tid:04d}",
            ticket_type=ticket.get("ticket_type") or ticket.get("tipo_requerimiento", ""),
            category=ticket.get("category") or ticket.get("categoria", ""),
            description=ticket.get("descripcion", ""),
            motivo_resolucion=motivo_resolucion,
            causa_raiz=causa_raiz,
        )

    return result


# ── Shared tools (all roles) ──────────────────────────────────────────────────

@tool
@backend_retry
async def get_ticket_detail(ticket_id: Union[int, str], user_id: Union[int, str], user_role: str) -> dict:
    """
    Returns full details of a specific ticket.
    Includes: all fields, SLA status, deadline, stage, assignment info.
    
    If the ticket has ticket_parent_id, it is a child of another ticket (main problem).
    If it has ticket_child_ids, it has sub-tickets (related incidents).
    When a parent ticket is resolved, all children are auto-resolved in cascade.

    After calling this, proactively call suggest_solution
    using the ticket's description and category.
    """
    return wrap_external_data(
        await _port.get_ticket_detail(_parse_ticket_id(ticket_id), _safe_uid(user_id), user_role)
    )


@tool
@backend_retry
async def update_ticket(ticket_id: Union[int, str], fields_json: str, user_id: Union[int, str]) -> dict:
    """
    Updates specific fields of a ticket.
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID
        fields_json: JSON string of fields to update using Odoo technical names.
                     Example: '{"asunto": "New title", "system_equipment": "Laptop HP"}'
        user_id: Current user's ID
    """
    try:
        fields = json.loads(fields_json)
    except json.JSONDecodeError as e:
        return {"success": False, "error": f"Invalid JSON in fields_json: {e}"}
    return await _port.update_ticket(_parse_ticket_id(ticket_id), fields, _safe_uid(user_id))


# ── Supervisor tools ──────────────────────────────────────────────────────────

@tool
@backend_retry
async def get_all_tickets(filters_json: str = "{}", limit: int = 15, offset: int = 0) -> list:
    """
    Returns paginated tickets for supervisors, ordered by creation date (most recent first).
    
    Args:
        filters_json: JSON string with Odoo field filters.
                      Example: '{"stage_id": 1}' to filter by stage.
        limit:  Max tickets to return (default 15). Use higher values for more.
        offset: Skip N tickets for pagination. offset=15 = page 2.

    The response includes a _pagination note when there might be more results.
    """
    try:
        filters = json.loads(filters_json)
    except json.JSONDecodeError:
        filters = {}
    
    tickets = await _port.get_all_tickets(filters, limit=limit + 1, offset=offset)
    
    # Check if there are more tickets beyond this page
    has_more = len(tickets) > limit
    if has_more:
        tickets = tickets[:limit]
    
    result = [_slim_ticket(t) for t in tickets]
    
    if has_more:
        result.append({
            "_pagination": f"Showing {limit} of many tickets (offset={offset}). "
            f"Use offset={offset + limit} for the next page."
        })
    
    return result


@tool
@backend_retry
async def assign_ticket(
    ticket_id: Union[int, str],
    assignee_id: Union[int, str],
    agent_group_id: Union[int, str],
    user_id: Union[int, str],
) -> dict:
    """
    Assigns a ticket to a resolver agent.
    Always show the list of resolvers (get_resolvers) before calling this.
    Confirm with the user before assigning.

    Args:
        ticket_id: Numeric ticket ID
        assignee_id: ID of the resolver to assign (from get_resolvers)
        agent_group_id: ID of the agent group (from get_agent_groups)
        user_id: Current supervisor's user ID
    """
    return await _port.assign_ticket(_parse_ticket_id(ticket_id), int(assignee_id), int(agent_group_id), _safe_uid(user_id))


@tool
@backend_retry
async def reopen_ticket(ticket_id: Union[int, str], reason: str, user_id: Union[int, str]) -> dict:
    """
    Reopens a resolved or closed ticket.
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID
        reason: Reason for reopening the ticket
        user_id: Current supervisor's user ID
    """
    return await _port.reopen_ticket(_parse_ticket_id(ticket_id), reason, _safe_uid(user_id))


@tool
@backend_retry
async def approve_ticket(ticket_id: Union[int, str], user_id: Union[int, str]) -> dict:
    """
    Approves a pending ticket so the resolver can proceed with it.
    Only valid for tickets with approval_status: "pending".
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID
        user_id: Current supervisor's user ID
    """
    return await _port.approve_ticket(_parse_ticket_id(ticket_id), _safe_uid(user_id))


@tool
@backend_retry
async def reject_ticket(
    ticket_id: Union[int, str],
    reason: str,
    user_id: Union[int, str],
) -> dict:
    """
    Rejects a pending ticket. The resolver will be notified it does not proceed.
    Only valid for tickets with approval_status: "pending".
    Always confirm with the user before calling this.

    Args:
        ticket_id: Numeric ticket ID
        reason: Clear explanation of why the ticket is rejected
        user_id: Current supervisor's user ID
    """
    return await _port.reject_ticket(_parse_ticket_id(ticket_id), reason, _safe_uid(user_id))


# ── Delete — implemented but excluded from all tool lists ─────────────────────

@backend_retry
async def delete_ticket(ticket_id: str, user_id: str) -> dict:
    """Permanently deletes a ticket. Supervisor only."""
    return await _port.delete_ticket(int(ticket_id), int(user_id))

# SECURITY: delete_ticket is implemented above but intentionally excluded from
# all role tool lists (get_creator_tools, get_resolver_tools, get_supervisor_tools).
# To enable deletion: add the @tool decorator to delete_ticket and include it
# in get_supervisor_tools() AFTER an authorization layer is implemented.


# ── FASE 2: Approval lines tool ─────────────────────────────────────────────

@tool
@backend_retry
async def get_approval_lines(ticket_id: Union[int, str]) -> list:
    """
    Returns all approval lines for a ticket (multi-approver system).
    Shows who approved/rejected, when, and what role they have.
    For supervisor use before approve_ticket or reject_ticket.

    Args:
        ticket_id: Numeric ticket ID
    """
    return await _port.get_approval_lines(_parse_ticket_id(ticket_id))


# ── FASE 3: Origins catalog tool ────────────────────────────────────────────

@tool
@backend_retry
async def get_origins() -> list:
    """
    Returns all available ticket origins (email, phone, web, in-person).
    Each item: {"id": int, "name": str, "description": str}
    """
    return await _port.get_origins()


# ── FASE 4: Audit log tool ─────────────────────────────────────────────────

@tool
@backend_retry
async def get_ticket_logs(ticket_id: Union[int, str], limit: int = 50) -> list:
    """
    Returns the complete audit history for a ticket.
    Shows: stage changes, assignments, field changes, messages, notifications.
    For supervisor tracking and auditing.

    Args:
        ticket_id: Numeric ticket ID
        limit: Max number of log entries to return (default 50)
    """
    return await _port.get_ticket_logs(_parse_ticket_id(ticket_id), limit)


# ── FASE 4: Knowledge base tool ─────────────────────────────────────────────

@tool
@backend_retry
async def get_knowledge_articles(query: str, limit: int = 10) -> list:
    """
    Searches the knowledge base for articles matching the query.
    Searches by title, keywords, and content.
    Useful for finding documented solutions and procedures.

    Args:
        query: Search terms to find relevant articles
        limit: Max number of results (default 10)
    """
    return wrap_external_data(await _port.get_knowledge_articles(query, limit))


# ── Internal notes ────────────────────────────────────────────────────────────

@tool
@backend_retry
async def add_note_to_ticket(
    ticket_id: Union[int, str],
    note: str,
    user_id: Union[int, str],
) -> dict:
    """
    Adds an internal note (comment) to a ticket WITHOUT changing its state.
    
    Use this to leave documentation, progress updates, or diagnostic notes
    for other agents/supervisors. The note is internal — NOT visible to the
    end user who created the ticket.
    
    NEVER call this to communicate with the end user — use your regular
    text response for that.

    Args:
        ticket_id: Numeric ticket ID
        note: Plain text content of the internal note
        user_id: Your user ID (the note author)

    Returns:
        {"success": True, "message_id": int} or {"success": False, "error": str}
    """
    return await _port.add_note(_parse_ticket_id(ticket_id), note, _safe_uid(user_id))


# ── Incident detection (Fase 4) ───────────────────────────────────────────────

# Spanish stopwords for keyword extraction (subset)
_STOPWORDS_ES_TICKETS = {
    "que", "los", "las", "por", "del", "una", "con", "para", "como", "más",
    "pero", "sus", "fue", "este", "esta", "hay", "sin", "nos", "son", "está",
    "era", "sea", "han", "les", "eso", "ese", "muy", "ya", "al", "el", "la",
    "de", "en", "se", "un", "lo", "le", "mi", "su", "es", "no", "si", "me",
    "te", "tu", "ni", "o", "y", "a", "e", "u", "yo", "él", "ella", "todo",
    "sobre", "entre", "donde", "tiene", "puede", "hacer", "hace", "dice",
}

import re as _kw_re

def _extract_keywords_ticket(text: str) -> set[str]:
    """Extract meaningful lowercase keywords from text (spanish aware)."""
    if not text:
        return set()
    clean = _kw_re.sub(r"[^a-záéíóúñü0-9\s]", " ", str(text).lower())
    words = clean.split()
    return {w for w in words if len(w) >= 3 and w not in _STOPWORDS_ES_TICKETS}


@tool
@backend_retry
async def check_similar_open_tickets(problem_description: str) -> dict:
    """
    Checks for open tickets in the system that are similar to the given
    problem description. Detects potential MASSIVE INCIDENTS — when multiple
    users report the same issue independently.

    Use BEFORE assigning tickets. If this finds >2 similar open tickets,
    consider consolidating them as children of a master incident ticket
    instead of creating more duplicates.

    Args:
        problem_description: The problem description to check (from the user's message)

    Returns:
        {
            "alert": bool,               # True if a massive incident is detected
            "similar_count": int,         # Number of similar open tickets found
            "max_shared_keywords": int,   # Highest keyword match count
            "similar_tickets": [          # Up to 5 top matches
                {"name": str, "asunto": str, "stage": str, "shared_keywords": int}
            ],
            "recommendation": str,        # Actionable recommendation
        }
    """
    if not _port:
        return {"alert": False, "similar_count": 0, "error": "Backend no disponible"}

    # Extract keywords from the problem description
    keywords = _extract_keywords_ticket(problem_description)
    if len(keywords) < 2:
        return {
            "alert": False,
            "similar_count": 0,
            "max_shared_keywords": 0,
            "similar_tickets": [],
            "recommendation": "Descripción muy breve para comparar. Procede normalmente.",
        }

    # Get all open tickets
    try:
        all_tickets = await _port.get_all_tickets({}, limit=1000)
    except Exception:
        return {"alert": False, "similar_count": 0, "error": "No se pudo consultar tickets abiertos"}

    # Find tickets with shared keywords
    matches = []
    for ticket in all_tickets:
        asunto = ticket.get("asunto", "")
        ticket_keywords = _extract_keywords_ticket(asunto)
        shared = len(keywords & ticket_keywords)

        if shared >= 2:  # threshold: 2+ shared keywords
            stage = ticket.get("stage_id", "")
            if isinstance(stage, (list, tuple)) and len(stage) >= 2:
                stage = str(stage[1])

            # Only consider truly open (not resolved/closed) tickets
            stage_lower = stage.lower() if isinstance(stage, str) else ""
            if any(w in stage_lower for w in ("resuelto", "cerrado", "cancelado")):
                continue

            matches.append({
                "name": ticket.get("name", "?"),
                "asunto": asunto,
                "stage": stage,
                "shared_keywords": shared,
            })

    # Sort by shared keywords descending
    matches.sort(key=lambda x: -x["shared_keywords"])

    similar_count = len(matches)
    max_shared = matches[0]["shared_keywords"] if matches else 0
    alert = similar_count >= 3  # 3+ similar = incidente masivo

    if alert:
        recommendation = (
            f"⚠️ INCIDENTE MASIVO DETECTADO: {similar_count} tickets abiertos "
            f"comparten {max_shared}+ palabras clave con este problema. "
            "CONSIDERA crear un ticket 'incidente padre' y vincular estos tickets "
            "como hijos (ticket_parent_id). NO asignes más tickets del mismo problema — "
            "consolida."
        )
    elif similar_count >= 1:
        recommendation = (
            f"Se encontraron {similar_count} ticket(s) similares. "
            "Verifica si este es un duplicado antes de asignar un nuevo agente. "
            "Considera vincular como ticket relacionado."
        )
    else:
        recommendation = "No se detectaron incidentes masivos. Procede con la asignación normal."

    return {
        "alert": alert,
        "similar_count": similar_count,
        "max_shared_keywords": max_shared,
        "similar_tickets": matches[:5],  # top 5
        "recommendation": recommendation,
    }


# ── Role-keyed tool sets ──────────────────────────────────────────────────────

def get_creator_tools() -> list:
    """Tools available to users with role 'creador'."""
    return [
        get_creator_dashboard,      # PRIMARY: summary first, saves tokens
        create_ticket,
        get_my_created_tickets,     # drill-down: list individual tickets
        get_ticket_detail,
        update_ticket,
        get_origins,
    ]


def get_resolver_tools() -> list:
    """Tools available to users with role 'resueltor'."""
    return [
        get_resolver_dashboard,     # PRIMARY: summary first, saves tokens
        get_my_assigned_tickets,    # drill-down: list individual tickets
        get_ticket_detail,
        resolve_ticket,
        update_ticket,
        add_note_to_ticket,         # internal notes on assigned tickets
        get_knowledge_articles,
    ]


def get_supervisor_tools() -> list:
    """
    Tools available to users with role 'supervisor'.
    Note: delete_ticket is NOT included — see SECURITY comment above.
    """
    return [
        get_supervisor_dashboard,   # PRIMARY: summary grouped by team, saves tokens
        get_all_tickets,            # drill-down: list individual tickets with filters
        get_ticket_detail,
        assign_ticket,
        reopen_ticket,
        approve_ticket,
        reject_ticket,
        add_note_to_ticket,         # internal notes on any ticket
        check_similar_open_tickets, # detect massive incidents before assignment
        get_approval_lines,
        get_ticket_logs,
        get_knowledge_articles,
    ]
