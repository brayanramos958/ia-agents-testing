# Agent v2 — Helpdesk Microservice (Plan)

---

## Estado actual — 2026-04-24 (última revisión)

> **Tests**: `scratch/test_improvements.py` (30 tests) + `scratch/test_bugs_ab.py` (9 tests) — todos verdes.
> `scratch/test_fullflow.py` (14 turnos / 3 roles) — **14/14 PASS** confirmado 2026-04-22 y 2026-04-23 con Groq llama-4-scout-17b.
> `scratch/test_rol.py` — test modular por rol. Supervisor: **4/4 PASS** confirmado 2026-04-24.
> RAG operativo: 3 tickets sembrados (TCK-0001, TCK-0002, TCK-0016). Scores correctos post-fix: 0.688–0.815.
> Flujo aprobación supervisor: **PASS** — approve y reject verificados en BD (2026-04-24).

### ✅ Implementado y funcionando (probado en desarrollo)

| Archivo | Estado | Notas |
|---|---|---|
| `config/settings.py` | ✅ | Pydantic Settings, single source of truth. Fallbacks actualizados 2026-04-21: 5 modelos válidos verificados con tool calling (`nvidia/nemotron-3-super-120b-a12b:free`, `google/gemma-4-31b-it:free`, `google/gemma-4-26b-a4b-it:free`, `minimax/minimax-m2.5:free`, `nvidia/nemotron-3-nano-30b-a3b:free`). Los anteriores `meta-llama/llama-3.3-70b-instruct:free` y `openai/gpt-oss-*` ya no existen en OpenRouter |
| `ports/ticket_port.py` | ✅ | ITicketPort con nombres Odoo |
| `ports/rag_port.py` | ✅ | IRAGPort + SuggestionResult. `SolutionItem` incluye `causa_raiz`. `add_resolved_ticket` acepta `causa_raiz` con default `""` (backwards compat) |
| `adapters/express_adapter.py` | ✅ | Adapter de desarrollo contra FastAPI + SQLite (puerto 8000). Nota: el backend NO es Node.js/Express — es FastAPI Python en `ia-agent-tickets-v2/backend/main.py` |
| `rag/store.py` | ✅ | ChromaDB seeding desde API REST. `causa_raiz` embebida en `document_text` y metadata. **2026-04-23**: `similarity_search_with_score` + conversión `sim = 1 - (dist/2)` — los scores ahora son correctos [0,1] (antes retornaba distancias coseno sin normalizar) |
| `rag/embeddings.py` | ✅ | HuggingFace singleton `all-MiniLM-L6-v2` |
| `tools/ticket_tools.py` | ✅ | create, get, resolve, assign, reopen, update. `_resolve_id()` convierte nombres LLM → IDs. **2026-04-22**: `update_ticket` agregado a `get_resolver_tools()`. **2026-04-23 (Bug-R)**: todos los params de ID cambiados a `Union[int, str]` — Groq valida schemas server-side antes de Python. `resolve_ticket` usa fallback `tipo_requerimiento`/`categoria` para el RAG (Express no usa `ticket_type`/`category`) |
| `tools/user_tools.py` | ✅ | catálogos: tipos, categorías 3 niveles, urgencia, impacto, prioridad. **2026-04-21 (Bug-L)**: `parent_id` cambiado a `Union[int, str, None]` + validator que normaliza `"null"` → None |
| `tools/rag_tools.py` | ✅ | `suggest_solution` expone `causa_raiz` al LLM. **2026-04-23 (Bug-Q)**: `record_agent_feedback` — `user_id`, `rating`, `ticket_id` cambiados a `Union[int, str]` |
| `scratch/test_rol.py` | ✅ | **NUEVO 2026-04-23** — test modular por rol. Uso: `py scratch/test_rol.py creador\|resueltor\|supervisor\|all [--delay N]`. ~50-60K tokens/bloque. Incluye estimado de tokens consumidos |
| `tools/ticket_tools.py` (approve/reject) | ✅ | **2026-04-24**: `approve_ticket` y `reject_ticket` agregadas como tools con `@tool @backend_retry`. Incluidas en `get_supervisor_tools()` |
| `ports/ticket_port.py` (approve/reject) | ✅ | **2026-04-24**: `approve_ticket(ticket_id, user_id)` y `reject_ticket(ticket_id, reason, user_id)` agregados como métodos abstractos |
| `adapters/express_adapter.py` (approve/reject) | ✅ | **2026-04-24**: Implementados via `PUT /api/tickets/:id` con `{"approval_status": "approved/rejected", "rejection_reason": reason}` |
| `prompts/base.py` | ✅ | Frustración → ticket urgente + contacto humano. Reglas anti-prompt-injection (Capa 1) |
| `prompts/creator.py` | ✅ | Historial inyectado en contexto. Paso 1B hardware (pasos de verificación). Paso 1B software (explicación proceso aprobación 4 pasos). Descripción en 3ra persona con voz del usuario |
| `prompts/resolver.py` | ✅ | Tickets agrupados por SLA. Verifica `approval_status`. Guía `motivo_resolucion` + `causa_raiz`. **2026-04-21**: removido `get_categories` del listado de tools del prompt (no está en el toolset del rol) |
| `prompts/supervisor.py` | ✅ | Resumen ejecutivo al iniciar. Priorización visual por SLA. **2026-04-21**: removido `get_categories` (no disponible para este rol), agregado `get_stages` (sí disponible). **2026-04-24**: agregado flujo completo de aprobación/rechazo con confirmación, conteo de pendientes en resumen inicial |
| `feedback/collector.py` | ✅ | SQLite-backed, evaluación del agente AI (≠ CSAT del ticket) |
| `core/graph.py` | ✅ | Groq primario + OpenRouter fallback + AsyncSqliteSaver. **2026-04-21**: `timeout=60` en cada modelo fallback (previene esperas >3000s). `APIStatusError` agregado a `exceptions_to_handle` (captura error 402 spend-limit de OpenRouter). Ollama: `think=False` + `num_ctx=8192` para evitar OOM en CPU |
| `core/agent.py` | ✅ | `_trim_hook` (ventana 12 msgs, saneado de huérfanos, **solo conserva último SystemMessage**). `_fetch_creator_context` inyecta historial en system prompt (**cacheado por thread_id**). `_prepare_invocation` elimina lógica duplicada entre `/chat` y `/stream`. Detección de thread corrupto con `aget_state()`. `invalidate_creator_context()` para limpiar cache explícitamente |
| `api/routes/chat.py` | ✅ | sesión diaria: `thread_id = user-{id}-{date.today()}` |
| `api/routes/stream.py` | ✅ | POST /agent/stream — SSE token a token via `astream_events` |
| `api/routes/invoke.py` | ✅ | POST /agent/invoke — A2A stateless sin LLM |
| `api/middleware/auth.py` | ✅ | X-Agent-Key |
| `main.py` | ✅ | lifespan con RAG seeding resiliente |
| `pyproject.toml` + `uv.lock` | ✅ | gestionado con uv |

