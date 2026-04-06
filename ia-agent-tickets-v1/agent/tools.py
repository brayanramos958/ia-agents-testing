"""
Tools for the IA Agent - Backend API integration via httpx
"""
import httpx
import os
from typing import Any
from langchain_core.tools import tool

BACKEND_URL = os.getenv("BACKEND_URL", "http://localhost:3001")

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
        reopen_ticket
    ]
