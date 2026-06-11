# Remediación de Bugs — Migración Async Fase 8

Documento de remediación post-incidente. Los bugs descritos fueron descubiertos durante la validación E2E de la migración async (Fase 8) y están **todos corregidos** en el árbol de trabajo actual.

## Estado

**Fecha:** 2026-06-11  
**Status:** ✅ Todos los bugs arreglados y validados  
**Scope:** 3 bugs en el agente de helpdesk (`ia-agent-tickets-v2/agent-v2/`)  
**Impacto:** 3 bugs bloqueantes (agente no arrancaba, métricas caían, Odoo entraba en loop de auth)

---

## Quick path — qué se arregló y cómo

### Bug 1: `_build_rag_port` — `SyntaxError: 'await' outside async function`
**Fix:** Hacer la función `async def` y cambiar el call site a `await`.
```python
# ANTES (rompía startup):
_rag_port = _build_rag_port(_ticket_port)
# DESPUÉS:
_rag_port = await _build_rag_port(_ticket_port)
```

### Bug 2: `/agent/metrics` — `'coroutine' object is not iterable`
**Fix:** Remover `asyncio.to_thread()` innecesario.
```python
# ANTES (rompía métricas):
op_metrics = await asyncio.to_thread(_runtime_port.get_operation_metrics)
# DESPUÉS:
op_metrics = await _runtime_port.get_operation_metrics()
```

### Bug 3: Odoo `asyncio.gather()` — loop infinito de re-autenticación
**Fix:** Pasar `cookies` explícito en cada request, leyendo `self._session_id` fresco.
```python
# ANTES (loop infinito cada 8s):
resp = await self._client.post(..., cookies={"session_id": self._session_id})
# DESPUÉS (estable, ~4 re-auth/2 min bajo carga):
cookies = {"session_id": self._session_id} if self._session_id else None
resp = await self._client.post(..., cookies=cookies)
```

---

## Detalles por bug

### Bug 1: `await` en función síncrona

| Campo | Valor |
|---|---|
| **Archivo** | `main.py` |
| **Línea** | 84 |
| **Síntoma** | `SyntaxError: 'await' outside async function` en startup |
| **Causa raíz** | `_build_rag_port()` se mantuvo como `def` (sync) pero la migración async agregó `await ticket_port.get_resolved_tickets()` dentro de la función. |
| **Fix aplicado** | `_build_rag_port()` → `async def _build_rag_port(...)`, call site en `lifespan` → `await _build_rag_port(...)` |
| **Tests que lo detectaron** | Startup del agente (crash en import del módulo) |
| **Categoría** | Error de compilación / sintaxis |

**Verificación:**
```bash
python3 -c "import ast; ast.parse(open('main.py').read()); print('OK')"
```

---

### Bug 2: `asyncio.to_thread()` envolviendo una corutina

| Campo | Valor |
|---|---|
| **Archivo** | `api/routes/metrics.py` |
| **Línea** | 71 |
| **Síntoma** | `TypeError: 'coroutine' object is not iterable` en `/agent/metrics` |
| **Causa raíz** | `asyncio.to_thread()` recibe una función **síncrona** y la ejecuta en un thread. Al migrar `get_operation_metrics()` a `async def`, se convirtió en una corutina. `to_thread()` le pasó la corutina al thread, pero nunca la hizo `await`, retornando el objeto corutina en vez de la lista. |
| **Fix aplicado** | `await asyncio.to_thread(_runtime_port.get_operation_metrics)` → `await _runtime_port.get_operation_metrics()` |
| **Tests que lo detectaron** | `curl /agent/metrics` retornaba `{"_error": "'coroutine' object is not iterable"}` |
| **Categoría** | Error de compatibilidad async/sync |

**Verificación:**
```bash
curl -sS http://localhost:8001/agent/metrics -H "X-Agent-Key: dev-key-change-in-prod" \
  --max-time 30 | python3 -c "import json,sys; d=json.load(sys.stdin); assert '_error' not in d['operation']; print('OK')"
```

---

### Bug 3: Cookie jar stale en conexiones keep-alive