---

### ⚠️ Implementado pero SIN PROBAR en producción (requiere acceso Odoo API)

| Archivo | Estado | Qué falta verificar |
|---|---|---|
| `adapters/odoo_adapter.py` | ⚠️ implementado, no probado en prod | JSON-RPC 2.0 contra Odoo 15. 8 fixes de producción aplicados: re-auth automático en sesión expirada, `_text_to_html` con escape HTML completo, retry en `_call_kw`. Necesita credenciales reales para validar |
| `_text_to_html()` en odoo_adapter | ⚠️ implementado, no probado | Odoo requiere HTML en campos `fields.Html`; no se ha verificado en Odoo real |
| `usuario_solicitante_id` en `create_ticket` | ⚠️ implementado, no probado | Se envía explícitamente; en Odoo lo setea `@api.onchange`, no JSON-RPC |
| `system_equipment` como campo real | ⚠️ implementado, no probado | Es `Char(tracking=True)` en custom, se envía como campo standalone |
| `reopen_ticket` con historial | ⚠️ implementado, no probado | Lee `motivo_resolucion` actual y lo preserva con `<hr/>` separator |
| `approval_status` en `get_ticket_detail` | ⚠️ implementado, no probado | Agregado a fields list; depende de que Odoo lo retorne |
| Campos SLA (`sla_status`, `deadline_date`, `is_about_to_expire`) | ⚠️ implementado, no probado | Stored=True en Odoo; verificar que JSON-RPC los devuelva |

