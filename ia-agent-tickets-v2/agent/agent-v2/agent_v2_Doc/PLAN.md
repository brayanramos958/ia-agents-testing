# Agent v2 — Helpdesk Microservice (Plan)

> **Para arrancar el agente**: ver `CLAUDE.md` en la raíz del proyecto.
> Guía rápida: backend en puerto 8000, agente en Docker via `bash docker-up-dev.sh` (puerto 8001).

---

## Estado actual — 2026-05-06 (actualizado sesión)

> **Tests 2026-05-05**: `scratch/test_sara.py` — **18/18 PASS** (Supervisor 5/5, Creador 7/7, Resueltor 6/6) con `xai/grok-4.1-fast-non-reasoning` vía Vercel AI Gateway + `--delay 5`. Promedio: ~13s/turno.
> pgvector operativo: 2 documentos en store (Docker postgres, puerto 5433). ChromaDB eliminado.
> UX-2 (español forzado) + UX-3 (confirmación supervisor) implementados y verificados en tests.
> Rate limiting activo: sliding window 60s por user_id (`RATE_LIMIT_PER_MINUTE=10`).
> Docker stack auto-contenido: `helpdesk-postgres` (5433) + `helpdesk-agent-v2` (8001) — ambos healthy.
> **Dev con hot reload (2026-05-06)**: `docker-compose.dev.yml` + `docker-up-dev.sh` — bind mount del código fuente + volúmenes nombrados para venv y modelos HF. Cambios en `.py` recargan el agente en ~2s sin rebuild. Funciona en **Linux nativo** y WSL2. Ver `DOCKER_SETUP.txt`.
>
> **ENTORNO DE DESARROLLO**: Linux nativo recomendado. Ver `DOCKER_SETUP.txt` para setup completo.
> Para desarrollo local sin Docker (solo en Linux/Mac): `uv run python run.py`.
> **[Windows únicamente]** Puerto 8001 bloqueado por `iphlpsvc` → usar `PORT=8002` en `.env`. Arrancar con `uv run python run.py` (no `main.py` — falla con ProactorEventLoop + psycopg3).
>
> *(Historia anterior)* `scratch/test_sara.py` — **2026-05-04**: 21/21 PASS. `scratch/test_rol.py` — **2026-04-27**: Creador 4/5, Resolutor 5/5, Supervisor 4/4. **Agente dockerizado** (2026-04-28) — Docker Engine en WSL2 Ubuntu.

### ✅ Implementado y funcionando (probado en desarrollo)

