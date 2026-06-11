# Plan de Migración: Arquitectura Async Completa (Fase 8)

> **Fecha:** 2026-06-10
> **Versión:** 1.0 (pendiente de aprobación)
> **Estado:** PLAN — no implementar hasta aprobación
> **Duración estimada:** 10-14 horas
> **Días de trabajo:** 2-3 días

---

## 1. Contexto y Estado Actual

### 1.1 Stack de versiones

| Componente | Versión actual | Nota |
|---|---|---|
| Python | 3.11+ | Required |
| FastAPI | 0.135.3 | Nativamente async |
| LangGraph | 1.1.6 | **Soporta async tools nativamente** |
| httpx | 0.28.1 | AsyncClient disponible |
| langgraph-checkpoint-postgres | 2.0.13 | AsyncPostgresSaver ya async |
| psycopg | 3.2.0 | Async compatible |

**LangGraph 1.1.6 soporta async tools nativamente.** `create_react_agent` puede recibir tools async y las ejecuta en el event loop sin thread pool.

### 1.2 Arquitectura actual (sync en tools)

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Frontend       │────▶│  FastAPI        │────▶│  LangGraph      │────▶│  Tool (SYNC)    │────▶┌─────────────────┐
│  (async)        │     │  (async)        │     │  (async)        │     │  def create_    │     │  httpx.post     │
│                 │     │                 │     │  ainvoke()      │     │  ticket()       │     │  (SYNC)         │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘     │  Odoo 15        │
                                                                                                   │  JSON-RPC       │
                                                                                                   └─────────────────┘
                                                                                                           ▲
                                                                                                           │
                                                                                                    asyncio.to_thread()
                                                                                                    (40 threads max)
```

**El problema:** `asyncio.to_thread()` usa `ThreadPoolExecutor` con **40 threads por default**. Cada llamada a Odoo (~500ms) ocupa un thread. Con 50 usuarios concurrentes × 2 llamadas/turno = 100 threads necesarios. El pool se satura.

### 1.3 Arquitectura objetivo (async completo)

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│  Frontend       │────▶│  FastAPI        │────▶│  LangGraph      │────▶│  Tool (ASYNC)   │────▶│  httpx.AsyncClient │
│  (async)        │     │  (async)        │     │  (async)        │     │  async def      │     │  (ASYNC)          │
│                 │     │                 │     │  ainvoke()      │     │  create_ticket()│     │  pool=50          │
└─────────────────┘     └─────────────────┘     └─────────────────┘     └─────────────────┘     │  Odoo 15        │
                                                                                                   │  JSON-RPC       │
                                                                                                   └─────────────────┘
```

**Sin threads.** Todo corre en el event loop. El único límite es el pool de conexiones de `httpx.AsyncClient` (configurable, default 50).

---

## 2. Alcance de la Migración

### 2.1 Archivos a modificar

| # | Archivo | Cambios | Complejidad |
|---|---|---|---|
| 1 | `ports/ticket_port.py` | Todos los métodos abstractos → `async def` | 🔴 Alta |
| 2 | `adapters/odoo_adapter.py` | Todo → `async def` + `httpx.AsyncClient` | 🔴 Alta |
| 3 | `adapters/express_adapter.py` | Todo → `async def` + `httpx.AsyncClient` | 🟡 Media |
| 4 | `adapters/http_adapter.py` | Todo → `async def` + `httpx.AsyncClient` | 🟡 Media |
| 5 | `tools/ticket_tools.py` | Todas las tools → `async def` | 🟡 Media |
| 6 | `tools/user_tools.py` | Todas las tools → `async def` | 🟡 Media |
| 7 | `tools/rag_tools.py` | `suggest_solution` + `record_agent_feedback` → `async def` | 🟡 Media |
| 8 | `core/agent.py` | `get_response()` y `stream_response()` → await en tools | 🟡 Media |
| 9 | `core/graph.py` | `build_llm()` → retornar LLM con async tools | 🟢 Baja |
| 10 | `main.py` | Lifespan → `AsyncClient` initialization | 🟢 Baja |
| 11 | `config/settings.py` | Agregar `httpx_max_connections`, `httpx_max_keepalive` | 🟢 Baja |
| 12 | `api/routes/health.py` | Health check → async calls | 🟢 Baja |
| 13 | `scratch/test_rol.py` | Tests → `async` | 🟡 Media |
| 14 | `scratch/test_sara.py` | Tests → `async` | 🟡 Media |

