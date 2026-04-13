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
    search_solutions    → description, category (optional)
    get_catalog         → catalog_name: types|categories|urgency|impact|priority|stages
"""

from fastapi import APIRouter
from api.schemas.invoke import InvokeRequest, InvokeResponse
import tools.ticket_tools as tt
import tools.rag_tools as rt
import tools.user_tools as ut

router = APIRouter()

# ── Intent dispatch table ─────────────────────────────────────────────────────
# Each handler: (parameters: dict, user_id: int) -> any
# The port (_port) is accessed through the tool module's module-level variable,
# which was injected at startup via initialize_ports().

def _intent_create_ticket(p: dict, uid: int):
    return tt._port.create_ticket(p, uid)

def _intent_get_tickets(p: dict, uid: int):
    return tt._port.get_tickets_by_creator(uid)

def _intent_get_assigned(p: dict, uid: int):
    return tt._port.get_tickets_by_assignee(uid)

def _intent_get_all_tickets(p: dict, uid: int):
    return tt._port.get_all_tickets(p.get("filters", {}))

def _intent_get_ticket_detail(p: dict, uid: int):
    return tt._port.get_ticket_detail(
        p["ticket_id"], uid, p.get("role", "creador")
    )

def _intent_resolve_ticket(p: dict, uid: int):
    return tt._port.resolve_ticket(
        p["ticket_id"],
        p["motivo_resolucion"],
        p.get("causa_raiz", ""),
        uid,
    )

def _intent_assign_ticket(p: dict, uid: int):
    return tt._port.assign_ticket(
        p["ticket_id"],
        p["assignee_id"],
        p.get("agent_group_id", 0),
        uid,
    )

def _intent_reopen_ticket(p: dict, uid: int):
    return tt._port.reopen_ticket(p["ticket_id"], p.get("reason", ""), uid)

def _intent_search_solutions(p: dict, uid: int):
    result = rt._rag_port.search_similar(
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

def _intent_get_catalog(p: dict, uid: int):
    name = p.get("catalog_name", "")
    catalogs = {
        "types":      lambda: ut._port.get_ticket_types(),
        "categories": lambda: ut._port.get_categories(p.get("parent_id")),
        "urgency":    lambda: ut._port.get_urgency_levels(),
        "impact":     lambda: ut._port.get_impact_levels(),
        "priority":   lambda: ut._port.get_priority_levels(),
        "stages":     lambda: ut._port.get_stages(),
        "groups":     lambda: ut._port.get_agent_groups(),
        "resolvers":  lambda: ut._port.get_resolvers(),
    }
    handler = catalogs.get(name)
    if not handler:
        raise ValueError(f"Unknown catalog '{name}'. Valid: {list(catalogs.keys())}")
    return handler()


INTENT_MAP = {
    "create_ticket":    _intent_create_ticket,
    "get_tickets":      _intent_get_tickets,
    "get_assigned":     _intent_get_assigned,
    "get_all_tickets":  _intent_get_all_tickets,
    "get_ticket_detail":_intent_get_ticket_detail,
    "resolve_ticket":   _intent_resolve_ticket,
    "assign_ticket":    _intent_assign_ticket,
    "reopen_ticket":    _intent_reopen_ticket,
    "search_solutions": _intent_search_solutions,
    "get_catalog":      _intent_get_catalog,
}


@router.post("/agent/invoke", response_model=InvokeResponse)
def invoke(request: InvokeRequest) -> InvokeResponse:
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
        result = handler(request.parameters, request.user_id)
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