| Archivo | Estado | Notas |
|---|---|---|
| `config/settings.py` | ✅ | Pydantic Settings, single source of truth. Fallbacks actualizados 2026-04-21: 5 modelos válidos verificados con tool calling (`nvidia/nemotron-3-super-120b-a12b:free`, `google/gemma-4-31b-it:free`, `google/gemma-4-26b-a4b-it:free`, `minimax/minimax-m2.5:free`, `nvidia/nemotron-3-nano-30b-a3b:free`). Los anteriores `meta-llama/llama-3.3-70b-instruct:free` y `openai/gpt-oss-*` ya no existen en OpenRouter |
| `ports/ticket_port.py` | ✅ | ITicketPort con nombres Odoo |
| `ports/rag_port.py` | ✅ | IRAGPort + SuggestionResult. `SolutionItem` incluye `causa_raiz`. `add_resolved_ticket` acepta `causa_raiz` con default `""` (backwards compat) |
| `adapters/express_adapter.py` | ✅ | Adapter de desarrollo contra FastAPI + SQLite (puerto 8000). Nota: el backend NO es Node.js/Express — es FastAPI Python en `ia-agent-tickets-v2/backend/main.py` |
| `rag/store.py` | ✅ | **2026-05-05**: `ChromaRAGStore` reemplazado por `PGVectorRAGStore` (`langchain_postgres.PGVector`). Mismo `postgres_dsn` del checkpointer — sin servicio extra. IDs estables `ticket-{id}` para upsert nativo. `_pg_dsn()` convierte `postgresql://` → `postgresql+psycopg://`. `count()` via SQL directo psycopg3. `chromadb` y `langchain-chroma` removidos de `pyproject.toml`. |
| `rag/embeddings.py` | ✅ | HuggingFace singleton `all-MiniLM-L6-v2` |
| `tools/ticket_tools.py` | ✅ | create, get, resolve, assign, reopen, update. `_resolve_id()` convierte nombres LLM → IDs. **2026-04-22**: `update_ticket` agregado a `get_resolver_tools()`. **2026-04-23 (Bug-R)**: todos los params de ID cambiados a `Union[int, str]`. **2026-04-28 (Capa 4)**: `_safe_uid()` aplicado a los 10 tools — lee `current_user_id` del ContextVar, ignora el valor que genera el LLM; fallback al valor del LLM solo cuando `context=0` (tests sin request activo) |
| `tools/user_tools.py` | ✅ | catálogos: tipos, categorías 3 niveles, urgencia, impacto, prioridad. **2026-04-21 (Bug-L)**: `parent_id` cambiado a `Union[int, str, None]` + validator que normaliza `"null"` → None |
| `tools/rag_tools.py` | ✅ | `suggest_solution` expone `causa_raiz` al LLM. **2026-04-23 (Bug-Q)**: `record_agent_feedback` — `user_id`, `rating`, `ticket_id` cambiados a `Union[int, str]`. **2026-04-28 (Capa 4)**: `_safe_uid()` aplicado a `record_agent_feedback` |
| `scratch/test_rol.py` | ✅ | **NUEVO 2026-04-23** — test modular por rol. Uso: `py scratch/test_rol.py creador\|resueltor\|supervisor\|all [--delay N]`. ~50-60K tokens/bloque. Incluye estimado de tokens consumidos |
| `tools/ticket_tools.py` (approve/reject) | ✅ | **2026-04-24**: `approve_ticket` y `reject_ticket` agregadas como tools con `@tool @backend_retry`. Incluidas en `get_supervisor_tools()` |
| `ports/ticket_port.py` (approve/reject) | ✅ | **2026-04-24**: `approve_ticket(ticket_id, user_id)` y `reject_ticket(ticket_id, reason, user_id)` agregados como métodos abstractos |
| `adapters/express_adapter.py` (approve/reject) | ✅ | **2026-04-24**: Implementados via `PUT /api/tickets/:id` con `{"approval_status": "approved/rejected", "rejection_reason": reason}` |
| `prompts/base.py` | ✅ | Frustración → ticket urgente + contacto humano. Anti-prompt-injection (Capa 1). **2026-05-04 (SARA v2)**: identidad SARA, contexto ITS. **2026-05-05 (UX-2)**: `## IDIOMA — REGLA ABSOLUTA E IRROMPIBLE` como PRIMERA sección — no sobreescribible por contexto corrupto |
| `prompts/creator.py` | ✅ | **2026-05-04 (SARA v2)**: `system_equipment`, `affected_users_count`, AnyDesk, prefijos INC-/SR-, guía L2/L3, RAG obligatorio antes de crear. Descripción en 3ra persona con voz del usuario |
| `prompts/resolver.py` | ✅ | **2026-05-04 (SARA v2)**: priorización SLA (VENCIDO → PRÓXIMO → PENDIENTE), guía `motivo_resolucion` + `causa_raiz`, escalamiento N2, base de conocimiento tras resolver |
| `prompts/supervisor.py` | ✅ | **2026-05-04 (SARA v2)**: dashboard **🚨 ACCIÓN REQUERIDA**, MTTN/MTTR, filtros JSON `get_all_tickets`. **2026-05-05 (UX-3)**: `NUNCA llames assign_ticket sin confirmación` en flujo Y en Restricciones. Verificado: LLM ya no salta el paso |
| `feedback/collector.py` | ✅ | SQLite-backed, evaluación del agente AI (≠ CSAT del ticket) |
| `core/graph.py` | ✅ | Groq primario + OpenRouter fallback + **AsyncPostgresSaver (2026-04-27)**. `timeout=60` en cada modelo fallback. `APIStatusError` en `exceptions_to_handle`. Ollama: `think=False` + `num_ctx=8192`. **Bug-W2**: DSN ya NO se transforma a `postgresql+psycopg://` (formato SQLAlchemy incompatible con psycopg3). **Bug-W3**: setup() usa conexión dedicada con `autocommit=True` para `CREATE INDEX CONCURRENTLY` |
| `core/agent.py` | ✅ | `_trim_hook` (ventana 12 msgs, saneado de huérfanos, **solo conserva último SystemMessage**). `_fetch_creator_context` inyecta historial en system prompt (**cacheado por thread_id**). `_prepare_invocation` elimina lógica duplicada entre `/chat` y `/stream`. Detección de thread corrupto con `aget_state()`. `invalidate_creator_context()` para limpiar cache explícitamente. **2026-04-28 (Capa 4)**: `current_user_id.set(user_id)` antes de `ainvoke()` y `astream_events()` en `get_response()` y `stream_response()` |
| `api/middleware/rate_limit.py` | ✅ | **NUEVO 2026-05-05 (PROD-6)** — Sliding window 60s keyed por `user_id`. HTTP 429 + `Retry-After`. Configurable via `RATE_LIMIT_PER_MINUTE`. Para multi-worker: reemplazar `_windows` dict por Redis (interface `check_rate_limit(user_id)` no cambia) |
| `api/routes/chat.py` | ✅ | **2026-04-28 (PROD-4)**: `thread_id = f"{user_id}:{raw_thread}"`. **2026-05-05**: `check_rate_limit(request.user_id)` al inicio del handler |
| `api/routes/stream.py` | ✅ | POST /agent/stream — SSE token a token via `astream_events`. **2026-04-28 (PROD-4)**: mismo fix de thread isolation que chat.py |
| `core/context.py` | ✅ | **NUEVO 2026-04-28 (Capa 4)** — `ContextVar[int] current_user_id` async-safe. Fija el user_id autenticado antes de cada invocación. Cada corrutina tiene su propio valor aislado — sin contaminación entre requests concurrentes |
| `api/routes/invoke.py` | ✅ | POST /agent/invoke — A2A stateless sin LLM |
| `api/middleware/auth.py` | ✅ | X-Agent-Key |
| `main.py` | ✅ | lifespan con RAG seeding resiliente |
| `run.py` | ✅ | **NUEVO 2026-04-27** — entry point Windows. Crea `asyncio.SelectorEventLoop()` explícitamente antes de que uvicorn inicie, evitando incompatibilidad psycopg3 + ProactorEventLoop (Bug-W1). En Linux/Mac el `else` usa `asyncio.run()` estándar. Uso: `uv run python run.py`. **2026-05-04 (Bug-PORT)**: corregido puerto hardcodeado 8001 → lee `settings.port` |
| `config/settings.py` | ✅ | **2026-05-04**: `ai_gateway_api_key`, `ai_gateway_model`, `ai_gateway_base_url`. `llm_provider` acepta `"vercel"`. **2026-05-05**: `rate_limit_per_minute` |
| `core/graph.py` | ✅ | **2026-05-04**: `_build_vercel_llm()` — `ChatOpenAI` con `base_url` override (Vercel AI Gateway). `build_llm()` enruta vercel/groq/ollama |
| `tools/rag_tools.py` | ✅ | **2026-05-04 (Bug-RAG-S)**: `suggest_solution` params `description` y `category` → `Any` + `_to_str()`. Groq rechazaba 400 con objetos en lugar de strings |
| `scratch/test_sara.py` | ✅ | **NUEVO 2026-05-04** — 4 roles, `--port`/`--delay`/`--verbose`. **21/21 PASS** (2026-05-04). **18/18 PASS** (2026-05-05 con 3 roles, delay 5s) |
| `pyproject.toml` + `uv.lock` | ✅ | gestionado con uv |
| `Dockerfile` | ✅ | `python:3.11-slim` + `uv sync --frozen --no-dev`. CMD: `uv run python main.py`. EXPOSE 8001 |
| `docker-compose.yml` | ✅ | **NUEVO 2026-04-27/28, actualizado 2026-05-05** — DOS servicios: `helpdesk-postgres` (pgvector/pgvector:pg17, puerto 5433:5432) + `helpdesk-agent-v2` (puerto 8001). `depends_on: condition: service_healthy`. `extra_hosts: host.docker.internal:${DOCKER_HOST_IP}` |
| `.dockerignore` | ✅ | **NUEVO 2026-04-27** — excluye `.env`, `*.db`, `vector_store/`, `__pycache__/` |
| `env.docker` | ✅ | **NUEVO 2026-04-27, actualizado 2026-04-28** — template con `host.docker.internal` en lugar de `localhost` para todos los servicios del host (backend, PostgreSQL, Ollama) |
| `docker-up.sh` | ✅ | **2026-04-28, actualizado 2026-05-06** — script producción. Detecta IP del host, inicia Docker si es necesario, levanta stack completo. Funciona en Linux nativo y WSL2 |
| `docker-compose.dev.yml` | ✅ | **NUEVO 2026-05-06** — override de desarrollo: bind mount `.:/app` + volúmenes nombrados `agent_venv_dev` (venv Linux) + `hf_cache_dev` (modelos HF). Uvicorn --reload. Funciona en Linux nativo y WSL2 sin paths hardcodeados |
| `docker-up-dev.sh` | ✅ | **NUEVO 2026-05-06** — script dev. Detecta IP host, inicia Docker si es necesario, espera postgres healthy, arranca agente en foreground con hot reload. Linux nativo + WSL2 |
| `DOCKER_SETUP.txt` | ✅ | **2026-04-28, reescrito 2026-05-06** — guía completa Linux-first: setup, modos dev/prod, comandos, troubleshooting. WSL2 en apéndice |