**Total: 14 archivos.**

### 2.2 Archivos NO a modificar

| Archivo | Por qué no cambia |
|---|---|
| `feedback/collector.py` | SQLite es sync, pero el thread pool de LangGraph ya lo maneja. Se puede dejar sync o hacer async con `aiosqlite`. |
| `rag/store.py` | `PGVector` de `langchain_postgres` ya es async internamente. |
| `core/logging.py` | Logging es sync por naturaleza. |
| `api/routes/auth.py` | FastAPI dependency functions — ya pueden ser async. |
| `api/middleware/rate_limit.py` | Dict en memoria — sync es suficiente. |
| `prompts/*.py` | Solo strings, no I/O. |

---

## 3. Detalle de la Migración por Archivo

### 3.1 Fase A: Ports y Adapters (fundamento)

#### 3.1.1 `ports/ticket_port.py` — Interface abstracta

**Cambio:** Todos los métodos abstractos cambian a `async def`.

```python
# ANTES:
class ITicketPort(ABC):
    @abstractmethod
    def create_ticket(self, payload: dict, user_id: int) -> dict: ...
    @abstractmethod
    def get_tickets_by_creator(self, user_id: int) -> list: ...

# DESPUÉS:
class ITicketPort(ABC):
    @abstractmethod
    async def create_ticket(self, payload: dict, user_id: int) -> dict: ...
    @abstractmethod
    async def get_tickets_by_creator(self, user_id: int) -> list: ...
```

**Impacto:** Todos los adapters (Odoo, Express, Http) deben implementar `async`.

**Nota:** `async` en `ABC` es compatible. Los métodos abstractos pueden ser `async def` y los implementadores también deben ser `async def`.

---

#### 3.1.2 `adapters/odoo_adapter.py` — Adapter Odoo

**Cambio 1:** `httpx.post` → `httpx.AsyncClient` con pool de conexiones.

```python
# ANTES:
class OdooAdapter(ITicketPort):
    def __init__(self):
        self._base_url = settings.odoo_base_url.rstrip("/")
        # ...
    def _call_kw(self, ...):
        resp = httpx.post(..., timeout=30.0)

# DESPUÉS:
class OdooAdapter(ITicketPort):
    def __init__(self):
        self._base_url = settings.odoo_base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(
                max_connections=settings.httpx_max_connections,
                max_keepalive_connections=settings.httpx_max_keepalive,
            ),
        )
    
    async def _call_kw(self, ...):
        resp = await self._client.post(...)
```

**Cambio 2:** Todos los métodos públicos cambian a `async def`.

```python
# ANTES:
def get_tickets_by_creator(self, user_id: int) -> list:
    return self._call_kw(...)

# DESPUÉS:
async def get_tickets_by_creator(self, user_id: int) -> list:
    return await self._call_kw(...)
```

**Cambio 3:** `_authenticate()` ahora es async.

```python
# ANTES:
def _authenticate(self):
    resp = httpx.post(...)

# DESPUÉS:
async def _authenticate(self):
    resp = await self._client.post(...)
```

**Cambio 4:** `_ensure_session()` ahora es async.

```python
# ANTES:
def _ensure_session(self):
    if not self._session_id:
        self._authenticate()

# DESPUÉS:
async def _ensure_session(self):
    if not self._session_id:
        await self._authenticate()
```

**Cambio 5:** Métodos auxiliares que usan `_call_kw` → `await self._call_kw(...)`.

```python
# ANTES:
def _get_resolve_stage_id(self) -> int:
    stages = self._call_kw("helpdesk.ticket.stage", "search_read", ...)

# DESPUÉS:
async def _get_resolve_stage_id(self) -> int:
    stages = await self._call_kw("helpdesk.ticket.stage", "search_read", ...)
```

**Nota importante:** `_get_resolve_stage_id()` y `_get_start_stage_id()` son métodos privados que usan `_call_kw`. Todos deben cambiar a `async def`.

