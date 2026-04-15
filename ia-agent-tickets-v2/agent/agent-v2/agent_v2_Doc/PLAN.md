# Agent v2 — Helpdesk Microservice (Plan)

---

## Estado actual — 2026-04-14

### ✅ Implementado y funcionando (probado en desarrollo)

| Archivo | Estado | Notas |
|---|---|---|
| `config/settings.py` | ✅ funcionando | Pydantic Settings, single source of truth |
| `ports/ticket_port.py` | ✅ funcionando | ITicketPort con nombres Odoo |
| `ports/rag_port.py` | ✅ funcionando | IRAGPort + SuggestionResult |
| `adapters/express_adapter.py` | ✅ funcionando | Adapter de desarrollo contra Express + SQLite |
| `rag/store.py` | ✅ funcionando | ChromaDB seeding desde API REST |
| `rag/embeddings.py` | ✅ funcionando | HuggingFace singleton `all-MiniLM-L6-v2` |
| `tools/ticket_tools.py` | ✅ funcionando | create, get, resolve, assign, reopen, update (delete excluido) |
| `tools/user_tools.py` | ✅ funcionando | catálogos: tipos, categorías 3 niveles, urgencia, impacto, prioridad |
| `tools/rag_tools.py` | ✅ funcionando | suggest_solution_before_ticket + record_agent_feedback |
| `prompts/creator.py` | ✅ funcionando | flujo resolución-primero, categorización L1→L2→L3 |
| `prompts/resolver.py` | ✅ actualizado | verifica `approval_status` antes de resolver; bloquea si pending/rejected |
| `prompts/supervisor.py` | ✅ actualizado | priorización visual por `is_about_to_expire` y `sla_status` |
| `feedback/collector.py` | ✅ funcionando | SQLite-backed, evaluación del agente AI (≠ CSAT del ticket) |
| `core/graph.py` | ✅ funcionando | Groq primario + OpenRouter fallback + AsyncSqliteSaver |
| `core/agent.py` | ✅ actualizado | `_trim_hook` limpia contexto; imports duplicados eliminados |
| `api/routes/chat.py` | ✅ actualizado | sesión diaria: `thread_id = user-{id}-{date.today()}` |
| `api/routes/stream.py` | ✅ nuevo | POST /agent/stream — SSE token a token via `astream_events` |
| `api/routes/invoke.py` | ✅ funcionando | POST /agent/invoke — A2A stateless sin LLM |
| `api/middleware/auth.py` | ✅ funcionando | X-Agent-Key |
| `main.py` | ✅ funcionando | lifespan con RAG seeding resiliente |
| `pyproject.toml` + `uv.lock` | ✅ funcionando | gestionado con uv |

---

### ⚠️ Implementado pero SIN PROBAR en producción (requiere acceso Odoo API)

| Archivo | Estado | Qué falta verificar |
|---|---|---|
| `adapters/odoo_adapter.py` | ⚠️ implementado, no probado | JSON-RPC 2.0 contra Odoo 15; necesita credenciales reales |
| `_text_to_html()` en odoo_adapter | ⚠️ implementado, no probado | Odoo requiere HTML en campos `fields.Html`; no se ha verificado en Odoo real |
| `usuario_solicitante_id` en `create_ticket` | ⚠️ implementado, no probado | Se envía explícitamente; en Odoo lo setea `@api.onchange`, no JSON-RPC |
| `system_equipment` como campo real | ⚠️ implementado, no probado | Es `Char(tracking=True)` en custom, se envía como campo standalone |
| `reopen_ticket` con historial | ⚠️ implementado, no probado | Lee `motivo_resolucion` actual y lo preserva con `<hr/>` separator |
| `approval_status` en `get_ticket_detail` | ⚠️ implementado, no probado | Agregado a fields list; depende de que Odoo lo retorne |
| Campos SLA (`sla_status`, `deadline_date`, `is_about_to_expire`) | ⚠️ implementado, no probado | Stored=True en Odoo; verificar que JSON-RPC los devuelva |

---

### ❌ Pendiente / No implementado