---

### 🔴 Bugs confirmados (pendientes de fix)

> Sin bugs críticos pendientes al 2026-04-23. Los pendientes abiertos son mejoras y flujos incompletos (ver sección ❌ más abajo).

---

### 🚀 Producción — mejoras para 50 usuarios simultáneos

#### Crítico (rompe bajo carga)

- [x] **[PROD-1] Migrar checkpointer a PostgreSQL** — `AsyncSqliteSaver` tiene write contention con múltiples usuarios concurrentes. Fix: `AsyncPostgresSaver` de `langgraph-checkpoint-postgres`. Requiere `CHECKPOINT_BACKEND=postgres` + `POSTGRES_DSN` en `.env`. `settings.py`, `core/graph.py`, `pyproject.toml`
- [ ] **[PROD-2] ChromaDB en modo servidor** — con múltiples uvicorn workers, cada proceso apunta al mismo archivo SQLite y colisionan. Fix: `chroma run` como servicio independiente + `chromadb.HttpClient` en `rag/store.py`. Alternativa a largo plazo: pgvector
- [ ] **[PROD-3] Semáforo async en LLM calls** — 50 usuarios pueden generar 50+ LLM calls paralelas, saturando Groq y el fallback OpenRouter. Fix: `asyncio.Semaphore(20)` antes de `agent.ainvoke()` en `core/agent.py`
- [ ] **[PROD-4] Thread isolation** — `thread_id` viene del frontend sin prefijo de `user_id`. Dos usuarios con el mismo `thread_id` comparten historial. Fix (1 línea): `safe_thread = f"{user_id}:{thread_id}"` en `api/routes/chat.py` y `api/routes/stream.py`

#### Medio (degrada bajo carga)

- [ ] **[PROD-5] OdooAdapter async** — `httpx.post` síncrono corre en thread pool (default 40 threads). Bajo carga con Odoo lento, el pool se agota. Fix: migrar a `httpx.AsyncClient` con `await` en `adapters/odoo_adapter.py`
- [ ] **[PROD-6] Rate limiting por usuario** — un usuario puede saturar el presupuesto LLM del equipo entero. Fix: `slowapi` con `@limiter.limit("10/minute")` en las routes de chat y stream
- [ ] **[PROD-7] `_creator_context_cache` no sobrevive múltiples workers** — cada worker tiene su propio dict en memoria. Fix: Redis para cache compartido, o documentar restricción de single-worker

#### Observabilidad (operar sin ceguera)

- [ ] **[PROD-8] Health check real** — el `/health` actual siempre devuelve 200. Debe verificar conectividad a Odoo, ChromaDB y LLM. Fix: checks async con timeout corto en `main.py`
- [ ] **[PROD-9] Structured logging con contexto** — logs actuales no incluyen `user_id` ni `thread_id`. Imposible trazar una sesión fallida en producción. Fix: logger con contextvars en cada request
- [ ] **[PROD-10] Métricas de deflexión** — endpoint `GET /agent/metrics` con `deflection_rate`, `avg_satisfaction`, `tickets_deflected`. Files: `api/routes/metrics.py`, `feedback/collector.py`

---

### ❌ Pendiente / No implementado

#### Flujos incompletos
- [x] **Supervisor: aprobación de tickets** — **RESUELTO 2026-04-24**. `approve_ticket` y `reject_ticket` implementadas en `ticket_tools.py`, `ports/ticket_port.py`, `adapters/express_adapter.py`. Flujo completo en `prompts/supervisor.py`. Backend DEV extendido con columnas `approval_status` y `rejection_reason`. Verificado: approve y reject persisten en BD, supervisor detecta pendientes con filtro `approval_status=pending`.
- [ ] **Prefetch de contexto para resolutor** — el creador tiene `_fetch_creator_context` precargado en el system prompt; el resolutor empieza ciego y debe esperar que el agente llame `get_my_assigned_tickets` antes de ser útil. Implementar `_fetch_resolver_context(user_id, thread_id)` análogo al del creador