---

### ⚠️ Implementado pero SIN PROBAR en producción (requiere acceso Odoo API)

| Archivo | Estado | Qué falta verificar |
|---|---|---|
| `adapters/odoo_adapter.py` | ⚠️ implementado, no probado en prod | JSON-RPC 2.0 contra Odoo 15. 8 fixes de producción aplicados: re-auth automático en sesión expirada, `_text_to_html` con escape HTML completo, retry en `_call_kw`. Necesita credenciales reales para validar |
| `_text_to_html()` en odoo_adapter | ⚠️ implementado, no probado | Odoo requiere HTML en `descripcion`, `causa_raiz`, `motivo_resolucion` (tipo `fields.Html`); verificar que se aplica en los 3 campos |
| `usuario_solicitante_id` en `create_ticket` | ⚠️ implementado, no probado | Se envía explícitamente; en Odoo lo setea `@api.onchange`, no JSON-RPC |
| `system_equipment` como campo real | ⚠️ implementado, no probado | Es `Char(tracking=True)` en `ITS_Helpdesk_custom` — confirmado que existe en el módulo real |
| `reopen_ticket` con historial | ⚠️ implementado, no probado | Lee `motivo_resolucion` actual y lo preserva con `<hr/>` separator |
| `approval_status` en `get_ticket_detail` | ⚠️ implementado, no probado | Campo `Selection('pending','approved','rejected')` confirmado en `ITS_Helpdesk_custom`. Sí lo retorna Odoo. |
| Campos SLA (`sla_status`, `deadline_date`, `is_about_to_expire`) | ⚠️ implementado, no probado | `stored=True` en Odoo — confirmado en modelo. Verificar que JSON-RPC los devuelva en `search_read` |
| `approve_ticket` y `reject_ticket` en `OdooAdapter` | ⚠️ implementado, no probado en prod | **COMPLETO 2026-05-05**. `approve_ticket`: escribe `approval_status='approved'` + `approval_date`. `reject_ticket`: escribe `approval_status='rejected'` + `approval_comment` (campo real Odoo 15 — `rejection_reason` NO existe en ITS_Helpdesk_custom). Falta validar contra instancia Odoo real. |