#### En el agente (sin tocar backend):
- [ ] **Historial del usuario en contexto** — antes de sugerir solución, llamar `get_my_created_tickets` y avisar si hay ticket similar abierto en los últimos 7 días (`prompts/creator.py`)
- [ ] **Resumen de conversación en el ticket** — la descripción del ticket debe incluir lo que el usuario dijo con sus palabras, no solo lo que el LLM infirió (`prompts/creator.py`)
- [ ] **Detección de incidentes masivos** — tool `check_similar_open_tickets()` que alerte si >2 usuarios reportaron el mismo problema en 24h (`tools/ticket_tools.py`, `prompts/creator.py`, `prompts/supervisor.py`)
- [ ] **Métricas de deflexión** — endpoint `GET /agent/metrics` con deflection_rate, avg_satisfaction, tickets_deflected (`api/routes/metrics.py`, `feedback/collector.py`)
- [ ] **Escalación a humano** — detectar frustración del usuario y crear ticket urgente con nota interna (`prompts/base.py`, `prompts/creator.py`)
- [ ] **Tool `add_note_to_ticket`** — agregar nota interna a un ticket existente (`tools/ticket_tools.py`)

#### Requieren cambios en Express backend (desarrollo):
- [ ] `GET /api/tickets/:id` — incluir historial de acciones
- [ ] `POST /api/tickets/:id/notes` — agregar notas internas
- [ ] CHECK de `accion` en `ticket_history` — ampliar para incluir `'nota'`

#### Requieren acceso a Odoo API en producción:
- [ ] **Knowledge base de Odoo** — integrar `helpdesk.knowledge` como segunda fuente de RAG (`ports/ticket_port.py`, `adapters/odoo_adapter.py`, `tools/rag_tools.py`)
- [ ] Verificar paginación (`limit`/`offset`) en `get_all_tickets` contra Odoo real
- [ ] Verificar mapping del Chatter de Odoo (`log_ids`/`x_private_note_ids`) a historial del agente
- [ ] `http_adapter.py` — sigue siendo stub; solo `odoo_adapter.py` está implementado

#### Requieren servicios externos (Fase 3):
- [ ] **Alertas proactivas de SLA** — background task + email/Slack/webhook
- [ ] **Multi-canal** — WhatsApp Business API / Teams / Slack
- [ ] **Soporte de adjuntos/imágenes** — upload endpoint + Llama 4 Scout multimodal (ya instalado)

---

### Bugs corregidos en esta sesión (2026-04-14)

| Bug | Archivo | Fix aplicado |
|---|---|---|
| Campos `fields.Html` rechazados por Odoo sin HTML | `odoo_adapter.py` | `_text_to_html()` wrappea texto plano en `<p>` |
| `system_equipment` concatenado a `descripcion` | `odoo_adapter.py` | Se envía como campo standalone |
| `reopen_ticket` borraba historial previo | `odoo_adapter.py` | Lee y preserva `motivo_resolucion` anterior |
| `_trim_hook` tenía `import logging` y `_log` duplicados dentro de la función | `core/agent.py` | Eliminados — ya existen a nivel módulo |
| Sesión permanente acumulaba contexto indefinidamente | `chat.py`, `stream.py` | `thread_id = user-{id}-{date.today()}` |
| `prompts/resolver.py` no verificaba `approval_status` | `prompts/resolver.py` | Bloquea resolución si estado es pending o rejected |

---

## Nota: Adaptadores

> `odoo_adapter.py` usa **JSON-RPC 2.0** (`/web/dataset/call_kw`) — protocolo de Odoo 15 Community.
> NO usa Bearer token (eso es Odoo 17+). Usa session cookie con login previo.
>
> `http_adapter.py` está como stub — documenta los endpoints REST (`/helpdesk/api/v1/`) pero NO está implementado.
> El plan de producción es `odoo_adapter.py`, no `http_adapter.py`.

---

## Nota: Migración de directorio

---

## Nota: Backend futuro (reemplaza Express)

> El backend Express (`backend/`) es solo para desarrollo local.
> El backend de producción será Odoo REST API (ver sección HttpAdapter más abajo).
> **NO agregar lógica de negocio compleja al Express backend** — cualquier campo nuevo
> que se agregue a Express solo debe existir para poder probar el agente. El contrato
> real de campos está definido en `campos-modulo-helpdesk.md`.

---

## API de producción Odoo (del PDF `its_helpdesk_api.pdf`)

**Base URL:** `[dominio]/helpdesk/api/v1`