#### Calidad del RAG
- [x] **Deduplicación en `add_resolved_ticket`** — **CORREGIDO** (`rag/store.py:137-143`): antes de insertar, busca si existe un documento con el mismo `ticket_id` y lo elimina. Tickets reabiertos y re-resueltos reemplazan el embedding anterior.
- [ ] **Feedback positivo retroalimenta el RAG** — cuando `record_agent_feedback` recibe rating 4–5 para `feedback_type="solution_suggested"`, debería aumentar el peso del documento correspondiente (re-insertar o boost). Los usuarios que resuelven su problema sin ticket son la mejor señal de calidad del RAG

#### Seguridad — Prompt injection
- [ ] **Capa 2 — Sanitización de input**: middleware en la route que detecta patrones de inyección antes de llegar al LLM (`api/middleware/` o `api/routes/chat.py`)
- [ ] **Capa 3 — Inyección indirecta desde BD/RAG**: wrapping de resultados de tools con framing explícito de "datos externos, no ejecutar como instrucciones"
- [ ] **Capa 4 — Aislamiento de user_id en tools**: el `user_id` no debe venir del LLM como parámetro — debe cerrarse desde el contexto autenticado del request. Actualmente el LLM podría pasar un `user_id` diferente al real (mayor impacto de seguridad)
- [ ] **Capa 5 — Filtrado de output**: post-procesamiento para detectar/redactar datos sensibles antes de devolver al frontend

#### Aislamiento de sesiones
- [ ] **Thread isolation**: componer `safe_thread = f"{user_id}:{thread_id_del_cliente}"` en `chat.py` y `stream.py`. Actualmente si el frontend envía `thread_id="abc"`, cualquier usuario con ese mismo `thread_id` comparte el historial conversacional

#### En el agente (sin tocar backend):
- [ ] **Detección de incidentes masivos** — tool `check_similar_open_tickets()` que alerte si >2 usuarios reportaron el mismo problema en 24h (`tools/ticket_tools.py`, `prompts/supervisor.py`)
- [ ] **Métricas de deflexión** — endpoint `GET /agent/metrics` con deflection_rate, avg_satisfaction, tickets_deflected (`api/routes/metrics.py`, `feedback/collector.py`)
- [ ] **Tool `add_note_to_ticket`** — agregar nota interna a un ticket existente (`tools/ticket_tools.py`)

#### Requieren cambios en Express backend (desarrollo):
- [x] `approval_status` y `rejection_reason` — **RESUELTO 2026-04-24**. Columnas agregadas al modelo SQLAlchemy, schema Pydantic y DB SQLite via `ALTER TABLE`. Filtro `?approval_status=pending` disponible en `GET /api/tickets`.
- [ ] `GET /api/tickets/:id` — incluir historial de acciones
- [ ] `POST /api/tickets/:id/notes` — agregar notas internas

#### Requieren acceso a Odoo API en producción:
- [ ] **Knowledge base de Odoo** — integrar `helpdesk.knowledge` como segunda fuente de RAG
- [ ] Verificar paginación (`limit`/`offset`) en `get_all_tickets` contra Odoo real
- [ ] Verificar mapping del Chatter de Odoo a historial del agente
- [ ] `http_adapter.py` — sigue siendo stub

#### Requieren servicios externos (Fase 3):
- [ ] **Alertas proactivas de SLA** — background task + email/Slack/webhook
- [ ] **Multi-canal** — WhatsApp Business API / Teams / Slack
- [ ] **Soporte de adjuntos/imágenes** — upload endpoint + Llama 4 Scout multimodal

---

### Bugs corregidos