---

### 🔴 Bugs confirmados (pendientes de fix)

> Sin bugs críticos pendientes al 2026-04-28. Los pendientes abiertos son mejoras y flujos incompletos (ver sección ❌ más abajo).

### 📦 Docker — notas de infraestructura (actualizado 2026-05-06)

> **Entorno primario: Linux nativo**. Setup completo en `DOCKER_SETUP.txt`.
> Prerequisito único: `sudo usermod -aG docker $USER && newgrp docker` (una sola vez).
>
> **`host.docker.internal` en Linux nativo**: `host-gateway` resuelve al host correctamente sin configuración adicional. `docker-compose.yml` usa `${DOCKER_HOST_IP:-host-gateway}` — en Linux el default funciona.
>
> **`host.docker.internal` en WSL2**: `host-gateway` resuelve al bridge Docker (`172.17.0.1`), NO al host Windows. Los scripts `docker-up.sh` y `docker-up-dev.sh` detectan el IP real del host via `ip route show default` y exportan `DOCKER_HOST_IP`.
>
> **Acceso desde Windows a puertos Docker-in-WSL2**: WSL2 no auto-forwarda puertos. Requiere `netsh interface portproxy`. Los scripts lo gestionan cuando tienen permisos.
>
> **Modo dev (2026-05-06)**: `docker-compose.dev.yml` usa paths relativos (`.:/app`) — funciona en cualquier OS sin modificar. Volúmenes nombrados `agent_venv_dev` y `hf_cache_dev` persisten venv y modelos entre reinicios.
>
> **[Windows IoT LTSC únicamente]**: Docker Desktop NO soportado (exit -5). Solución: Docker Engine dentro de WSL2. Ver apéndice en `DOCKER_SETUP.txt`.