**Auth — 4 headers obligatorios en CADA request (stateless, sin sesión):**
```
X-Odoo-Db     → nombre exacto de la base de datos
X-Odoo-Login  → correo o login del usuario
X-Api-Key     → contraseña o clave API
Accept        → application/json
```

**Endpoints:**
```
GET  /authenticate        → health check / validar credenciales
GET  /tickets             → listado (params: name, stage_id, limit=80, offset=0)
GET  /ticket/{id}         → detalle completo + Chatter (historial + notas internas)
POST /tickets             → crear ticket  { subject, description }
PATCH /tickets/{id}       → actualizar ticket
```

**Diferencias clave vs Express:**
- Filtros distintos: Odoo usa `name` (referencia exacta) y `stage_id`, no `created_by`
- El `/ticket/{id}` (singular) devuelve el Chatter completo — mapea a `log_ids`/`x_private_note_ids`
- Paginación nativa con `limit` y `offset`

---



## Context

The v1 agent (`ia-agent-tickets-v1/agent/`) works as a demo but has structural coupling that blocks enterprise use:
- Hardcoded absolute filesystem paths
- Reads backend's SQLite directly (violates data ownership)
- No authentication
- Volatile in-memory conversation state
- Mixed Spanish/English code
- No A2A endpoint for agent orchestration
- No human feedback mechanism
- Delete operation exposed without auth

**Goal**: Build `agent-v2/` — a pluggable microservice that enforces resolution-first flow, collects human feedback, supports A2A calls, and is ready for security hardening. V1 stays **untouched**.

The real enterprise target is an **Odoo Helpdesk** instance accessed via its REST API and/or PostgreSQL.
The `ExpressAdapter` is for local development only. `HttpAdapter` (generic) will connect to the real Odoo API.

---

## Real Enterprise Data Model (from campos-modulo-helpdesk.md)

The agent must use the REAL field names of the Odoo Helpdesk model:

### Core ticket fields the agent interacts with:

| Field | Type | Purpose |
|---|---|---|
| `name` | computed | Ticket ID (e.g. TCK-0001) — READ only, auto-generated |
| `asunto` | string | Ticket title/subject |
| `descripcion` | text | Full problem description |
| `ticket_type_id` | FK → catalog | Ticket type (Incidente, Requerimiento, Cambio) |
| `category_id` | FK → category L1 | Primary category |
| `subcategory_id` | FK → category L2 | Subcategory |
| `element_id` | FK → category L3 | Specific element/system affected |
| `urgency_id` | FK → catalog | Urgency level |
| `impact_id` | FK → catalog | Impact level |
| `priority_id` | FK → catalog | Priority (computed from urgency × impact) |
| `stage_id` | FK → stages | Current workflow stage |
| `partner_id` | FK → contact | Requestor (client/employee contact) |
| `usuario_solicitante_id` | FK → user | Internal system user who made the request |
| `affected_user_id` | FK → user | Actual user impacted by the problem |
| `asignado_a` | FK → agent | Assigned specialist |
| `agent_group_id` | FK → group | Support team/level |
| `motivo_resolucion` | text | Resolution description |
| `causa_raiz` | text | Root cause explanation |
| `sla_id` | FK → SLA | Applied SLA rule |
| `deadline_date` | datetime | SLA resolution deadline |
| `sla_status` | selection | SLA status (on_time, at_risk, expired) |
| `satisfaction_rating` | selection | Customer satisfaction rating |
| `satisfaction_comment` | text | Customer feedback text |
| `system_equipment` | string | Affected device/software name |
| `anydesk_id` | string | Remote access code if needed |

### Catalog tables the agent must query at startup to present valid options:

- `ticket_type` — types: Incidente, Requerimiento, Cambio, etc.
- `helpdesk_category` — 3-level tree (category → subcategory → element)
- `helpdesk_urgency` — urgency levels
- `helpdesk_impact` — impact levels
- `helpdesk_priority` — priority levels
- `helpdesk_ticket_stage` — workflow stages (with `is_close`, `is_resolve`, `is_pause` flags)
- `helpdesk_agent_group` — agent groups

### Important notes about the real system:

1. **Satisfaction already exists natively**: `satisfaction_rating`, `satisfaction_rating_num`, `satisfaction_comment`, `satisfaction_date` are built into the ticket model.
   - Our `feedback/collector.py` stores **agent evaluation** (how good was the AI assistant), NOT ticket CSAT.
   - These are different: CSAT = "was the problem solved?"; Agent eval = "was the AI helpful?"

