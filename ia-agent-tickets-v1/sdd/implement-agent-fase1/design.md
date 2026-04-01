# Técnico Design Document: implement-agent-fase1

## 1. Technical Approach Summary

Implementar un microservicio de agente IA basado en LangGraph que actúe como intermediario conversacional entre usuarios y el sistema de tickets. El agente utilizará el patrón ReAct (Reasoning and Acting) para decidir qué herramientas invocar basándose en el rol del usuario y el contexto de la conversación. El microservicio expondrá un único endpoint POST /agent/chat que recibirá mensajes de usuario y devolverá respuestas del agente, manteniendo el contexto de conversación mediante checkpointer de LangGraph.

## 2. Architecture Decisions

| Decision | Description | Justification | Alternatives Considered |
|----------|-------------|---------------|-------------------------|
| **Framework** | FastAPI para el servidor HTTP | Ligero, async nativo, excelente para microservicios | Express.js (menos adecuado para Python/LangChain), Django (sobredimensionado) |
| **Agent Framework** | LangGraph con patrón ReAct | Maneja naturalmente el ciclo LLM→Tool→LLM, menos código que routers custom | Router custom, LangChain Agents (menos flexible) |
| **LLM** | Groq llama-3.1-8b-instant via langchain-groq | Rápido, gratuito para desarrollo, buena calidad para instrucciones | GPT-3.5-turbo (costo), modelos locales (menor performance) |
| **HTTP Client** | httpx (async) | Compatibilidad total con async/await de FastAPI, mejor performance | requests (síncrono, bloquearía el event loop) |
| **Memory/Checkpointing** | langgraph.checkpoint.memory.InMemorySaver | Simple para desarrollo, persiste historial por thread_id | SqliteSaver/PostgresSaver (sobrecarga para fase 1) |
| **Tool Implementation** | @tool decorated functions que llaman al backend via httpx | Encapsula lógica de API, manejo de errores en español, respuestas estructuradas | Clases de servicio separadas (más complejo para este uso) |
| **System Prompts** | Prompts dinámicos por rol almacenados en prompts.py | Permite comportamiento diferente según rol sin duplicar código | Prompts hardcodeados en cada tool (diffícil de mantener) |
| **Backend Communication** | Headers x-user-id y x-user-rol para simular autenticación | Reutiliza middleware existente de backend, no requiere cambios de auth | Tokens JWT, sesiones (complejidad innecesaria) |
| **Endpoint Design** | POST /agent/chat con user_id, user_rol, message, thread_id opcional | Simple, RESTful, permite continuation de conversaciones | WebSockets (sobrecarga para fase 1), múltiples endpoints (menos cohesivo) |

## 3. Data Flow (ASCII Diagram)

```
┌─────────────┐    HTTP POST    ┌──────────────┐    HTTP Request    ┌──────────────┐
│   Frontend  │ ──────────────▶ │   Agent    │ ─────────────────▶ │  Backend API │
│ (React/Vite)│                 │ (Python)   │                      │ (Node.js)    │
└─────────────┘                 └──────────────┘                    └──────────────┘
        ▲                             │                             │
        │                             │ HTTP Response               │ HTTP Response
        │                             ▼                             ▼
        │                       ┌──────────────┐              ┌──────────────┐
        │                       │  Agent     │              │  Agent     │
        │                       │ (Processing)│              │ (Response) │
        │                       └──────────────┘              └──────────────┘
        │                             │                             │
        │                             │                             │
        └──────────────◄──────────────┴─────────────────────────────┘
                   HTTP Response (JSON)

Where:
1. Frontend envía POST /agent/chat con user_id, user_rol, message
2. Agent recibe request, invoca grafo LangGraph con system prompt según rol
3. LLM decide si necesita invocar una tool basado en prompt y conversación
4. Si necesita tool, ejecuta tool que llama al backend API via httpx
5. Tool procesa respuesta del backend y devuelve resultado estructurado
6. LLM genera respuesta final en español basada en tool output y conversation
7. Agent devuelve respuesta JSON con reply y thread_id al frontend
8. Frontend muestra respuesta al usuario
```

## 4. File Changes

| File | Type | Description |
|------|------|-------------|
| agent/main.py | Nuevo | FastAPI app con endpoint POST /agent/chat |
| agent/graph.py | Nuevo | LangGraph StateGraph con nodo LLM y tool node, InMemorySaver checkpointer |
| agent/tools.py | Nuevo | Funciones @tool decoradas que llaman al backend API via httpx |
| agent/prompts.py | Nuevo | System prompts por rol (creador, resolutor) con valores válidos para enums |
| agent/requirements.txt | Nuevo | Dependencias Python: fastapi, langchain-groq, langgraph, httpx, etc. |
| agent/.env.example | Nuevo | Template de variables de entorno |
| backend/src/routes/tickets.js | Modificado | Agregar filtro created_by en GET /api/tickets |
| backend/src/db/initDb.js | Ninguno | Schema ya incluye created_by |