---

### 🚀 Producción — mejoras para 50 usuarios simultáneos

#### Crítico (rompe bajo carga)

- [x] **[PROD-1] Migrar checkpointer a PostgreSQL** — **COMPLETO 2026-04-27**. `AsyncPostgresSaver` activo en PostgreSQL 18 local. DB: `helpdesk_checkpoints`, user: `helpdesk_agent`. 3 bugs Windows corregidos (ver Bug-W1/W2/W3). Tablas LangGraph creadas: `checkpoints`, `checkpoint_blobs`, `checkpoint_writes`, `checkpoint_migrations`. Verificado con test_rol.py: Creador 4/5, Resueltor 5/5, Supervisor 4/4.
- [x] **[PROD-2] Migrado ChromaDB → pgvector** — **COMPLETO 2026-05-05**. `rag/store.py` reemplazado por `PGVectorRAGStore` usando `langchain_postgres.PGVector`. Mismo `postgres_dsn` del checkpointer — sin servicio extra. Deduplicación via stable IDs `ticket-{id}` (upsert nativo). `count()` via SQL directo con psycopg3. `chromadb` y `langchain-chroma` removidos de `pyproject.toml`. Prerequisito: `CREATE EXTENSION IF NOT EXISTS vector;` (lo hace el store automáticamente).
- [ ] **[PROD-3] Semáforo async en LLM calls** — 50 usuarios pueden generar 50+ LLM calls paralelas, saturando Groq y el fallback OpenRouter. Fix: `asyncio.Semaphore(20)` antes de `agent.ainvoke()` en `core/agent.py`
- [x] **[PROD-4] Thread isolation** — **COMPLETO 2026-04-28**. `thread_id = f"{user_id}:{raw_thread}"` en `api/routes/chat.py` y `api/routes/stream.py`. El cliente puede proporcionar sufijo propio pero el prefijo con user_id autenticado es siempre forzado por el servidor.

#### Medio (degrada bajo carga)

- [ ] **[PROD-5] OdooAdapter async** — `httpx.post` síncrono corre en thread pool (default 40 threads). Bajo carga con Odoo lento, el pool se agota. Fix: migrar a `httpx.AsyncClient` con `await` en `adapters/odoo_adapter.py`
- [x] **[PROD-6] Rate limiting por usuario** — **COMPLETO 2026-05-05**. `api/middleware/rate_limit.py` — sliding window 60s keyed por `user_id`. Configurable via `RATE_LIMIT_PER_MINUTE` en `.env` (default 10). Aplicado en `POST /agent/chat` y `POST /agent/stream`. HTTP 429 con header `Retry-After`. Para multi-worker: reemplazar `_windows` dict por Redis (interface `check_rate_limit(user_id)` no cambia).
- [ ] **[PROD-7] `_creator_context_cache` no sobrevive múltiples workers** — cada worker tiene su propio dict en memoria. Fix: Redis para cache compartido, o documentar restricción de single-worker

#### Observabilidad (operar sin ceguera)

- [ ] **[PROD-8] Health check real** — el `/health` actual siempre devuelve 200. Debe verificar conectividad a Odoo, ChromaDB y LLM. Fix: checks async con timeout corto en `main.py`
- [ ] **[PROD-9] Structured logging con contexto** — logs actuales no incluyen `user_id` ni `thread_id`. Imposible trazar una sesión fallida en producción. Fix: logger con contextvars en cada request
- [ ] **[PROD-10] Métricas de deflexión** — endpoint `GET /agent/metrics` con `deflection_rate`, `avg_satisfaction`, `tickets_deflected`. Files: `api/routes/metrics.py`, `feedback/collector.py`

