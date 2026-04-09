"""
Tools for the IA Agent - Backend API integration via httpx and vector search
"""
import httpx
import os
from typing import Any, List
from langchain_core.tools import tool
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
import logging

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuración del vector store
VECTOR_STORE_PATH = "/home/bramos01/Documentos/ia-agents/ia-agent-tickets-v1/agent/vector_store"
BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:3001")

# Cache global para evitar recargas costosas
_embeddings_cache = None
_vector_store_cache = None

def get_embeddings():
    """Obtener instancia única de embeddings"""
    global _embeddings_cache
    if _embeddings_cache is None:
        logger.info("Inicializando HuggingFaceEmbeddings (un solo uso)...")
        _embeddings_cache = HuggingFaceEmbeddings(
            model_name="sentence-transformers/all-MiniLM-L6-v2"
        )
    return _embeddings_cache

def get_vector_store():
    """Obtener instancia del vector store desde init_vector_store"""
    try:
        from init_vector_store import get_vector_store_from_init
        return get_vector_store_from_init()
    except Exception as e:
        logger.error(f"Error al cargar el vector store: {e}")
        return None

def get_headers(user_id: int, user_rol: str) -> dict:
    """Generate headers for backend API calls"""
    return {
        "x-user-id": str(user_id),
        "x-user-rol": user_rol
    }


@tool
def create_ticket(
    tipo_requerimiento: str,
    categoria: str,
    descripcion: str,
    urgencia: str,
    impacto: str,
    prioridad: str,
    user_id: int
) -> dict:
    """
    Creates a new ticket in the system.
    Must collect all fields before calling this tool.
    """
    payload = {
        "tipo_requerimiento": tipo_requerimiento,
        "categoria": categoria,
        "descripcion": descripcion,
        "urgencia": urgencia,
        "impacto": impacto,
        "prioridad": prioridad
    }
    
    with httpx.Client() as client:
        response = client.post(
            f"{BACKEND_URL}/api/tickets",
            json=payload,
            headers=get_headers(user_id, "creador"),
            timeout=30.0
        )
        
        if response.status_code == 201:
            return {"success": True, "ticket": response.json()}
        else:
            error = response.json().get("error", "Error desconocido")
            return {"success": False, "error": f"Error al crear ticket: {error}"}

