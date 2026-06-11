"""
POST /agent/invoke — A2A (agent-to-agent) endpoint.

Designed for machine-to-machine calls from an orchestrating agent.
NO LLM in the call path — intent maps directly to port method calls.
Stateless: each call is independent, no conversation memory.

Valid intents and their required parameters:
    create_ticket       → payload dict (Odoo fields), user_id
    get_tickets         → user_id (returns tickets created by user)
    get_assigned        → user_id (returns tickets assigned to user)
    get_all_tickets     → optional filters dict
    get_ticket_detail   → ticket_id, user_id, role
    resolve_ticket      → ticket_id, motivo_resolucion, causa_raiz, user_id
    assign_ticket       → ticket_id, assignee_id, agent_group_id, user_id
    reopen_ticket       → ticket_id, reason, user_id
    approve_ticket      → ticket_id, user_id
    reject_ticket       → ticket_id, reason, user_id
    search_solutions    → description, category (optional)
    get_catalog         → catalog_name: types|categories|urgency|impact|priority|stages

ARCHITECTURE NOTE (Fase 8 — async migration):
    All port methods are async (httpx.AsyncClient). The intent handlers
    here must `await` them. Returning a coroutine without awaiting causes
    PydanticSerializationError ("Unable to serialize unknown type: coroutine").
"""

import inspect
from fastapi import APIRouter, HTTPException
from api.schemas.invoke import InvokeRequest, InvokeResponse
from core.context import current_user_id, current_user_role
import tools.ticket_tools as tt
import tools.rag_tools as rt
import tools.user_tools as ut

router = APIRouter()


# ── user_id validation ─────────────────────────────────────────────────────


def _validate_body_match(request: InvokeRequest) -> None:
    """Verify body user_id/role match the JWT claims."""
    token_uid = current_user_id.get(0)
    token_role = current_user_role.get("")
    if token_uid and request.user_id != token_uid:
        raise HTTPException(status_code=403,
                            detail=f"user_id mismatch: token={token_uid} body={request.user_id}")
    if token_role and request.user_rol != token_role:
        raise HTTPException(status_code=403,
                            detail=f"role mismatch: token={token_role} body={request.user_rol}")


# ── Intent dispatch table ─────────────────────────────────────────────────────
# All handlers are async because the underlying port methods are async (Fase 8).

async def _intent_create_ticket(p: dict, uid: int):
    return await tt._port.create_ticket(p, uid)


async def _intent_get_tickets(p: dict, uid: int):
    return await tt._port.get_tickets_by_creator(uid)


async def _intent_get_assigned(p: dict, uid: int):
    return await tt._port.get_tickets_by_assignee(uid)


async def _intent_get_all_tickets(p: dict, uid: int):
    return await tt._port.get_all_tickets(p.get("filters", {}))


async def _intent_get_ticket_detail(p: dict, uid: int):
    return await tt._port.get_ticket_detail(
        p["ticket_id"], uid, p.get("role", "creador")
    )


async def _intent_resolve_ticket(p: dict, uid: int):
    return await tt._port.resolve_ticket(
        p["ticket_id"],
        p["motivo_resolucion"],
        p.get("causa_raiz", ""),
        uid,
    )


async def _intent_assign_ticket(p: dict, uid: int):
    return await tt._port.assign_ticket(
        p["ticket_id"],
        p["assignee_id"],
        p.get("agent_group_id", 0),
        uid,
    )


async def _intent_reopen_ticket(p: dict, uid: int):
    return await tt._port.reopen_ticket(p["ticket_id"], p.get("reason", ""), uid)


async def _intent_approve_ticket(p: dict, uid: int):
    return await tt._port.approve_ticket(p["ticket_id"], uid)


async def _intent_reject_ticket(p: dict, uid: int):
    return await tt._port.reject_ticket(
        p["ticket_id"], p.get("reason", ""), uid
    )


async def _intent_search_solutions(p: dict, uid: int):
    result = await rt._rag_port.search_similar(
        query=p["description"],
        category=p.get("category"),
    )
    return {
        "solutions_found": result.solutions_found,
        "confidence": result.confidence,
        "solutions": [
            {
                "ticket_name": s.ticket_name,
                "category": s.category,
                "description": s.description,
                "motivo_resolucion": s.motivo_resolucion,
                "score": s.score,
            }
            for s in result.solutions
        ],
    }


async def _intent_get_catalog(p: dict, uid: int):
    name = p.get("catalog_name", "")
    catalogs = {
        "types":      ut._port.get_ticket_types,
        "categories": lambda: ut._port.get_categories(p.get("parent_id")),
        "urgency":    ut._port.get_urgency_levels,
        "impact":     ut._port.get_impact_levels,
        "priority":   ut._port.get_priority_levels,
        "stages":     ut._port.get_stages,
        "groups":     ut._port.get_agent_groups,
        "resolvers":  ut._port.get_resolvers,
    }
    handler = catalogs.get(name)
    if not handler:
        raise ValueError(f"Unknown catalog '{name}'. Valid: {list(catalogs.keys())}")
    # All port methods are async since Fase 8 — await the coroutine
    return await handler()


INTENT_MAP = {
    "create_ticket":    _intent_create_ticket,
    "get_tickets":      _intent_get_tickets,
    "get_assigned":     _intent_get_assigned,
    "get_all_tickets":  _intent_get_all_tickets,
    "get_ticket_detail":_intent_get_ticket_detail,
    "resolve_ticket":   _intent_resolve_ticket,
    "assign_ticket":    _intent_assign_ticket,
    "reopen_ticket":    _intent_reopen_ticket,
    "approve_ticket":   _intent_approve_ticket,
    "reject_ticket":    _intent_reject_ticket,
    "search_solutions": _intent_search_solutions,
    "get_catalog":      _intent_get_catalog,
}


@router.post("/agent/invoke", response_model=InvokeResponse)
async def invoke(request: InvokeRequest) -> InvokeResponse:
    _validate_body_match(request)

    handler = INTENT_MAP.get(request.intent)

    if not handler:
        return InvokeResponse(
            status="error",
            result={},
            message=(
                f"Unknown intent: '{request.intent}'. "
                f"Valid intents: {list(INTENT_MAP.keys())}"
            ),
        )

    try:
        result = await handler(request.parameters, request.user_id)
        return InvokeResponse(
            status="success",
            result=result if isinstance(result, dict) else {"data": result},
            message="Executed successfully",
        )
    except KeyError as e:
        return InvokeResponse(
            status="error",
            result={},
            message=f"Missing required parameter: {e}",
        )
    except Exception as e:
        return InvokeResponse(
            status="error",
            result={},
            message=str(e),
        )