---

### ❌ Pendiente / No implementado

#### Mejoras identificadas 2026-05-04 (post-test SARA v2)

- [x] **[UX-1] Streaming SSE en `/agent/chat`** — **COMPLETO 2026-05-05**. `api/routes/stream.py` + `core/agent.py:stream_response()` implementados. Bug fix: `on_tool_end` handler en `stream_response()` invalida el creator context cache cuando `create_ticket` tiene éxito (paridad con `get_response()`). Endpoint: `POST /agent/stream`, misma auth y request schema que `/agent/chat`.
- [x] **[UX-2] Idioma hard en prompts** — **COMPLETO 2026-05-05**. Sección `## IDIOMA — REGLA ABSOLUTA E IRROMPIBLE` como PRIMERA sección de `BASE_RULES`, antes de Identidad y Reglas Globales. Verificado: 18/18 tests en español.
- [x] **[UX-3] Confirmación obligatoria del supervisor antes de asignar** — **COMPLETO 2026-05-05**. `NUNCA llames assign_ticket sin confirmación previa` añadido en el paso 3 del flujo de asignación Y en la sección `## Restricciones`. Doble refuerzo necesario — solo en uno el LLM lo ignoraba. Verificado en test T3.3.
- [ ] **[UX-4] Fix detección de duplicados** — `_fetch_creator_context` muestra tickets de distintas categorías como "duplicados". Filtrar por categoría o similitud semántica antes de presentar como posible duplicado.
- [ ] **[RAG-1] Poblar RAG con historial real** — el vector store tiene solo 3 documentos de seed. En producción importar el historial completo de tickets resueltos para que `suggest_solution` sea útil. Implementar endpoint o script de migración.
- [ ] **[RAG-2] Feedback positivo retroalimenta el RAG** — cuando `record_agent_feedback` recibe rating 4–5 para `solution_suggested`, re-insertar el documento con mayor peso (o flag de alta confianza).
- [ ] **[INF-1] Puerto fijo 8002 en `.env`** — el puerto 8001 está bloqueado permanentemente en este equipo por Windows `iphlpsvc`. Cambiar `PORT=8002` en `.env` para no requerir override manual en cada arranque.
- [ ] **[INF-2] Soporte OpenRouter como fallback** — `OPENROUTER_API_KEY` ya está en `.env`. Agregar `_build_openrouter_llm()` en `core/graph.py` como cuarto proveedor, útil cuando Vercel/Groq tienen issues.
- [ ] **[MON-1] Métricas de uso de SARA** — `record_agent_feedback` captura ratings pero no hay dashboard. Implementar `GET /agent/metrics` con `deflection_rate`, `avg_satisfaction`, `tickets_deflected`, `rag_hit_rate`.

#### Flujos incompletos
- [x] **Supervisor: aprobación de tickets** — **RESUELTO 2026-04-24**. `approve_ticket` y `reject_ticket` implementadas en `ticket_tools.py`, `ports/ticket_port.py`, `adapters/express_adapter.py`. Flujo completo en `prompts/supervisor.py`. Backend DEV extendido con columnas `approval_status` y `rejection_reason`. Verificado: approve y reject persisten en BD, supervisor detecta pendientes con filtro `approval_status=pending`.
- [ ] **Prefetch de contexto para resolutor** — el creador tiene `_fetch_creator_context` precargado en el system prompt; el resolutor empieza ciego y debe esperar que el agente llame `get_my_assigned_tickets` antes de ser útil. Implementar `_fetch_resolver_context(user_id, thread_id)` análogo al del creador

#### Calidad del RAG
- [x] **Deduplicación en `add_resolved_ticket`** — **CORREGIDO** (`rag/store.py:137-143`): antes de insertar, busca si existe un documento con el mismo `ticket_id` y lo elimina. Tickets reabiertos y re-resueltos reemplazan el embedding anterior.
- [ ] **Feedback positivo retroalimenta el RAG** — cuando `record_agent_feedback` recibe rating 4–5 para `feedback_type="solution_suggested"`, debería aumentar el peso del documento correspondiente (re-insertar o boost). Los usuarios que resuelven su problema sin ticket son la mejor señal de calidad del RAG