| Bug | Archivo | Fix aplicado |
|---|---|---|
| **Bug-C** — HTML crudo en embeddings de ChromaDB (`motivo_resolucion`, `causa_raiz` con `<p>`, `<br/>`, `&amp;`) | `rag/store.py:119-124` | `_strip_html()` limpia tags HTML antes de construir `document_text` |
| **Bug-E** — `rag_similarity_threshold` definido en settings pero ignorado en `search_similar` | `rag/store.py:82-90` | Filtro `if score < threshold: continue` antes de construir cada `SolutionItem` |
| `ValueError: invalid literal for int()` — LLM pasaba nombre en lugar de ID | `tools/ticket_tools.py` | `_resolve_id()` resuelve nombre → ID desde catálogo |
| `handle_tool_errors` en lugar incorrecto | `core/agent.py` | Movido a `ToolNode(tools, handle_tool_errors=True)` |
| Thread corrupto por crash mid-tool-call | `core/agent.py` | `aget_state()` detecta orphaned tool_calls y resetea thread |
| Historial skipped por el LLM (tool call ignorada) | `core/agent.py` | Historial inyectado directamente en system prompt via `_fetch_creator_context` |
| Fallbacks de peor calidad generaban respuestas basura | `config/settings.py` | Removidos `qwen3-coder:free` y `nemotron-nano:free` |
| Campos `fields.Html` rechazados por Odoo | `adapters/odoo_adapter.py` | `_text_to_html()` wrappea texto plano en `<p>` |
| `_trim_hook` con imports duplicados | `core/agent.py` | Eliminados — ya existen a nivel módulo |
| Sesión permanente acumulaba contexto indefinidamente | `chat.py`, `stream.py` | `thread_id = user-{id}-{date.today()}` |
| SystemMessages acumulados en el checkpoint (N msgs × N llamadas) | `core/agent.py:_trim_hook` | Solo se conserva el `all_system[-1]` — el más reciente |
| `_fetch_creator_context` llamado en cada mensaje (N round-trips a Odoo) | `core/agent.py` | Cache por `thread_id` con FIFO de 500 entradas |
| Lógica duplicada entre `get_response` y `stream_response` | `core/agent.py` | Extraída a `_prepare_invocation()` |
| `causa_raiz` descartada al indexar en RAG | `rag/store.py`, `tools/ticket_tools.py`, `adapters/odoo_adapter.py`, `ports/rag_port.py`, `tools/rag_tools.py` | `causa_raiz` se embebe en `document_text`, se guarda en metadata y se expone al LLM via `suggest_solution_before_ticket` |
| `f"TCK-{ticket_id:04d}"` con `ticket_id: str` → `ValueError` en fallback de `resolve_ticket` | `tools/ticket_tools.py` | Cambiado a `ticket.get("name") or f"TCK-{int(ticket_id):04d}"` (cortocircuito evita evaluación eager) |
| **Bug-A** — `_fetch_creator_context` filtraba por `t.get("state","")` (campo inexistente en Odoo). Todos los tickets aparecían "abiertos" incluyendo cerrados/resueltos | `core/agent.py` | Nuevo `_is_open(ticket)` que inspecciona `stage_id[1].lower()` contra set de nombres cerrados. `stage_id=False` se trata como abierto |
| **Bug-B** — `get_tickets_by_creator` devolvía tickets cerrados (sin filtro de stage), inconsistente con `get_tickets_by_assignee` | `adapters/odoo_adapter.py` | Agregado `["stage_id.is_close","=",False]` al domain. El stage name ahora aparece correctamente en el historial |
| **Bug-F** — Prompt resueltor listaba `update_ticket` en tools disponibles pero no estaba en `get_resolver_tools()`. LangGraph fallaba silenciosamente cuando el LLM intentaba llamarla | `tools/ticket_tools.py` | `update_ticket` agregado a `get_resolver_tools()` |
| **Bug-G** — Prompt resueltor listaba `get_categories` que fue removida del toolset del rol en optimización anterior. Causaba error de tool-not-found | `prompts/resolver.py` | `get_categories` removida del listado del prompt |
| **Bug-H** — Prompt supervisor listaba `get_categories` que fue removida del toolset del rol. Causaba "no puedo acceder al sistema" en turno de asignación | `prompts/supervisor.py` | `get_categories` removida, `get_stages` agregada (tool que SÍ tiene disponible) |
| **Bug-I** — Fallback chain sin timeout: si OpenRouter no respondía, el agente esperaba indefinidamente. Causó espera de 3266s (54 min) en un turno del supervisor | `core/graph.py` | `timeout=60` en cada `ChatOpenAI` del fallback |
| **Bug-J** — Error `402 spend-limit` de OpenRouter no capturado: subía como HTTP 500 en lugar de intentar el siguiente modelo fallback | `core/graph.py` | `APIStatusError` agregado a `exceptions_to_handle` |
| **Bug-K** — 3 de 5 modelos en `openrouter_fallback_models` eran inválidos (`meta-llama/llama-3.3-70b-instruct:free`, `openai/gpt-oss-120b:free`, `openai/gpt-oss-20b:free`). Causaban 404 inmediato y elongaban la cadena innecesariamente | `config/settings.py` | Lista reemplazada por 5 modelos verificados en OpenRouter API (abril 2026) con tool calling confirmado |
| **Bug-L** (2026-04-22) — `get_categories` schema rechazado por Groq. `parent_id="null"` (string) enviado por LLM causaba error 400 server-side. Schema decía `anyOf: [integer, null]` pero LLM mandaba string | `tools/user_tools.py` | `_CategoriesInput(BaseModel)` con `Union[int, str, None]` + validator que normaliza `"null"` string → None |
| **Bug-N** (2026-04-22) — Error 413 (TPM) por checkpoints acumulados del mismo día. `thread_id=None` → servidor generaba `user-{id}-{date.today()}`, reutilizando historia entre runs | `scratch/test_fullflow.py` | `_slim_ticket()` helper + límites en listados (10/10/15). Root cause: checkpoints acumulados, no el prompt |
| **Bug-O** (2026-04-22) — `test_fullflow.py` T2.4 con TCK-0001 hardcodeado causaba false-positive PASS si el ticket ya estaba resuelto | `scratch/test_fullflow.py` | Mensaje dinámico que referencia el primer ticket de la lista en lugar de nombre hardcodeado |
| **Bug-P** (2026-04-22) — Cada re-run del mismo día reutilizaba `thread_id = user-{id}-{date.today()}`, acumulando historial en checkpoints.db hasta exceder 30K TPM de Groq | `scratch/test_fullflow.py` | `RUN_ID = int(time.time())` al inicio + `thread_id = test-{RUN_ID}-user-{id}` — cada run tiene threads únicos |
| **Bug-D** (2026-04-22) — `invalidate_creator_context` no se llamaba tras `create_ticket` exitoso. Cache retiene historial viejo. | `core/agent.py` | Detección de `ToolMessage` con `success: True` de `create_ticket` → invalida cache. Confirmado PASS en test 14/14 |
| **Bug-Q** (2026-04-23) — `record_agent_feedback`: `ticket_id`, `user_id`, `rating` declarados como `str` pero LLM manda integers. Groq rechaza 400 antes de llegar a Python | `tools/rag_tools.py` | Cambiados a `Union[int, str]` / `Optional[Union[int, str]]` |
| **Bug-R** (2026-04-23) — Todos los params de ID en todas las tools de `ticket_tools.py` declarados como `str`. LLM manda integers → Groq 400 server-side validation | `tools/ticket_tools.py` | Todos los params de ID cambiados a `Union[int, str]` (8 tools afectadas) |
| **Bug-RAG-1** (2026-04-23) — `vector_store/` tenía 5 docs de BD antigua (iteración anterior). `initialize_from_resolved_tickets` tiene guard `count() > 0 → skip` → nunca re-siembra | `vector_store/` | Borrar el directorio para forzar re-seed. Agregado a `.gitignore` |
| **Bug-RAG-2** (2026-04-23) — `similarity_search_with_relevance_scores` retornaba distancias coseno sin normalizar (rango [-1, 1]). Scores negativos nunca superaban el umbral 0.6 → RAG siempre "SIN SOLUCIONES" | `rag/store.py` | Cambio a `similarity_search_with_score` + conversión `sim = 1 - (dist / 2)` → scores en [0, 1] |
| **Bug-RAG-3** (2026-04-23) — `resolve_ticket` llamaba `add_resolved_ticket` con `ticket.get("ticket_type")` y `ticket.get("category")` — vacíos porque Express usa `tipo_requerimiento` y `categoria` | `tools/ticket_tools.py` | Fallback: `ticket.get("ticket_type") or ticket.get("tipo_requerimiento", "")` |

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
