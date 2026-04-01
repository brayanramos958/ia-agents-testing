"""
FastAPI application for the IA Agent
"""
import os
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from graph import create_agent, get_response
from langchain_core.messages import HumanMessage

# Load environment variables
load_dotenv()

# Initialize FastAPI app
app = FastAPI(title="IA Agent - Mesa de Ayuda")

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize agent (lazy loading)
agent_graph = None

def get_agent():
    """Lazy load the agent graph"""
    global agent_graph
    if agent_graph is None:
        agent_graph = create_agent()
    return agent_graph

# Request/Response models
class ChatRequest(BaseModel):
    user_id: int
    user_rol: str
    message: str
    thread_id: str | None = None

class ChatResponse(BaseModel):
    reply: str
    thread_id: str

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "ia-agent"}

@app.post("/agent/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """
    Main chat endpoint for the IA Agent.
    Takes a message from the user and returns the agent's response.
    """
    # Generate thread_id if not provided
    thread_id = request.thread_id or f"user-{request.user_id}"
    
    try:
        # Get the agent
        graph = get_agent()
        
        # Create message
        messages = [HumanMessage(content=request.message)]
        
        # Get response from agent
        reply = get_response(graph, messages, thread_id, request.user_id, request.user_rol)
        
        return ChatResponse(reply=reply, thread_id=thread_id)
    
    except Exception as e:
        # Log error and return friendly message
        error_msg = str(e)
        
        if "API key" in error_msg.lower() or "auth" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Error de configuración: API key de Groq no válida"
            )
        
        raise HTTPException(
            status_code=500,
            detail=f"Error al procesar tu mensaje: {error_msg}"
        )

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)


# =============================================================================
# Testing Commands
# =============================================================================

## Start the services

# Terminal 1: Backend
# cd backend && npm run dev

# Terminal 2: Agent
# cd agent && pip install -r requirements.txt
# Set OPENAI_API_KEY in .env
# python main.py

# Terminal 3: Frontend
# cd frontend && npm run dev

## Test CREADOR Flow

# Create a ticket
# curl -X POST http://localhost:8000/agent/chat \
#   -H "Content-Type: application/json" \
#   -d '{
#     "user_id": 1,
#     "user_rol": "creador",
#     "message": "Quiero abrir un ticket, tengo un problema con mi computadora"
#   }'

# List created tickets
# curl -X POST http://localhost:8000/agent/chat \
#   -H "Content-Type: application/json" \
#   -d '{
#     "user_id": 1,
#     "user_rol": "creador",
#     "message": "Quiero ver mis tickets"
#   }'

## Test RESOLUTOR Flow

# View assigned tickets
# curl -X POST http://localhost:8000/agent/chat \
#   -H "Content-Type: application/json" \
#   -d '{
#     "user_id": 2,
#     "user_rol": "resolutor",
#     "message": "Hola, quiero ver mis tickets asignados"
#   }'

# Resolve a ticket
# curl -X POST http://localhost:8000/agent/chat \
#   -H "Content-Type: application/json" \
#   -d '{
#     "user_id": 2,
#     "user_rol": "resolutor",
#     "message": "Resolver ticket 1, lo arreglé reemplazando el cable de red"
#   }'