**Cambio 6:** `get_operation_metrics()` (la métrica que implementamos en Fase 1) → `async def`.

```python
# ANTES:
def get_operation_metrics(self) -> dict:
    approved = self._call_kw(...)
    closed = self._call_kw(...)
    by_cat = self._call_kw(...)

# DESPUÉS:
async def get_operation_metrics(self) -> dict:
    approved = await self._call_kw(...)
    closed = await self._call_kw(...)
    by_cat = await self._call_kw(...)
    # NOTA: Las 3 llamadas son independientes — podrían hacerse en paralelo con asyncio.gather()
```

**Optimización opcional:** `asyncio.gather()` para llamadas paralelas.

```python
# Las 3 llamadas a Odoo son independientes → paralelizar:
approved, closed, by_cat = await asyncio.gather(
    self._call_kw(...),  # approved
    self._call_kw(...),  # closed
    self._call_kw(...),  # by_cat
)
```

**Beneficio:** `get_operation_metrics()` pasa de 3×500ms = 1500ms a 500ms (paralelo).

---

#### 3.1.3 `adapters/express_adapter.py` — Adapter Express

**Cambio 1:** `httpx.Client` → `httpx.AsyncClient`.

```python
# ANTES:
class ExpressAdapter(ITicketPort):
    def _get(self, path, params=None):
        with httpx.Client(timeout=30.0) as client:
            response = client.get(...)

# DESPUÉS:
class ExpressAdapter(ITicketPort):
    def __init__(self, base_url):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.AsyncClient(
            timeout=30.0,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=20),
        )
    
    async def _get(self, path, params=None):
        response = await self._client.get(...)
```

**Cambio 2:** Métodos públicos → `async def`.

```python
# ANTES:
def get_tickets_by_creator(self, user_id: int) -> list:
    return self._get("/api/tickets", {"created_by": user_id})

# DESPUÉS:
async def get_tickets_by_creator(self, user_id: int) -> list:
    return await self._get("/api/tickets", {"created_by": user_id})
```

**Nota:** Los `_post`, `_put`, `_get` internos ahora usan `self._client` (AsyncClient) en vez de `with httpx.Client() as client:`.

---

### 3.2 Fase B: Tools (capa de LangGraph)

#### 3.2.1 `tools/ticket_tools.py` — 10 tools

**Cambio:** Todos los `@tool` cambian a `async def`.

```python
# ANTES:
@tool
@backend_retry
def create_ticket(...):
    return _port.create_ticket(...)

# DESPUÉS:
@tool
@backend_retry
async def create_ticket(...):
    return await _port.create_ticket(...)
```

**Tools afectadas:**
1. `create_ticket`
2. `get_my_created_tickets`
3. `get_ticket_detail`
4. `resolve_ticket`
5. `update_ticket`
6. `get_all_tickets`
7. `assign_ticket`
8. `reopen_ticket`
9. `approve_ticket`
10. `reject_ticket`

**Nota:** `_safe_uid()` y `_resolve_id()` son sync internos (no tocan I/O). No necesitan cambiar.

**Nota:** `get_resolver_tools()`, `get_creator_tools()`, `get_supervisor_tools()` devuelven **listas de funciones**. No cambian. Lo que cambia es que cada función en la lista es `async`.

**LangGraph 1.1.6 soporta esto nativamente.** `create_react_agent` detecta automáticamente si una tool es `async` y la ejecuta en el event loop sin thread pool.

---

#### 3.2.2 `tools/user_tools.py` — Catalog tools

**Cambio:** Todos los `@tool` cambian a `async def`.

```python
# ANTES:
@tool
def get_ticket_types(...):
    return _port.get_ticket_types()

# DESPUÉS:
@tool
async def get_ticket_types(...):
    return await _port.get_ticket_types()
```

**Tools afectadas:**
1. `get_ticket_types`
2. `get_categories`
3. `get_urgency_levels`
4. `get_impact_levels`
5. `get_priority_levels`
6. `get_resolvers`
7. `get_agent_groups`
8. `get_stages`

---

#### 3.2.3 `tools/rag_tools.py` — RAG tools

**Cambio:** `suggest_solution` y `record_agent_feedback` → `async def`.