## 5. Interfaces

### Python Function Signatures for Tools

```python
from langchain_core.tools import tool
from typing import Dict, List, Any
import httpx

@tool
def create_ticket(tipo_requerimiento: str, categoria: str, descripcion: str, 
                 urgencia: str, impacto: str, prioridad: str, user_id: int) -> Dict[str, Any]:
    """
    Crea un nuevo ticket en el sistema.
    
    Args:
        tipo_requerimiento: Tipo de requerimiento (Incidente/Solicitud/Problema)
        categoria: Categoría (Hardware/Software/Red/Seguridad/Otro)
        descripcion: Descripción libre del problema
        urgencia: Nivel de urgencia (baja/media/alta/critica)
        impacto: Nivel de impacto (bajo/medio/alto)
        prioridad: Nivel de prioridad (baja/media/alta/urgente)
        user_id: ID del usuario que crea el ticket
        
    Returns:
        Dict con datos del ticket creado o mensaje de error
    """
    # Implementación: POST http://localhost:3001/api/tickets con headers x-user-id, x-user-rol

@tool
def get_created_tickets(user_id: int) -> List[Dict[str, Any]]:
    """
    Obtiene los tickets creados por el usuario actual.
    
    Args:
        user_id: ID del usuario
        
    Returns:
        Lista de tickets creados por el usuario
    """
    # Implementación: GET http://localhost:3001/api/tickets?created_by={user_id}

@tool
def get_my_tickets(user_id: int) -> List[Dict[str, Any]]:
    """
    Obtiene los tickets asignados al resolutor actual.
    
    Args:
        user_id: ID del usuario resolutor
        
    Returns:
        Lista de tickets asignados al usuario
    """
    # Implementación: GET http://localhost:3001/api/tickets?asignado_a={user_id}

@tool
def get_ticket_detail(ticket_id: int, user_id: int) -> Dict[str, Any]:
    """
    Obtiene el detalle completo de un ticket específico.
    
    Args:
        ticket_id: ID del ticket
        user_id: ID del usuario (para headers de autenticación simulada)
        
    Returns:
        Dict con detalle del ticket
    """
    # Implementación: GET http://localhost:3001/api/tickets/{ticket_id}

@tool
def resolve_ticket(ticket_id: int, resolucion: str, user_id: int) -> Dict[str, Any]:
    """
    Marca un ticket como resuelto con el texto de resolución.
    
    Args:
        ticket_id: ID del ticket a resolver
        resolucion: Texto describing the solution
        user_id: ID del usuario resolutor
        
    Returns:
        Dict con ticket actualizado o mensaje de error
    """
    # Implementación: PUT http://localhost:3001/api/tickets/{ticket_id}/resolve

@tool
def get_resolutores() -> List[Dict[str, Any]]:
    """
    Obtiene la lista de usuarios con rol resolutor.
    
    Returns:
        Lista de usuarios resolutores disponibles
    """
    # Implementación: GET http://localhost:3001/api/users?rol=resueltor
```

### Graph Structure (LangGraph)

```python
from typing import TypedDict, List
from langchain_core.messages import BaseMessage
from langgraph.graph import StateGraph, START, END
from langgraph.prebuilt import ToolNode

class AgentState(TypedDict):
    messages: List[BaseMessage]  # Historial de conversación

def create_agent_graph(system_prompt: str, tools: List):
    """
    Crea un grafo ReAct de LangGraph con el system prompt especificado.
    
    Args:
        system_prompt: Prompt del sistema según el rol del usuario
        tools: Lista de herramientas disponibles para el agente
        
    Returns:
        Grafo LangGraph compilado con checkpointer
    """
    # Definir el state
    builder = StateGraph(AgentState)
    
    # Nodo LLM que invoca el modelo con el system prompt
    def llm_node(state: AgentState):
        # Invocar LLM con system prompt y mensajes
        # Devolver actualización de state con respuesta del LLM
        pass
    
    # Nodo de herramientas
    tool_node = ToolNode(tools)
    
    # Construir el grafo
    builder.add_node("llm", llm_node)
    builder.add_node("tools", tool_node)
    builder.add_edge(START, "llm")
    builder.add_conditional_edges(
        "llm",
        should_continue,  # Función que decide si continuar con herramientas o terminar
        {"tools": "tools", "__end__": END}
    )
    builder.add_edge("tools", "llm")
    
    # Configurar checkpointer para memoria
    checkpointer = InMemorySaver()
    graph = builder.compile(checkpointer=checkpointer)
    
    return graph
```