@tool
def get_created_tickets(user_id: int) -> list:
    """
    Gets all tickets created by the specified user.
    """
    with httpx.Client() as client:
        response = client.get(
            f"{BACKEND_URL}/api/tickets",
            params={"created_by": user_id},
            headers=get_headers(user_id, "creador"),
            timeout=30.0
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return []

@tool
def get_my_tickets(user_id: int) -> list:
    """
    Gets all tickets assigned to the specified resolver user.
    """
    with httpx.Client() as client:
        response = client.get(
            f"{BACKEND_URL}/api/tickets",
            params={"asignado_a": user_id},
            headers=get_headers(user_id, "resueltor"),
            timeout=30.0
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return []

@tool
def get_ticket_detail(ticket_id: int, user_id: int, user_rol: str) -> dict:
    """
    Gets the full details of a specific ticket.
    """
    with httpx.Client() as client:
        response = client.get(
            f"{BACKEND_URL}/api/tickets/{ticket_id}",
            headers=get_headers(user_id, user_rol),
            timeout=30.0
        )
        
        if response.status_code == 200:
            return response.json()
        elif response.status_code == 404:
            return {"error": f"Ticket #{ticket_id} no encontrado"}
        else:
            return {"error": f"Error al obtener ticket: {response.status_code}"}

@tool
def resolve_ticket(ticket_id: int, resolucion: str, user_id: int) -> dict:
    """
    Marks a ticket as resolved with the given resolution text.
    Also adds the resolved ticket to the vector store for learning.
    """
    payload = {"resolucion": resolucion}
    
    with httpx.Client() as client:
        response = client.put(
            f"{BACKEND_URL}/api/tickets/{ticket_id}/resolve",
            json=payload,
            headers=get_headers(user_id, "resueltor"),
            timeout=30.0
        )
        
        if response.status_code == 200:
            # También añadir al vector store para aprendizaje
            try:
                # Obtener detalles del ticket para añadir al vector store
                detail_response = client.get(
                    f"{BACKEND_URL}/api/tickets/{ticket_id}",
                    headers=get_headers(user_id, "resueltor"),
                    timeout=30.0
                )
                
                if detail_response.status_code == 200:
                    ticket_data = detail_response.json()
                    # Añadir al vector store
                    add_ticket_to_vector_store(
                        ticket_id=ticket_id,
                        tipo_requerimiento=ticket_data.get("tipo_requerimiento", ""),
                        categoria=ticket_data.get("categoria", ""),
                        descripcion=ticket_data.get("descripcion", ""),
                        resolucion=resolucion
                    )
                    logger.info(f"Ticket #{ticket_id} resuelto y añadido al vector store para aprendizaje")
                else:
                    logger.warning(f"No se pudo obtener detalle del ticket #{ticket_id} para vector store")
            except Exception as e:
                logger.error(f"Error al añadir ticket al vector store tras resolución: {e}")
            
            return {"success": True, "ticket": response.json()}
        else:
            error = response.json().get("error", "Error desconocido")
            return {"success": False, "error": f"Error al resolver ticket: {error}"}

@tool
def get_resolutores() -> list:
    """
    Gets all users with 'resolutor' role.
    """
    with httpx.Client() as client:
        response = client.get(
            f"{BACKEND_URL}/api/users",
            params={"rol": "resueltor"},
            timeout=30.0
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return []

@tool
def get_all_tickets() -> list:
    """
    Gets all tickets in the system. For supervisor use.
    Returns all tickets regardless of state or assignment.
    """
    with httpx.Client() as client:
        response = client.get(
            f"{BACKEND_URL}/api/tickets",
            timeout=30.0
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return []

@tool
def assign_ticket(ticket_id: int, asignado_a: int, user_id: int) -> dict:
    """
    Assigns a ticket to a resolutor. For supervisor use only.
    """
    payload = {"asignado_a": asignado_a}
    
    with httpx.Client() as client:
        response = client.put(
            f"{BACKEND_URL}/api/tickets/{ticket_id}/assign",
            json=payload,
            headers=get_headers(user_id, "supervisor"),
            timeout=30.0
        )
        
        if response.status_code == 200:
            return {"success": True, "ticket": response.json()}
        else:
            error = response.json().get("error", "Error desconocido")
            return {"success": False, "error": f"Error al asignar ticket: {error}"}

@tool
def reopen_ticket(ticket_id: int, motivo: str, user_id: int) -> dict:
    """
    Reopens a resolved ticket. For supervisor use only.
    """
    payload = {"motivo": motivo}
    
    with httpx.Client() as client:
        response = client.put(
            f"{BACKEND_URL}/api/tickets/{ticket_id}/reopen",
            json=payload,
            headers=get_headers(user_id, "supervisor"),
            timeout=30.0
        )
        
        if response.status_code == 200:
            return {"success": True, "ticket": response.json()}
        else:
            error = response.json().get("error", "Error desconocido")
            return {"success": False, "error": f"Error al reabrir ticket: {error}"}

@tool
def delete_ticket(ticket_id: int, user_id: int) -> dict:
    """
    Deletes a ticket permanently. For supervisor use only.
    WARNING: This action cannot be undone!
    """
    with httpx.Client() as client:
        response = client.delete(
            f"{BACKEND_URL}/api/tickets/{ticket_id}",
            headers=get_headers(user_id, "supervisor"),
            timeout=30.0
        )
        
        if response.status_code == 200:
            return {"success": True, "message": f"Ticket #{ticket_id} eliminado"}
        else:
            error = response.json().get("error", "Error desconocido")
            return {"success": False, "error": f"Error al eliminar ticket: {error}"}

@tool
def get_resolved_tickets() -> list:
    """
    Gets all resolved tickets. For learning/suggestions.
    Returns tickets that have been successfully resolved.
    """
    with httpx.Client() as client:
        response = client.get(
            f"{BACKEND_URL}/api/tickets",
            params={"estado": "resuelto"},
            timeout=30.0
        )
        
        if response.status_code == 200:
            return response.json()
        else:
            return []

@tool
def buscar_soluciones_similares(categoria: str, busqueda: str) -> list:
    """
    Searches for similar resolved tickets using semantic search (vector embeddings).
    Returns suggestions of how similar problems were solved before.
    Use this when a resolver needs help with a new ticket.
    """
    try:
        vector_store = get_vector_store()
        if vector_store is None:
            logger.warning("Vector store no disponible, devolviendo lista vacía")
            return []
        
        # Construir query que combine categoría y búsqueda para mejor contexto
        query = f"Categoría: {categoria}. Problema: {busqueda}"
        
        # Realizar búsqueda semántica
        docs = vector_store.similarity_search(
            query=query,
            k=5  # Obtener los 5 más similares
        )
        
        # Filtrar por categoría si se específicamente
        if categoria and categoria.lower() != "todas":
            filtered_docs = [
                doc for doc in docs 
                if doc.metadata.get("categoria", "").lower() == categoria.lower()
            ]
            # Si no hay resultados filtrados, usar todos los resultados
            docs = filtered_docs if filtered_docs else docs
        
        # Formatear resultados
        resultados = []
        for doc in docs:
            resultados.append({
                "ticket_id": doc.metadata.get("ticket_id"),
                "categoria": doc.metadata.get("categoria"),
                "tipo": doc.metadata.get("tipo_requerimiento"),
                "descripcion": doc.metadata.get("descripcion"),
                "resolucion": doc.metadata.get("resolucion")
            })
        
        logger.info(f"Búsqueda semántica realizada: '{query}' -> {len(resultados)} resultados")
        return resultados
        
    except Exception as e:
        logger.error(f"Error en búsqueda semántica: {e}")
        return []

def add_ticket_to_vector_store(ticket_id: int, tipo_requerimiento: str, categoria: str, descripcion: str, resolucion: str) -> bool:
    """
    Añade un ticket resuelto al vector store para aprendizaje en tiempo real.
    """
    try:
        # Obtener instancia compartida
        vector_store = get_vector_store()
        if vector_store is None:
            logger.warning("Vector store no disponible para aprendizaje")
            return False
        
        # Crear documento para el vector store
        content = f"Problema: {descripcion}\nSolución: {resolucion}"
        metadata = {
            "ticket_id": ticket_id,
            "tipo_requerimiento": tipo_requerimiento,
            "categoria": categoria,
            "descripcion": descripcion,
            "resolucion": resolucion
        }
        
        doc = Document(page_content=content, metadata=metadata)
        
        # Añadir al vector store
        vector_store.add_documents([doc])
        
        logger.info(f"Ticket #{ticket_id} añadido al vector store para aprendizaje")
        return True
        
    except Exception as e:
        logger.error(f"Error al añadir ticket al vector store: {e}")
        return False


def create_tools():
    """Returns list of all available tools"""
    return [
        create_ticket,
        get_created_tickets,
        get_my_tickets,
        get_ticket_detail,
        resolve_ticket,
        get_resolutores,
        get_all_tickets,
        assign_ticket,
        reopen_ticket,
        delete_ticket,
        get_resolved_tickets,
        buscar_soluciones_similares
    ]