#### Seguridad — Prompt injection
- [ ] **Capa 2 — Sanitización de input**: middleware en la route que detecta patrones de inyección antes de llegar al LLM (`api/middleware/` o `api/routes/chat.py`)
- [ ] **Capa 3 — Inyección indirecta desde BD/RAG**: wrapping de resultados de tools con framing explícito de "datos externos, no ejecutar como instrucciones"
- [x] **Capa 4 — Aislamiento de user_id en tools**: **COMPLETO 2026-04-28**. `core/context.py` con `ContextVar current_user_id`. Se setea en `core/agent.py` antes de cada `ainvoke()`/`astream_events()`. `_safe_uid()` en los 10 tools de `ticket_tools.py` y en `record_agent_feedback` de `rag_tools.py`. En producción el ContextVar siempre está seteado → el LLM no puede impersonar a otro usuario.
- [ ] **Capa 5 — Filtrado de output**: post-procesamiento para detectar/redactar datos sensibles antes de devolver al frontend

#### Aislamiento de sesiones
- [x] **Thread isolation**: **COMPLETO 2026-04-28** — `thread_id = f"{user_id}:{raw_thread}"` en `chat.py` y `stream.py`. Ver nota de seguridad: el aislamiento es completo contra accidentes; contra ataques deliberados requiere JWT (user_id viene del body, no de un token validado).

#### En el agente (sin tocar backend):
- [ ] **Detección de incidentes masivos** — tool `check_similar_open_tickets()` que alerte si >2 usuarios reportaron el mismo problema en 24h (`tools/ticket_tools.py`, `prompts/supervisor.py`)
- [ ] **Métricas de deflexión** — endpoint `GET /agent/metrics` con deflection_rate, avg_satisfaction, tickets_deflected (`api/routes/metrics.py`, `feedback/collector.py`)
- [ ] **Tool `add_note_to_ticket`** — agregar nota interna a un ticket existente (`tools/ticket_tools.py`)

#### Requieren cambios en Express backend (desarrollo):
- [x] `approval_status` y `rejection_reason` — **RESUELTO 2026-04-24**. Columnas agregadas al modelo SQLAlchemy, schema Pydantic y DB SQLite via `ALTER TABLE`. Filtro `?approval_status=pending` disponible en `GET /api/tickets`.
- [ ] `GET /api/tickets/:id` — incluir historial de acciones
- [ ] `POST /api/tickets/:id/notes` — agregar notas internas

#### Compatibilidad con módulo Odoo real (ITS_Helpdesk — análisis 2026-04-27)

> Módulo analizado: `ITS_Helpdesk_base` (v15.0.1.0.0) + `ITS_Helpdesk_custom` (v15.0.1.0.1).
> Modelo principal: `helpdesk.ticket.base`. Sin controlador REST — solo JSON-RPC ORM.
> **17 de 18 campos que usa el agente coinciden exactamente con el módulo real.**

