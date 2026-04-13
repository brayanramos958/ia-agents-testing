# Rediseño: Agente de Tickets como Microservicio Empresarial (A2A-ready)

## Contexto y problema

El agente actual funciona como demostración pero tiene **acoplamiento estructural** que impide usarlo en producción empresarial:
- Paths absolutos hardcodeados al filesystem del desarrollador
- Lee SQLite del backend directamente (viola la propiedad de datos)
- Sin autenticación real
- Memoria volátil (RAM)
- No tiene contrato A2A para ser llamado por otro agente

**Objetivo rediseño**: Un microservicio Python que:
1. Puede enchufarse a **cualquier sistema de tickets** (API configurable)
2. Puede ser **llamado por otro agente** (patrón A2A)
3. Es apto para **producción empresarial** (auth, persistencia, config)

---

## User Review Required

> [!IMPORTANT]
> Este plan propone **reescribir el agente desde cero** en un nuevo directorio `agent-v2/`, dejando `agent/` intacto mientras se desarrolla. Al final se replaza.

> [!WARNING]
> El patrón A2A (Agent-to-Agent) requiere agregar un endpoint especial `/agent/invoke` diferente al `/agent/chat` actual. Los dos pueden coexistir.

> [!IMPORTANT]
> La autenticación inicial será **API Key fija** (header `X-Agent-Key`), preparada para OAuth2 después. Valida al menos que el caller está autorizado — funciona tanto para frontend como para agente orquestador.

---

## Arquitectura propuesta: Hexagonal + A2A

```
┌─────────────────────────────────────────────────────────────────┐
│                  AGENT MICROSERVICE (FastAPI)                   │
│                                                                 │
│  ┌─────────┐   ┌──────────────────────────────────────────┐   │
│  │ /chat   │   │          Agent Core (LangGraph)           │   │
│  │ /invoke │──▶│  ReAct Graph + InMemory/SqliteSaver       │   │
│  │ /health │   │                                           │   │
│  └─────────┘   │  ┌────────────────────────────────────┐  │   │
│                │  │     Tools (usan el Port)            │  │   │
│  Middleware:   │  │  create_ticket, resolve_ticket...   │  │   │
│  - API Key     │  └────────────┬───────────────────────┘  │   │
│  - CORS        │               │                           │   │
│  - Logging     │  ┌────────────▼───────────────────────┐  │   │
│                │  │   ITicketPort (Puerto abstracto)    │  │   │
│                │  └──┬──────────────┬──────────────┬──-┘  │   │
│                │     │              │               │       │   │
│                └─────┼──────────────┼───────────────┼───── ┘   │
│                      │              │               │           │
│               ┌──────▼───┐  ┌──────▼───┐  ┌───────▼───┐      │
│               │ Express  │  │  Jira    │  │ Zendesk   │      │
│               │ Adapter  │  │ Adapter  │  │ Adapter   │      │
│               └──────────┘  └──────────┘  └───────────┘      │
└─────────────────────────────────────────────────────────────────┘

Flujo A2A:
Orquestador Agent ──POST /agent/invoke──▶ Ticket Agent
                  ◀── { result, status } ──
```

---

## Nueva estructura de archivos

```
agent-v2/
├── core/
│   ├── __init__.py
│   ├── graph.py           ← LangGraph ReAct — NO conoce el backend concreto
│   ├── prompts.py         ← System prompts por rol (sin user_id hardcodeado)
│   └── tools.py           ← Tools que llaman al puerto abstracto
│
├── ports/
│   ├── __init__.py
│   └── ticket_port.py     ← ITicketPort: interfaz abstracta de operaciones
│
├── adapters/
│   ├── __init__.py
│   ├── express_adapter.py ← Implementación para este backend Express
│   ├── jira_adapter.py    ← [futuro] Adapter para Jira
│   └── http_adapter.py    ← Adapter genérico configurable por env vars
│
├── rag/
│   ├── __init__.py
│   ├── vector_store.py    ← ChromaDB — paths desde env vars
│   └── embeddings.py      ← HuggingFace embeddings cacheados
│
├── api/
│   ├── __init__.py
│   ├── routes_chat.py     ← POST /agent/chat (uso humano, con thread_id)
│   ├── routes_invoke.py   ← POST /agent/invoke (A2A, sin estado de sesión)
│   └── middleware.py      ← API Key auth + CORS + logging
│
├── config/
│   └── settings.py        ← Pydantic Settings — TODA la config desde env
│
├── main.py                ← FastAPI app bootstrap
├── requirements.txt
├── .env.example
└── Dockerfile
```

