# IA Helpdesk Agent v2 — SARA

Microservicio de IA (LangGraph ReAct) para gestión de tickets de helpdesk empresarial.
Arquitectura hexagonal. Backend de producción: Odoo 15. Backend de desarrollo: FastAPI+SQLite local.

---

## Arrancar el agente (entorno de desarrollo)

### Prerequisitos (una sola vez)
```bash
# 1. Agregar usuario al grupo docker
sudo usermod -aG docker $USER && newgrp docker

# 2. Verificar
docker ps
```

### Backend (terminal 1)
```bash
cd ia-agent-tickets-v2/backend
source venv/bin/activate          # o: python -m venv venv && source venv/bin/activate && pip install -r requirements.txt
python populate_db.py             # solo primera vez — siembra tickets de prueba
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
Verifica: `curl http://localhost:8000/docs`

### Agente en Docker con hot reload (terminal 2)
```bash
cd ia-agent-tickets-v2/agent/agent-v2
bash docker-up-dev.sh
```

El script:
1. Detecta IP del host para `host.docker.internal`
2. Inicia Docker si no está corriendo
3. Levanta postgres (pgvector/pg17) y espera que esté healthy
4. Arranca el agente con `uvicorn --reload` — cambios en `.py` recargan en ~2s

Primer arranque: descarga modelo HuggingFace `all-MiniLM-L6-v2` al volumen `hf_cache_dev` (~90MB, 1-2 min). Los arranques siguientes son <5s.

Verifica: `curl http://localhost:8001/health`

### Detener
- Agente: `Ctrl+C` en terminal 2
- Todo el stack: `docker compose -f docker-compose.yml -f docker-compose.dev.yml down`

---

## Variables de entorno

El agente en Docker usa `env.docker` (ya relleno con credenciales de dev).
Contiene: `AI_GATEWAY_API_KEY`, `GROQ_API_KEY`, `OPENROUTER_API_KEY`, `POSTGRES_DSN`, etc.

**No crear `.env` nuevo** — `env.docker` es el archivo correcto para Docker dev.

Para desarrollo local sin Docker (no recomendado):
```bash
cp env.docker .env
# Cambiar POSTGRES_DSN, BACKEND_URL y PORT según el entorno local
```

---

## Probar el agente

```bash
# Health
curl http://localhost:8001/health

# Chat (rol: creador | resueltor | supervisor)
curl -X POST http://localhost:8001/agent/chat \
  -H "Content-Type: application/json" \
  -H "X-Agent-Key: dev-key-change-in-prod" \
  -d '{"user_id":1,"user_rol":"creador","message":"Quiero reportar un problema","thread_id":"test-001"}'

# Streaming SSE
curl -N -X POST http://localhost:8001/agent/stream \
  -H "Content-Type: application/json" \
  -H "X-Agent-Key: dev-key-change-in-prod" \
  -d '{"user_id":1,"user_rol":"creador","message":"Hola","thread_id":"test-001"}'
```

---

## Stack técnico

| Componente | Tecnología |
|---|---|
| Framework agente | LangGraph ReAct |
| LLM primario | `xai/grok-4.1-fast-non-reasoning` vía Vercel AI Gateway |
| LLM fallback 1 | Groq `meta-llama/llama-4-scout-17b-16e-instruct` |
| LLM fallback 2 | OpenRouter (5 modelos free con tool calling) |
| Checkpointer | AsyncPostgresSaver (PostgreSQL) |
| Vector store | pgvector (`langchain_postgres.PGVector`) |
| Embeddings | `all-MiniLM-L6-v2` (HuggingFace, local) |
| API | FastAPI + uvicorn |
| Package manager | `uv` — NUNCA usar `pip install` directo |

---

## Estructura del proyecto