2. **Knowledge base already exists natively**: `suggested_knowledge_ids`, `has_suggestions`.
   - Our ChromaDB RAG complements this: if the API exposes the knowledge base, we can query it too.
   - RAG seeds from `GET /api/resolved_tickets` or equivalent — never from SQLite.

3. **Category is hierarchical (3 levels)**: The creator prompt must guide L1 → L2 → L3 progressively.
   - First ask category (L1), then show available subcategories for that L1, then elements for that L2.

4. **Stage-based workflow**: The agent does NOT use status strings. It uses `stage_id` references.
   - "Resolve" = move ticket to the stage where `is_resolve=True`
   - "Close" = move ticket to the stage where `is_close=True`

5. **SLA awareness**: The agent can inform users about `sla_status`, `deadline_date`, `is_about_to_expire`.

---

## Architecture

Hexagonal (ports + adapters). All code in English.

```
agent-v2/
├── config/
│   └── settings.py          # Pydantic BaseSettings — single source of truth
├── ports/
│   ├── ticket_port.py        # ITicketPort ABC — uses REAL Odoo field names
│   └── rag_port.py           # IRAGPort ABC + SuggestionResult dataclass
├── adapters/
│   ├── express_adapter.py    # DEV ONLY — maps to Express backend (simplified schema)
│   ├── http_adapter.py       # PRODUCTION — generic REST adapter (configurable for Odoo API)
│   └── postgres_adapter.py   # FUTURE — direct PostgreSQL access (stubs only)
├── rag/
│   ├── embeddings.py         # HuggingFace singleton via lru_cache
│   └── store.py              # ChromaDB implementing IRAGPort
├── tools/
│   ├── ticket_tools.py       # Ticket CRUD tools (delete present but excluded)
│   ├── user_tools.py         # User + catalog query tools (types, categories, groups)
│   └── rag_tools.py          # suggest_solution_before_ticket + record_agent_feedback
├── prompts/
│   ├── base.py               # Shared behavior rules injected into all roles
│   ├── creator.py            # Resolution-first flow, hierarchical category selection
│   ├── resolver.py           # Proactive suggestions, SLA awareness
│   └── supervisor.py         # Management actions (delete disabled message)
├── feedback/
│   ├── schemas.py            # AgentFeedbackRecord Pydantic model
│   └── collector.py          # SQLite-backed — stores AI assistant evaluation (NOT ticket CSAT)
├── core/
│   ├── state.py              # AgentState TypedDict
│   ├── graph.py              # LLM init + checkpointer factory
│   └── agent.py              # Port injection + role-keyed tool sets + response extraction
├── api/
│   ├── schemas/
│   │   ├── chat.py           # ChatRequest / ChatResponse
│   │   └── invoke.py         # InvokeRequest / InvokeResponse
│   ├── middleware/
│   │   └── auth.py           # X-Agent-Key middleware (swap to OAuth2 later)
│   └── routes/
│       ├── chat.py           # POST /agent/chat (human, stateful per thread_id)
│       └── invoke.py         # POST /agent/invoke (A2A, stateless, no LLM)
├── main.py                   # FastAPI bootstrap + lifespan + adapter selection
├── pyproject.toml            # Dependency declaration (managed by uv — NOT pip)
├── uv.lock                   # Lock file for reproducible installs
├── .env.example
└── Dockerfile
```

---

## Key Design Decisions

### 1. Resolution-first (enforced structurally)
- Creator prompt step 3 is always `suggest_solution_before_ticket`
- Only if `solutions_found=True AND confidence >= 0.6` does agent present solution before creating ticket
- If user says solution didn't help → proceed to ticket creation
- `confidence` from ChromaDB cosine similarity (`score = 1 - distance`)

### 2. Human-in-the-loop — AI feedback (separate from ticket CSAT)
- After EVERY ticket creation OR solution suggestion, agent asks: "Rate the AI assistance 1-5"
- Agent calls `record_agent_feedback(ticket_id, user_id, rating, comment, feedback_type)`
- Stored in `feedback.db` — this is DIFFERENT from the ticket's `satisfaction_rating` field
- `feedback_type`: `"ticket_created"` or `"solution_suggested"`
- The ticket's own `satisfaction_rating` (customer CSAT) is managed by the enterprise system