```python
# ANTES:
@tool
def suggest_solution(description: Any, category: Any = "") -> str:
    result = _rag_port.search_similar(...)

# DESPUÉS:
@tool
async def suggest_solution(description: Any, category: Any = "") -> str:
    result = await _rag_port.search_similar(...)
```

**Nota:** `_rag_port.search_similar()` viene de `rag/store.py`. `PGVector` ya soporta async? Necesito verificar.

**Investigación:** `langchain_postgres.PGVector` tiene `asimilarity_search()`? No, la API de LangChain es sync. Pero `PGVector` usa `sqlalchemy` internamente, que puede ser async con `AsyncSession`.

**Alternativa:** Si `PGVector` no soporta async, usar `asyncio.to_thread()` solo para `search_similar()` (es rápida, <100ms). El resto de la tool sigue siendo async.

**Verificación:** `langchain_postgres.PGVector` en `rag/store.py`.

```python
# Verificar si PGVector tiene método async
# En rag/store.py:
from langchain_postgres import PGVector
# PGVector.similarity_search() es sync
# Pero podemos usar asyncio.to_thread() para la búsqueda
```

**Decisión:** Dejar `search_similar` como sync dentro de `asyncio.to_thread()` (es rápida). La tool `suggest_solution` sigue siendo `async` pero la llamada interna a RAG usa `to_thread()`.

---

### 3.3 Fase C: Core Agent (orquestación)

#### 3.3.1 `core/agent.py` — `get_response()` y `stream_response()`

**Cambio:** `await` en las tools en vez de `asyncio.to_thread()`.

```python
# ANTES (get_response):
async def get_response(agent, ...):
    result = await agent.ainvoke(input_data, config)
    # LangGraph ejecuta tools en ThreadPoolExecutor
    # porque las tools son sync

# DESPUÉS (get_response):
async def get_response(agent, ...):
    result = await agent.ainvoke(input_data, config)
    # LangGraph ejecuta tools directamente en el event loop
    # porque las tools son async
```

**No hay cambios visibles en `get_response()`**. El cambio es que `agent.ainvoke()` ya no necesita `asyncio.to_thread()` para las tools. LangGraph las ejecuta directamente.

**Borrar:** El código que usa `asyncio.to_thread()` para tools ya no es necesario.

```python
# ANTES (en tools o en el adapter):
# asyncio.to_thread(_port.create_ticket, ...)  # ← BORRAR

# DESPUÉS:
# await _port.create_ticket(...)  # ← ASÍ
```

**Cambio en `_track_llm_call()`:** El tracking ya funciona con async. No hay cambios.

---

### 3.4 Fase D: Configuración y Main

#### 3.4.1 `config/settings.py` — Nuevos parámetros

```python
class Settings(BaseSettings):
    # ... existentes ...
    
    # httpx AsyncClient pool settings
    httpx_max_connections: int = 50
    httpx_max_keepalive: int = 20
    
    # Thread pool (legacy, for sync adapters only)
    thread_pool_max_workers: int = 50
```

---

#### 3.4.2 `main.py` — Lifespan

```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    # ... existente ...
    
    # Cambio: los adapters ahora son async
    # pero no necesitan initialization especial
    # El AsyncClient se crea en __init__ del adapter
    
    yield
    
    # Shutdown: cerrar AsyncClient
    if _ticket_port is not None:
        await _ticket_port.close()  # si tiene AsyncClient
```

**Nota:** `httpx.AsyncClient` debe cerrarse explícitamente en shutdown para liberar conexiones.

---

### 3.5 Fase E: Cache compartido (PostgreSQL)

#### 3.5.1 Implementación del cache