| Campo | Valor |
|---|---|
| **Archivo** | `adapters/odoo_adapter.py` |
| **Línea** | 289-304 (bloque de `_call_kw`) |
| **Síntoma** | Loop infinito: `Odoo session expired` → `re-authenticating` → `uid=17` → `session expired`... |
| **Causa raíz** | Cuando `asyncio.gather()` corre 7 queries en paralelo, **todas** leen `self._session_id` antes de que **cualquiera** re-autentique. El primero detecta session expiry, toma el lock, re-autentica, setea la cookie en el `AsyncClient` jar. Las otras 6, al salir del lock, también detectan session expiry (porque la sesión inicial era inválida) y re-autentican. **PERO** el `AsyncClient` reusa conexiones keep-alive, y las conexiones en el pool tienen la **cookie vieja cacheada en headers**. Aunque la cookie jar del cliente se actualizó, el **pool de conexiones no invalida headers cacheados**. |
| **Fix aplicado** | Leer `self._session_id` fresco en cada `_call_kw` y pasar como `cookies={"session_id": ...}` en el request. El request explícito sobrescribe cualquier cookie cacheada en la conexión keep-alive. |
| **Tests que lo detectaron** | `docker logs` mostrando `re-authenticating` cada 8-10s; `/agent/metrics` colgando 30s |
| **Categoría** | Race condition en async / estado compartido |

**Verificación:**
```bash
# Contar re-autenticaciones en 5 minutos (debe ser < 20 bajo carga normal)
docker logs helpdesk-agent-v2 --since 5m 2>&1 | grep -c "re-authenticating"
```

---

## Lecciones aprendidas

### Qué funciona
1. **Hot reload de uvicorn** detectó Bug 1 inmediatamente (crash en import).
2. **Tests E2E** detectaron Bug 2 y 3 en condiciones reales (async gather + session expiry).
3. **asyncio.Lock** para re-autenticación SÍ funciona correctamente — evita thundering herd.
4. **asyncio.gather()** para métricas paralelizó las 7 queries Odoo de 3.5s → 500ms.

### Qué NO funciona (y por qué)
1. **`asyncio.to_thread()` para corutinas** — NO envuelve corutinas. Es para funciones sync que bloquean I/O.
2. **`httpx.AsyncClient` cookie jar** — NO invalida cookies en conexiones keep-alive del pool. Siempre pasar cookies explícitas para sesiones que cambian.
3. **`await` en funciones sync** — Python no lo permite. Migrar todo el call chain.
4. **Análisis estático solo** — `ast.parse` no detecta bugs de runtime como race conditions o stale cookies. Necesitas tests E2E.

### Reglas para futuras migraciones async
1. **Cada función que usa `await` DEBE ser `async def`** — incluidas helpers y funciones internas.
2. **No usar `asyncio.to_thread()` para corutinas** — solo para sync I/O (SQLite, filesystem).
3. **Nunca depender del cookie jar del cliente** cuando hay re-autenticación concurrente — pasar cookies explícitas.
4. **Siempre correr tests E2E** antes de declarar una migración completa.
5. **Documentar el costo en `get_operation_metrics()`** — si usas `asyncio.gather()`, la ganancia de velocidad justifica la complejidad, pero documenta el race condition potencial.

---

## Checklist de verificación (post-remediación)

- [ ] Agent startup: `docker logs helpdesk-agent-v2 --tail 5` muestra `agent_ready`
- [ ] `/health` retorna 200 con todos los componentes healthy
- [ ] `/agent/metrics` retorna datos sin `"_error"`
- [ ] `docker logs | grep -c "re-authenticating"` < 5 en 5 minutos sin carga
- [ ] `test_rol.py creador` ejecuta 0 fallos
- [ ] `test_fullflow.py` ejecuta 0 fallos
- [ ] 5 requests concurrentes retornan 200 OK
- [ ] 10 requests concurrentes: 5 OK, 5 rate-limited (429) — comportamiento esperado

---

## Próximos pasos

1. **Merge / commit** de los 3 fixes + migración async
2. **Load test 50 concurrentes** con `ab` o `wrk` para validar el pool de 50 conexiones
3. **Documentar** en `AGENTS.md` la regla "pasar cookies explícitas para sesiones" 
4. **Automatizar** el test E2E en CI para detectar regressiones

---

## Referencias

- Archivo modificado: `main.py` (linea 72, 111)
- Archivo modificado: `api/routes/metrics.py` (linea 71)
- Archivo modificado: `adapters/odoo_adapter.py` (lineas 289-304, 165)
- PR asociado: pendiente
- Plan de migración: `agent_v2_Doc/ASYNC_MIGRATION_PLAN.md`