### 3. Role-keyed tool lists (security by construction)
- `creador` tools: create_ticket, get_my_created_tickets, get_ticket_detail, get_catalog_data, suggest_solution_before_ticket, record_agent_feedback
- `resolutor` tools: get_my_assigned_tickets, get_ticket_detail, resolve_ticket, get_catalog_data, suggest_solution_before_ticket, record_agent_feedback
- `supervisor` tools: get_all_tickets, get_ticket_detail, assign_ticket, reopen_ticket, get_resolvers, get_catalog_data, record_agent_feedback
- LangGraph cannot call a tool not in its list — this is security by construction, not by prompt

### 4. Delete pattern
```python
def delete_ticket(ticket_id: str, user_id: int) -> dict:
    """Permanently deletes a ticket. Supervisor only."""
    return _port.delete_ticket(ticket_id, user_id)

# SECURITY: delete_ticket is implemented but intentionally excluded from all role
# tool lists until an authorization layer is in place.
# To enable: add delete_ticket to get_supervisor_tools() return list.
```

### 5. A2A endpoint — no LLM in path
`POST /agent/invoke` maps `intent` → direct method call via `INTENT_MAP`. Deterministic, stateless, structured JSON in/out.

### 6. RAG seeds from API (not SQLite)
At startup: call `ticket_port.get_resolved_tickets()` → REST API → seeds ChromaDB. Never SQLite.

### 7. Catalog data cached at startup
Urgency, impact, priority, ticket types, stages, and categories are fetched once at startup and cached.
Tools expose a `get_catalog_data(catalog_name)` function so the LLM can present valid options.

### 8. Auth ready for OAuth2
```python
# api/middleware/auth.py
# To upgrade to OAuth2/JWT:
# 1. Replace this middleware with FastAPI dependency using OAuth2PasswordBearer
# 2. Business logic in routes stays unchanged
```

### 9. SqliteSaver for persistent memory
`CHECKPOINT_BACKEND=sqlite` → `SqliteSaver`. Conversations survive restarts.

---

## ITicketPort — Updated interface (Odoo-compatible field names)

```python
class ITicketPort(ABC):
    # --- Ticket CRUD ---
    @abstractmethod
    def create_ticket(self, payload: dict, user_id: int) -> dict:
        """
        payload uses REAL field names:
        {
          "asunto": str,
          "descripcion": str,
          "ticket_type_id": int,
          "category_id": int,
          "subcategory_id": int,       # optional
          "element_id": int,           # optional
          "urgency_id": int,
          "impact_id": int,
          "priority_id": int,
          "partner_id": int,           # requestor contact
          "affected_user_id": int,     # optional
          "system_equipment": str,     # optional
        }
        Returns: {"success": bool, "ticket_name": "TCK-0001", "ticket_id": int}
        """

    @abstractmethod
    def get_tickets_by_creator(self, user_id: int) -> list: ...

    @abstractmethod
    def get_tickets_by_assignee(self, user_id: int) -> list: ...

    @abstractmethod
    def get_ticket_detail(self, ticket_id: int, user_id: int, role: str) -> dict: ...

    @abstractmethod
    def resolve_ticket(self, ticket_id: int, motivo_resolucion: str,
                       causa_raiz: str, user_id: int) -> dict:
        """Moves ticket to resolve stage. Sets motivo_resolucion and causa_raiz."""

    @abstractmethod
    def update_ticket(self, ticket_id: int, fields: dict, user_id: int) -> dict: ...

    @abstractmethod
    def get_all_tickets(self, filters: dict = None) -> list: ...

    @abstractmethod
    def assign_ticket(self, ticket_id: int, assignee_id: int,
                      agent_group_id: int, user_id: int) -> dict: ...

    @abstractmethod
    def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict: ...

    # SECURITY: delete_ticket defined but excluded from all tool lists
    @abstractmethod
    def delete_ticket(self, ticket_id: int, user_id: int) -> dict: ...

    # --- Catalog queries ---
    @abstractmethod
    def get_resolvers(self) -> list: ...

    @abstractmethod
    def get_ticket_types(self) -> list: ...

    @abstractmethod
    def get_categories(self, parent_id: int = None) -> list:
        """Pass parent_id=None for L1, parent_id=<L1_id> for L2, etc."""

    @abstractmethod
    def get_urgency_levels(self) -> list: ...

    @abstractmethod
    def get_impact_levels(self) -> list: ...

    @abstractmethod
    def get_priority_levels(self) -> list: ...

    @abstractmethod
    def get_stages(self) -> list: ...

    @abstractmethod
    def get_resolved_tickets(self) -> list:
        """Returns resolved tickets for RAG seeding. Uses motivo_resolucion field."""

    @abstractmethod
    def get_agent_groups(self) -> list: ...
```