```
agent-v2/
├── CLAUDE.md               ← este archivo
├── docker-compose.yml      ← stack base (postgres + agent)
├── docker-compose.dev.yml  ← override dev (hot reload, bind mount)
├── docker-up-dev.sh        ← script arranque dev (Linux + WSL2)
├── docker-up.sh            ← script arranque prod
├── env.docker              ← variables de entorno para Docker
├── Dockerfile              ← imagen de producción
├── main.py                 ← bootstrap FastAPI (lifespan)
├── run.py                  ← entry point Windows (SelectorEventLoop fix)
├── config/settings.py      ← Pydantic Settings — single source of truth
├── ports/                  ← interfaces abstractas (ITicketPort, IRAGPort)
├── adapters/
│   ├── express_adapter.py  ← DEV: FastAPI+SQLite local (puerto 8000)
│   └── odoo_adapter.py     ← PROD: Odoo 15 JSON-RPC (implementado, no probado)
├── rag/store.py            ← PGVectorRAGStore (pgvector + langchain_postgres)
├── tools/                  ← ticket_tools, user_tools, rag_tools
├── prompts/                ← base, creator, resolver, supervisor
├── core/
│   ├── graph.py            ← LLM init + checkpointer factory
│   └── agent.py            ← inyección de ports, roles, get_response/stream_response
├── api/routes/             ← /agent/chat, /agent/stream, /agent/invoke
└── agent_v2_Doc/PLAN.md    ← estado completo del proyecto + backlog
```

---

## Roles del agente

| Rol | Tools disponibles | Responsabilidad |
|---|---|---|
| `creador` | create_ticket, get_my_created_tickets, suggest_solution, record_feedback | Usuarios que reportan problemas |
| `resolutor` | get_my_assigned_tickets, resolve_ticket, update_ticket, suggest_solution | Técnicos que resuelven tickets |
| `supervisor` | get_all_tickets, assign_ticket, approve_ticket, reject_ticket, reopen_ticket | Gestores del helpdesk |

---

## Convenciones

- **Package manager**: `uv` siempre. `uv add <pkg>`, `uv run python`, `uv run uvicorn`. Nunca `pip install`.
- **Entry point**: `main.py` (Linux/Docker). En Windows usar `run.py` (fix ProactorEventLoop + psycopg3).
- **Adaptador activo**: definido por `BACKEND_ADAPTER` en `env.docker`. Default: `express` (dev local).
- **Campos de tickets**: usar nombres reales de Odoo (`asunto`, `descripcion`, `ticket_type_id`, etc.), no strings inventados.
- **Módulo Odoo `ITS_Helpdesk_Docst_no_editable/`**: NO TOCAR. Es el módulo de producción real.
- **Tests**: `uv run python scratch/test_sara.py --port 8001 --delay 5`

---

## Estado actual y pendientes

Ver `agent_v2_Doc/PLAN.md` para el estado completo.

### Completado
- Roles creador/resueltor/supervisor con tools aisladas por rol
- Checkpointer PostgreSQL (AsyncPostgresSaver)
- RAG con pgvector (langchain_postgres)
- Streaming SSE (`/agent/stream`)
- Rate limiting por usuario (sliding window)
- Thread isolation (user_id:thread_id)
- Seguridad Capa 1 (anti-prompt-injection en prompts) y Capa 4 (ContextVar user_id)
- OdooAdapter implementado (no probado contra Odoo real)
- Docker dev con hot reload

### Pendiente (prioridad)
- **RAG-1**: Poblar vector store con tickets históricos reales
- **UX-4**: Fix detección de duplicados — filtrar por categoría, no global
- **PROD-3**: `asyncio.Semaphore(20)` en LLM calls (protección bajo carga)
- **INF-2**: OpenRouter como cuarto proveedor LLM fallback
- **Security Capa 2/3/5**: sanitización de input, framing de datos externos, filtrado de output

---

## Troubleshooting rápido

**"permission denied" al correr docker:**
```bash
sudo usermod -aG docker $USER && newgrp docker
```

**Agente no arranca (crash loop):**
```bash
docker compose logs agent --tail=50
# Causas: backend no corre en 8000, env.docker incompleto, postgres no healthy
```

**Hot reload no funciona:**
El archivo debe cambiar dentro del directorio montado (`.:/app`). Si editás fuera del bind mount, uvicorn no lo detecta.

**Nueva dependencia en pyproject.toml:**
```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml restart agent
# No hace rebuild — uv sync corre al arrancar el contenedor
```