```python
# core/cache.py
import asyncio
import json
from datetime import datetime, timedelta
from config.settings import settings

class PostgreSQLCache:
    """
    Shared cache using PostgreSQL (already running for checkpointer).
    Replaces _creator_context_cache dict for multi-worker environments.
    """
    def __init__(self, ttl_seconds: int = 3600):
        self._ttl = ttl_seconds
        self._dsn = settings.postgres_dsn
    
    async def _get_conn(self):
        import psycopg
        return await psycopg.AsyncConnection.connect(self._dsn)
    
    async def _ensure_table(self):
        async with await self._get_conn() as conn:
            await conn.execute("""
                CREATE TABLE IF NOT EXISTS agent_cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    expires_at TIMESTAMP NOT NULL
                )
            """)
            await conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_agent_cache_expires 
                ON agent_cache(expires_at)
            """)
    
    async def get(self, key: str) -> str | None:
        async with await self._get_conn() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    "SELECT value FROM agent_cache WHERE key = %s AND expires_at > NOW()",
                    (key,)
                )
                row = await cur.fetchone()
                return row[0] if row else None
    
    async def set(self, key: str, value: str):
        expires = datetime.now() + timedelta(seconds=self._ttl)
        async with await self._get_conn() as conn:
            await conn.execute(
                """INSERT INTO agent_cache (key, value, expires_at)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    expires_at = EXCLUDED.expires_at""",
                (key, value, expires)
            )
    
    async def delete(self, key: str):
        async with await self._get_conn() as conn:
            await conn.execute("DELETE FROM agent_cache WHERE key = %s", (key,))
    
    async def clear_expired(self):
        async with await self._get_conn() as conn:
            await conn.execute("DELETE FROM agent_cache WHERE expires_at <= NOW()")
```

**Integración en `core/agent.py`:**

```python
# ANTES:
_creator_context_cache: dict = {}

# DESPUÉS:
from core.cache import PostgreSQLCache
_cache = PostgreSQLCache(ttl_seconds=3600)

async def _fetch_creator_context(user_id, thread_id):
    cached = await _cache.get(f"creator_ctx:{thread_id}")
    if cached:
        return cached
    # ... fetch from Odoo ...
    await _cache.set(f"creator_ctx:{thread_id}", result)
    return result
```

**Nota:** `invalidate_creator_context()` ahora hace `await _cache.delete(...)`.

**Nota:** `_fetch_resolver_context()` (si se implementa) también usa `_cache`.

---

## 4. Tests y Verificación

### 4.1 Tests unitarios

```python
# test_async_tools.py
import pytest
import asyncio

@pytest.mark.asyncio
async def test_create_ticket_async():
    from tools.ticket_tools import create_ticket
    result = await create_ticket(
        asunto="Test",
        descripcion="Desc",
        ticket_type_id=1,
        category_id=1,
        urgency_id=1,
        impact_id=1,
        priority_id=1,
        user_id=1,
    )
    assert result["success"]

@pytest.mark.asyncio
async def test_get_tickets_by_creator_async():
    from tools.ticket_tools import get_my_created_tickets
    tickets = await get_my_created_tickets(user_id=1)
    assert isinstance(tickets, list)

@pytest.mark.asyncio
async def test_approve_ticket_async():
    from tools.ticket_tools import approve_ticket
    result = await approve_ticket(ticket_id=2854, user_id=53)
    assert result["success"]
```

### 4.2 Tests E2E

```bash
# Test E2E completo
python scratch/test_rol.py creador --delay 5
python scratch/test_rol.py resueltor --delay 5
python scratch/test_rol.py supervisor --delay 5

# Test de carga
ab -n 100 -c 50 -p payload.json -T "application/json" \
  http://localhost:8001/agent/chat
```

### 4.3 Checklist de verificación

- [ ] `test_rol.py` creador: 5/5 PASS
- [ ] `test_rol.py` resueltor: 5/5 PASS
- [ ] `test_rol.py` supervisor: 4/4 PASS
- [ ] `test_sara.py` flujo completo: PASS
- [ ] `/health` responde con todos los componentes OK
- [ ] Load test: 50 requests concurrentes, 95th percentile < 10s
- [ ] Cache funciona: mensaje 1 llena cache, mensaje 2 lee cache (sin round-trip)
- [ ] Cache invalidación: `create_ticket` → cache borrado
- [ ] PostgreSQL: tabla `agent_cache` creada automáticamente
- [ ] Metrics: `/agent/metrics` responde con todas las secciones
- [ ] Dashboard Odoo: 8 KPIs visibles

---

## 5. Cronograma