---

## Creator Prompt Flow (updated for 3-level categories)

```
1. Greet and ask what the problem is
2. Ask: ticket_type (show options from get_ticket_types())
3. CALL suggest_solution_before_ticket(description, category_name)
   → If confidence >= 0.6: present solution, ask if resolved
   → If resolved: ask for AI rating → record_agent_feedback
   → If not resolved: continue to step 4
4. Ask: category L1 (show options from get_categories())
5. Ask: subcategory L2 (show options from get_categories(parent_id=L1_id))
6. Ask: element L3 if available (show options from get_categories(parent_id=L2_id))
7. Ask: urgency (show options from get_urgency_levels())
8. Ask: affected device/software (system_equipment) — optional
9. Infer: impact and priority from urgency + description
10. Show full summary:
    - Subject (asunto)
    - Type / Category / Subcategory / Element
    - Urgency / Impact / Priority
    - Description
    Ask for confirmation
11. On confirm: call create_ticket(payload, user_id)
12. Report back: "Ticket TCK-XXXX created successfully."
13. Ask for AI rating → call record_agent_feedback(feedback_type="ticket_created")
```

---

## Implementation Order

| # | File | Key detail |
|---|------|-----------|
| 1 | `config/settings.py` | Port 8001 (coexists with v1 at 8000) |
| 2 | `ports/ticket_port.py` | Odoo field names; catalog query methods |
| 3 | `ports/rag_port.py` | `SuggestionResult` dataclass; `motivo_resolucion` as resolution field |
| 4 | `rag/embeddings.py` | `lru_cache(maxsize=1)` singleton |
| 5 | `rag/store.py` | Seeds from API; uses `motivo_resolucion` not `resolucion` |
| 6 | `adapters/express_adapter.py` | DEV ONLY — maps simplified Express schema to ITicketPort |
| 7 | `adapters/http_adapter.py` | PROD — generic REST adapter for Odoo API (configurable endpoints) |
| 8 | `adapters/postgres_adapter.py` | Stubs with SQL docstrings for real Odoo tables |
| 9 | `feedback/schemas.py` | `AgentFeedbackRecord` — AI assistant eval (NOT ticket CSAT) |
| 10 | `feedback/collector.py` | `threading.Lock`, SQLite |
| 11 | `tools/ticket_tools.py` | `set_ticket_port()` + role-grouped `get_*_tools()` |
| 12 | `tools/user_tools.py` | catalog queries: types, categories (3-level), urgency, impact, priority |
| 13 | `tools/rag_tools.py` | `suggest_solution_before_ticket` + `record_agent_feedback` |
| 14 | `prompts/base.py` | `BASE_RULES` — AI feedback request + knowledge restrictions |
| 15 | `prompts/creator.py` | 3-level category flow; numbered steps 1-13 |
| 16 | `prompts/resolver.py` | SLA awareness; `motivo_resolucion` + `causa_raiz` fields |
| 17 | `prompts/supervisor.py` | Delete disabled; `agent_group_id` in assign flow |
| 18 | `core/state.py` | `AgentState` TypedDict |
| 19 | `core/graph.py` | `build_llm()` + `build_checkpointer()` |
| 20 | `core/agent.py` | `initialize_ports()`, `get_tools_for_role()`, `get_response()` |
| 21 | `api/schemas/chat.py` | Keep `user_rol` field (frontend compat) |
| 22 | `api/schemas/invoke.py` | `InvokeRequest` / `InvokeResponse` |
| 23 | `api/middleware/auth.py` | Skip `/health`, check `X-Agent-Key` |
| 24 | `api/routes/chat.py` | One agent per role, lazy-init |
| 25 | `api/routes/invoke.py` | `INTENT_MAP` — no LLM |
| 26 | `main.py` | lifespan: build adapter → seed RAG → cache catalogs → inject ports |
| 27 | `pyproject.toml` + `uv.lock` | `uv` project — NOT pip |
| 28 | `.env.example` | Document every setting |
| 29 | `Dockerfile` | `uv sync --frozen --no-dev` |