---

## Propuestas de cambio por componente

---

### Config — Pydantic Settings (elimina TODO hardcoding)

#### [NEW] [settings.py](file:///home/bramos01/Documentos/ia-agents/ia-agent-tickets-v1/agent-v2/config/settings.py)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # LLM
    groq_api_key: str
    llm_model: str = "llama-3.1-8b-instant"
    openrouter_api_key: str = ""
    openrouter_model: str = "google/gemma-4-26b-a4b-it:free"

    # Backend adapter
    backend_url: str = "http://localhost:3001"
    backend_adapter: str = "express"  # express | jira | http_generic

    # RAG
    vector_store_path: str = "./vector_store"
    rag_enabled: bool = True

    # Auth
    agent_api_key: str  # Header X-Agent-Key

    # Persistence
    checkpoint_backend: str = "memory"  # memory | sqlite | postgres
    checkpoint_db_url: str = "checkpoints.db"

    # Server
    port: int = 8000
    cors_origins: list[str] = ["*"]

    class Config:
        env_file = ".env"
```

**Impacto**: Elimina TODOS los paths hardcodeados. Un solo lugar de verdad para config.

---

### Puerto abstracto — ITicketPort

#### [NEW] [ticket_port.py](file:///home/bramos01/Documentos/ia-agents/ia-agent-tickets-v1/agent-v2/ports/ticket_port.py)

Define el contrato que el agente entiende. Los adaptadores implementan este contrato.

```python
from abc import ABC, abstractmethod

class ITicketPort(ABC):
    @abstractmethod
    def create_ticket(self, payload: dict, user_id: int) -> dict: ...

    @abstractmethod
    def get_tickets_by_creator(self, user_id: int) -> list: ...

    @abstractmethod
    def get_tickets_by_assignee(self, user_id: int) -> list: ...

    @abstractmethod
    def get_ticket_detail(self, ticket_id: int, user_id: int, rol: str) -> dict: ...

    @abstractmethod
    def resolve_ticket(self, ticket_id: int, resolution: str, user_id: int) -> dict: ...

    @abstractmethod
    def get_all_tickets(self) -> list: ...

    @abstractmethod
    def assign_ticket(self, ticket_id: int, assignee_id: int, user_id: int) -> dict: ...

    @abstractmethod
    def reopen_ticket(self, ticket_id: int, reason: str, user_id: int) -> dict: ...

    @abstractmethod
    def get_resolvers(self) -> list: ...
```

**Impacto**: El agente habla con `ITicketPort`. No con Express, no con Jira. El adaptador hace la traducción.

---

### Adaptadores concretos

#### [NEW] [express_adapter.py](file:///home/bramos01/Documentos/ia-agents/ia-agent-tickets-v1/agent-v2/adapters/express_adapter.py)

Implementa `ITicketPort` llamando al backend Express actual. Misma lógica de `tools.py` pero bien encapsulada.

#### [NEW] [http_adapter.py](file:///home/bramos01/Documentos/ia-agents/ia-agent-tickets-v1/agent-v2/adapters/http_adapter.py)

Adapter genérico configurable: los endpoints, headers y campos se configuran por env vars. Permite conectar a cualquier API REST sin código nuevo.

---

### Tools — ya no llaman al backend, llaman al Port

#### [MODIFY] tools.py

```python
# ANTES (acoplado):
def create_ticket(...):
    response = httpx.post(f"{BACKEND_URL}/api/tickets", ...)

# DESPUÉS (desacoplado):
_port: ITicketPort = None  # inyectado al iniciar

def create_ticket(...):
    return _port.create_ticket(payload, user_id)
```

Las tools NO cambian en semántica — solo delegan al port. Esto permite testearlas con un mock.

---

### API — Endpoint A2A dedicado

#### [NEW] [routes_invoke.py](file:///home/bramos01/Documentos/ia-agents/ia-agent-tickets-v1/agent-v2/api/routes_invoke.py)

```
POST /agent/invoke
```

Diseñado para ser llamado por un agente orquestador. Diferencias con `/agent/chat`:

| Aspecto | `/agent/chat` | `/agent/invoke` |
|---------|--------------|-----------------|
| Caller | Usuario humano (frontend) | Agente orquestador |
| Memoria | thread_id por usuario | Stateless por defecto |
| Input | Mensaje en lenguaje natural | Intent + parámetros estructurados |
| Output | String de respuesta | `{ result, status, data }` estructurado |
| Auth | API Key | API Key |

```python
# Esquema de invoke para A2A:
class InvokeRequest(BaseModel):
    intent: str           # "create_ticket" | "get_my_tickets" | "resolve_ticket"
    parameters: dict      # parámetros específicos del intent
    user_id: int
    user_rol: str
    context: str = ""     # contexto adicional que el orquestador quiere darle