| Día | Fase | Archivos | Esfuerzo |
|---|---|---|---|
| **Día 1** | A.1 + A.2 | `ticket_port.py`, `odoo_adapter.py` | 4h |
| **Día 1** | A.3 | `express_adapter.py`, `http_adapter.py` | 1h |
| **Día 2** | B.1 + B.2 + B.3 | `ticket_tools.py`, `user_tools.py`, `rag_tools.py` | 3h |
| **Día 2** | C.1 + D.1 + D.2 | `core/agent.py`, `config/settings.py`, `main.py` | 2h |
| **Día 3** | E | Cache PostgreSQL (`core/cache.py`) | 1.5h |
| **Día 3** | Tests | `test_rol.py`, `test_sara.py`, load test | 2h |
| **Día 3** | Docs | `IMPLEMENTATION.txt`, `CAMBIOS_SARA.md` | 1h |

**Total: 14.5 horas** (3 días)

---

## 6. Riesgos y Mitigaciones

| Riesgo | Probabilidad | Impacto | Mitigación |
|---|---|---|---|
| **LangGraph no ejecuta async tools correctamente** | Media | Alto | Verificar con `test_rol.py` antes de tocar el resto. Si falla, abortar y mantener sync. |
| **Odoo JSON-RPC async + cookies + sesiones** | Media | Alto | El `AsyncClient` mantiene cookies igual que `Client`. Testear `authenticate()` primero. |
| **PGVector no soporta async** | Baja | Medio | Usar `asyncio.to_thread()` solo para `search_similar()` (rápida). |
| **Tests rotos** | Alta | Medio | `test_rol.py` y `test_sara.py` necesitan `async`. Tiempo: 1h. |
| **Cache PostgreSQL lento** | Baja | Medio | TTL de 1h. Si es lento, usar `asyncio.Lock()` para evitar N round-trips simultáneos. |
| **Rollback complejo** | Baja | Alto | Todos los commits separados por fase. Revertir con `git revert` por fase. |

---

## 7. Rollback Plan

Si la migración async falla, el rollback se hace por fases:

```bash
# Fase 1: Revertir tools (sync)
git revert <commit-tools-async>

# Fase 2: Revertir adapters (sync)
git revert <commit-adapters-async>

# Fase 3: Revertir cache (dict)
git revert <commit-cache-postgres>

# Fase 4: Revertir ports (sync)
git revert <commit-ports-async>

# Test: test_rol.py debe pasar 100%
```

**Tiempo de rollback:** 15 minutos por fase.

---

## 8. Decisiones Pendientes del Usuario

Antes de implementar, confirmar:

### 8.1 ¿PostgreSQL como cache compartido?
- ✅ **Sí** (ya confirmado) → Usar tabla `agent_cache` en PostgreSQL

### 8.2 ¿Pool de conexiones httpx?
- **50 conexiones** (recomendado para 50 usuarios)
- **100 conexiones** (más seguro, más RAM)

### 8.3 ¿TTL del cache?
- **3600 segundos (1h)** (recomendado)
- **1800 segundos (30min)** (más fresco, más round-trips)

### 8.4 ¿Orden de implementación?
- **Opción A (recomendada):** Fase A → B → C → D → E (ports → adapters → tools → core → cache)
- **Opción B:** Fase A → E → B → C → D (ports → cache → adapters → tools → core)

### 8.5 ¿Feature flag para sync fallback?
- **Sí** (recomendado) → `settings.enable_async_tools` (default True, puede revertir a False)
- **No** → Migración completa, sin fallback

---

## 9. Cómo Aprobar este Plan

Para aprobar este plan y comenzar la implementación:

1. ¿Aprobás el plan en general? (Sí/No)
2. ¿Pool de conexiones: 50 o 100?
3. ¿TTL del cache: 3600s o 1800s?
4. ¿Orden: A→B→C→D→E (recomendada) o A→E→B→C→D?
5. ¿Feature flag para sync fallback? (Sí/No)

Una vez aprobado, empiezo la implementación con **Fase A: Ports + Adapters** y te muestro progreso en cada fase.

---

**Documento generado:** 2026-06-10
**Versión:** 1.0
**Estado:** PLAN — esperando aprobación del usuario
**Stack:** LangGraph 1.1.6 | FastAPI 0.135.3 | httpx 0.28.1 | Python 3.11+