---

## V1 → V2 Comparison

| Concern | V1 | V2 |
|---------|----|----|
| Target system | Express + SQLite (dev) | Odoo Helpdesk via REST API + PostgreSQL |
| Field names | Spanish strings (tipo, estado) | Real Odoo technical names (ticket_type_id, stage_id) |
| Categories | 1-level string | 3-level FK hierarchy (L1→L2→L3) |
| Status | string `estado` | `stage_id` FK with workflow flags |
| Paths | Hardcoded absolute | `settings.py` from `.env` |
| SQLite | Direct read | Via REST API |
| Auth | None | `X-Agent-Key` middleware |
| Memory | `InMemorySaver` | `SqliteSaver` (configurable) |
| A2A | None | `POST /agent/invoke` |
| Code language | Mixed | All English |
| Resolution flow | Prompt-suggested | Structurally enforced |
| Feedback (AI) | None | `AgentFeedbackCollector` + tool |
| Feedback (CSAT) | None | Uses native Odoo `satisfaction_rating` |
| Delete | Tool in list | Implemented, excluded from lists |
| Port | 8000 | 8001 |

---

## Adapters: Development vs Production

### ExpressAdapter (dev only)
- Connects to `http://localhost:3001`
- Uses simplified schema (string enums instead of FK IDs)
- Catalog methods return hardcoded values matching Express seed data
- `resolve_ticket` maps to `PUT /api/tickets/:id/resolve` with `{"resolucion": text}`

### HttpAdapter (production — configurable for Odoo)
- All endpoints configurable via `.env` (e.g. `ODOO_BASE_URL`, `ODOO_API_KEY`)
- Uses Odoo REST API format: `POST /api/method/helpdesk.ticket/create`, etc.
- Catalog queries hit `/api/method/helpdesk.ticket_type/search_read`, etc.
- `resolve_ticket` writes to `motivo_resolucion` + `causa_raiz` + calls stage change
- Supports `X-Odoo-Database`, `Authorization: Bearer` headers (configurable)

### PostgresAdapter (future — enterprise direct access)
- All methods raise `NotImplementedError` with the real SQL query documented in the docstring
- Table names from Odoo: `helpdesk_ticket`, `helpdesk_ticket_stage`, `helpdesk_category`, etc.

---

## Verification

### Setup
```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
cd ia-agent-tickets-v1/agent-v2
uv init --no-readme --python 3.11
uv add langgraph langchain-core langchain-groq langchain-openai \
       langchain-chroma langchain-huggingface \
       fastapi "uvicorn[standard]" httpx python-dotenv \
       pydantic pydantic-settings chromadb sentence-transformers \
       langgraph-checkpoint-sqlite
```

### Phase 1 — Adapters
```bash
cp .env.example .env  # fill GROQ_API_KEY at minimum
uv run python -c "from adapters.express_adapter import ExpressAdapter; \
  a = ExpressAdapter('http://localhost:3001'); print(a.get_all_tickets())"
```

### Phase 2 — Full chat flow
```bash
uv run python main.py &
curl http://localhost:8001/health
curl -X POST http://localhost:8001/agent/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Key: dev-key-change-in-prod" \
  -d '{"user_id":1,"user_rol":"creador","message":"my laptop screen is broken"}'
# Agent must: ask details, call suggest_solution_before_ticket, guide L1→L2→L3 categories
```

### Phase 3 — A2A
```bash
curl -X POST http://localhost:8001/agent/invoke \
  -H "Content-Type: application/json" \
  -H "X-Agent-Key: dev-key-change-in-prod" \
  -d '{"intent":"get_tickets","parameters":{},"user_id":1,"user_rol":"creador"}'
```

### Phase 4 — AI Feedback
```bash
uv run python -c "import sqlite3; c=sqlite3.connect('feedback.db'); \
  print(c.execute('SELECT * FROM feedback').fetchall())"
```

### Dockerfile (uv-based)
```dockerfile
FROM python:3.11-slim
RUN pip install uv
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev
COPY . .
RUN mkdir -p /app/vector_store /app/data
EXPOSE 8001
CMD ["uv", "run", "python", "main.py"]
```