- [ ] **`rejection_reason` no existe en Odoo** — el módulo no define ese campo. El motivo de rechazo en Odoo vive en `approval_comment` (Text, readonly) del ticket o en `helpdesk.ticket.approval.comment`. El `OdooAdapter.reject_ticket()` debe escribir en `approval_comment` en lugar de `rejection_reason`. El campo `rejection_reason` solo existe en el backend Express/SQLite de desarrollo.
- [x] **`approve_ticket` y `reject_ticket` en `OdooAdapter`** — **COMPLETO 2026-05-05**. `approve_ticket`: escribe `approval_status='approved'` + `approval_date=now` (formato `%Y-%m-%d %H:%M:%S`). `reject_ticket`: escribe `approval_status='rejected'` + `approval_comment=reason` (campo real en Odoo — `rejection_reason` del express_adapter no existe en ITS_Helpdesk_custom).
- [ ] **Stage `is_resolve=True` no configurado en datos base** — el campo existe en `helpdesk.ticket.stage` pero ningún stage en el XML de datos tiene `is_resolve=True` explícito. El stage "Resuelto" (seq=110) existe pero el flag no está activo. En producción, `_get_resolve_stage_id()` en `OdooAdapter` fallará hasta que se configure manualmente desde la UI de Odoo o se parchee el XML de datos. Acción: configurar el stage "Resuelto" con `is_resolve=True` en la instancia de Odoo antes de conectar el agente.
- [ ] **`_text_to_html()` debe cubrir `causa_raiz` y `motivo_resolucion`** — estos 3 campos son `fields.Html` en Odoo: `descripcion`, `causa_raiz`, `motivo_resolucion`. Verificar que el `OdooAdapter` aplica `_text_to_html()` en los 3 al escribir, no solo en `descripcion`.
- [ ] **Knowledge base de Odoo** — integrar `helpdesk.knowledge` como segunda fuente de RAG
- [ ] Verificar paginación (`limit`/`offset`) en `get_all_tickets` contra Odoo real
- [ ] Verificar mapping del Chatter de Odoo (`log_ids`, `x_private_note_ids`) a historial del agente
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
| **Bug-W1** (2026-04-27) — `psycopg3 AsyncConnectionPool` incompatible con `ProactorEventLoop` (Windows default). `asyncio.set_event_loop_policy()` en `main.py` llega tarde porque uvicorn crea el loop antes de importar `main.py` | `run.py` (nuevo) | Entry point que crea `asyncio.SelectorEventLoop()` explícitamente y llama `loop.run_until_complete(server.serve())` — bypasea la creación automática de uvicorn |
| **Bug-W2** (2026-04-27) — `graph.py` convertía `postgresql://` → `postgresql+psycopg://` con comentario incorrecto "psycopg3 requires this". `AsyncConnectionPool` rechaza ese formato (es SQLAlchemy, no psycopg3) | `core/graph.py` | Eliminada la transformación de DSN — usar `settings.postgres_dsn` directamente sin modificar |
| **Bug-W3** (2026-04-27) — `checkpointer.setup()` ejecuta `CREATE INDEX CONCURRENTLY` que falla con `ActiveSqlTransaction` porque el pool por defecto usa autocommit=False | `core/graph.py` | Conexión dedicada `psycopg.AsyncConnection.connect(..., autocommit=True)` solo para `setup()`. Pool normal para requests. |
| **Bug-S1** (2026-04-27) — `create_ticket` con `descripcion: str` (required) fallaba con HTTP 500 cuando modelos de fallback OpenRouter omitían el campo. Groq valida el schema server-side antes de llegar a Python | `tools/ticket_tools.py` | `descripcion: str = ""` — opcional en schema, el docstring documenta que es requerida conceptualmente |
| **Bug-RAG-S** (2026-05-04) — `suggest_solution` fallaba HTTP 500 en todos los modelos Groq. Causa raíz: LLM generaba `description` y `category` como objetos JSON en lugar de strings. Groq valida el JSON schema del tool call en su servidor y rechaza con 400 si los tipos no coinciden. El error llega al agente como HTTP 500 | `tools/rag_tools.py` | Parámetros cambiados a `Any` + helper `_to_str()` que coerciona objetos/dicts/None a string. El JSON schema resultante no impone `type: string` → Groq acepta cualquier tipo |
| **Bug-PORT** (2026-05-04) — `run.py` tenía `port=8001` hardcodeado en la config de Uvicorn, ignorando la variable `PORT` del `.env` | `run.py` | Reemplazado `port=8001` por `port=settings.port` + import de `settings` |
| **Bug-UX2** (2026-05-05) — SARA respondía en inglés cuando el contexto del thread se corrompía tras un HTTP 500. La regla de idioma estaba enterrada en la lista de Reglas Globales y cualquier token anterior la sobreescribía | `prompts/base.py` | Sección `## IDIOMA — REGLA ABSOLUTA E IRROMPIBLE` como primera sección de BASE_RULES, antes de Identidad |
| **Bug-UX3** (2026-05-05) — Supervisor: LLM llamaba `assign_ticket` sin esperar confirmación. La instrucción de confirmación solo estaba en el flujo narrativo y el LLM la trataba como sugerencia, no como obligación | `prompts/supervisor.py` | `NUNCA llames assign_ticket sin confirmación` añadido en el paso 3 del flujo Y en sección Restricciones. Solo en uno no era suficiente |
| **Bug-STREAM-CACHE** (2026-05-05) — `stream_response()` no invalidaba el cache de contexto del creador tras `create_ticket` exitoso. `get_response()` sí lo hacía — divergencia entre ambas rutas | `core/agent.py` | Handler `on_tool_end` en `stream_response()` invalida `creator_context_cache` cuando `create_ticket` devuelve `success: True` |

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
