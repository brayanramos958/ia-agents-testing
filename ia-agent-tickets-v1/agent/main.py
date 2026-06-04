"""
FastAPI application for the IA Agent
"""
from dotenv import load_dotenv
# Load environment variables FIRST
load_dotenv()

import os
import uuid
import traceback
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from graph import create_agent, get_response
from langchain_core.messages import HumanMessage

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
def chat(request: ChatRequest):
    """
    Main chat endpoint for the IA Agent.
    Uses the provided thread_id or generates a new one for first-time users.
    """
    print(f"--- NUEVA PETICIÓN: {request.message} ---")
    # Use provided thread_id or generate a consistent one based on user_id
    thread_id = request.thread_id if request.thread_id else f"user-{request.user_id}"
    
    try:
        # Get the agent
        graph = get_agent()
        
        # Create message
        messages = [HumanMessage(content=request.message)]
        
        # Get response from agent
        reply = get_response(graph, messages, thread_id, request.user_id, request.user_rol)
        
        return ChatResponse(reply=reply, thread_id=thread_id)
    
    except HTTPException:
        # Re-raise HTTP exceptions as-is
        raise
    except Exception as e:
        # Log the full error for debugging
        print(f"Error processing chat: {e}")
        print(traceback.format_exc())
        
        # Return user-friendly error
        error_msg = str(e)
        
        if "api_key" in error_msg.lower() or "auth" in error_msg.lower() or "groq" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="Error de configuración: API key de Groq no válida o expirada"
            )
        
        if "connection" in error_msg.lower() or "refused" in error_msg.lower():
            raise HTTPException(
                status_code=500,
                detail="No se puede conectar al servidor backend. Asegúrate de que esté corriendo."
            )
        
        # Generic error
        raise HTTPException(
            status_code=500,
            detail=f"Error al procesar tu mensaje: {error_msg}"
        )

if __name__ == "__main__":
    import uvicorn
    
    port = int(os.getenv("PORT", "8000"))
    uvicorn.run(app, host="0.0.0.0", port=port)