class InvokeResponse(BaseModel):
    status: str           # "success" | "error" | "needs_more_info"
    result: dict          # datos estructurados del resultado
    message: str          # explicación en lenguaje natural (para el orquestador)
```

---

### Auth — API Key middleware

#### [NEW] [middleware.py](file:///home/bramos01/Documentos/ia-agents/ia-agent-tickets-v1/agent-v2/api/middleware.py)

```python
async def api_key_middleware(request: Request, call_next):
    key = request.headers.get("X-Agent-Key")
    if not key or key != settings.agent_api_key:
        return JSONResponse(status_code=401, content={"error": "Unauthorized"})
    return await call_next(request)
```

Simple, seguro, funciona para frontend Y para agente orquestador.

---

### RAG — paths desde env vars

#### [MODIFY] vector_store.py

```python
# ANTES:
VECTOR_STORE_PATH = "/home/bramos01/Documentos/.../vector_store"

# DESPUÉS:
VECTOR_STORE_PATH = settings.vector_store_path  # desde .env
```

La inicialización ya no lee SQLite directamente — llama al endpoint REST del backend para obtener tickets resueltos.

---

### Dockerfile

#### [NEW] Dockerfile

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "main.py"]
```

Con esto el agente corre en cualquier máquina/servidor sin depender del filesystem del dev.

---

## Plan de ejecución en fases

### Fase 1 — Base (2-3h) → agente funcional con arquitectura correcta
- `[ ]` Crear `agent-v2/` con la nueva estructura
- `[ ]` Implementar `config/settings.py` (Pydantic Settings)
- `[ ]` Implementar `ports/ticket_port.py` (interfaz abstracta)
- `[ ]` Implementar `adapters/express_adapter.py` (mismo backend actual)
- `[ ]` Reescribir `core/tools.py` (delegan al port)
- `[ ]` Reescribir `core/graph.py` (inyección del port, SqliteSaver)
- `[ ]` Reescribir `main.py` + middleware auth
- `[ ]` Probar `/agent/chat` equivalente al actual

### Fase 2 — A2A (1-2h) → agente llamable por otro agente
- `[ ]` Implementar `api/routes_invoke.py` con contrato A2A
- `[ ]` Probar `/agent/invoke` con curl simulando un orquestador
- `[ ]` Documentar el contrato A2A en `README.md`

### Fase 3 — RAG sin SQLite directo (1h)
- `[ ]` Reescribir `rag/vector_store.py` — paths desde env vars
- `[ ]` Eliminar lectura directa de SQLite → consumir API REST
- `[ ]` Verificar que el aprendizaje tras resolver ticket sigue funcionando

### Fase 4 — Docker (30min)
- `[ ]` `Dockerfile`
- `[ ]` `.env.example` completo
- `[ ]` Probar `docker build && docker run`

---

## Verificación

### Automática
- Tests de los adaptadores con mocks del puerto
- Test del endpoint `/agent/invoke` con `httpx.AsyncClient`

### Manual
- El agente corre en otra máquina solo cambiando `.env`
- Otro agente puede llamar a `/agent/invoke` y recibir datos estructurados
- El agente del frontend sigue funcionando con `/agent/chat`

---

## Open Questions

> [!IMPORTANT]
> **¿El orquestador que llamará a este agente ya existe o también lo construyes?**
> Si ya existe o es un agente conocido (LangGraph, CrewAI, AutoGen), el diseño del endpoint `/agent/invoke` puede adaptarse a su protocolo nativo.

> [!IMPORTANT]
> **¿El sistema de tickets destino tiene API REST documentada?**
> Si sí, el `http_adapter.py` genérico puede configurarse solo. Si no tiene API, necesitaremos otro tipo de adaptador.

> [!WARNING]
> **¿Usas contenedores (Docker/K8s) en la empresa destino?**
> Si sí, el `Dockerfile` es la pieza más crítica a entregar bien desde el inicio.