### FastAPI Endpoint

```python
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Optional

class ChatRequest(BaseModel):
    user_id: int
    user_rol: str  # "creador" o "resolutor"
    message: str
    thread_id: Optional[str] = None

class ChatResponse(BaseModel):
    reply: str
    thread_id: str

app = FastAPI(title="IA Agent Microservice", version="1.0.0")

@app.post("/agent/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Endpoint principal del agente IA.
    
    Args:
        request: Contiene user_id, user_rol, message y thread_id opcional
        
    Returns:
        Respuesta del agente con reply y thread_id
    """
    # Determinar system prompt según rol
    # Obtener o generar thread_id
    # Invocar grafo LangGraph con la configuración apropiada
    # Devolver respuesta formateada
    pass
```

## 6. Testing Strategy

### Manual Testing via curl/httpie

#### Probar flujo creador:
```bash
# Crear ticket
http POST http://localhost:8000/agent/chat \
    user_id=1 \
    user_rol="creador" \
    message="Quiero abrir un ticket para un problema de impresora que no imprime"

# Ver mis tickets
http POST http://localhost:8000/agent/chat \
    user_id=1 \
    user_rol="creador" \
    message="Muestra mis tickets creados"
```

#### Probar flujo resolutor:
```bash
# Ver tickets asignados
http POST http://localhost:8000/agent/chat \
    user_id=2 \
    user_rol="resolutor" \
    message="¿Qué tickets tengo asignados?"

# Obtener detalle de ticket
http POST http://localhost:8000/agent/chat \
    user_id=2 \
    user_rol="resolutor" \
    message="Dame el detalle del ticket #5"

# Resolver ticket
http POST http://localhost:8000/agent/chat \
    user_id=2 \
    user_rol="resolutor" \
    message="Quiero resolver el ticket #3 con la solución: Reemplacé el tóner de la impresora"
```

#### Verificar headers de autenticación simulada:
- Todas las llamadas al backend deben incluir:
  - x-user-id: {user_id}
  - x-user-rol: {user_rol}

#### Verificar persistencia de conversación:
- Enviar múltiples mensajes con mismo thread_id
- Verificar que el agente recuerda el contexto de la conversación

### Backend Modification Testing
```bash
# Verificar que el filtro created_by funciona
http GET "http://localhost:3001/api/tickets?created_by=1"
# Debería retornar solo tickets creados por usuario ID 1
```

## 7. Migration

No se requiere migración - es un nuevo servicio que se agrega al sistema existente.
El agente se comunica con el backend existente mediante sus APIs actuales.
El único cambio requerido en el backend es agregar el filtro `created_by` al endpoint GET /api/tickets,
lo cual es una adición no disruptiva que no afecta datos existentes.

## 8. Open Questions

1. **Manejo de errores de LLM**: ¿Cómo debería comportarse el agente si el servicio de Groq no está disponible o retorna errores?
   - Considerar retry con backoff exponencial
   - Fallback a respuestas predefinidas en español
   - Retornar mensaje de error amigable al usuario

2. **Timeouts en llamadas al backend**: ¿Qué timeout debería usar httpx para las llamadas al backend Express?
   - Valor inicial: 10 segundos
   - Hacer configurable via variables de entorno

3. **Límites de tasa**: ¿Debería implementar rate limiting en el endpoint del agente?
   - Posponer a fase 3 según plan
   - Por ahora confiar en que el uso será bajo en desarrollo

4. **Validación de entradas en tools**: ¿Qué nivel de validación debería realizar cada tool antes de llamar al backend?
   - Validación básica de tipos y rangos
   - Dejar validación de negocio al backend (que ya la tiene)

5. **Formato de respuestas de tools**: ¿Deberían las tools retornar siempre un formato estructurado consistente?
   - Sí: {success: bool, data: any, message: str, error: str|None}
   - Facilita el manejo por parte del LLM

6. **Idioma de las herramientas**: ¿Las herramientas deberían devolver mensajes en español o inglés?
   - Español, ya que el agente se comunica con usuarios hispanohablantes
   - Los mensajes de error deben ser amigables y en español

7. **Manejo de conversación vacía**: ¿Cómo debería comportarse el agente cuando recibe un mensaje vacío o solo espacios?
   - Responder solicitando que el usuario escriba su consulta
   - No invocar herramientas en este caso

8. **Límite de historial de conversación**: ¿Debería limitarse la cantidad de mensajes guardados en la memoria?
   - Por ahora no, usar InMemorySaver tal cual
   - Revisar en fase 3 si se necesita SqliteSaver con límites