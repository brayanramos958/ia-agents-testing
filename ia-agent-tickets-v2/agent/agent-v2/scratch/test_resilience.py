
import sys
import os
from unittest.mock import MagicMock
from tenacity import RetryError

# Añadir el path para importar los módulos del agente
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from tools.ticket_tools import create_ticket, set_ticket_port

def test_resilience_success_after_retries():
    print("\n--- TEST 1: Éxito tras 2 fallos (Resiliencia en acción) ---")
    mock_port = MagicMock()
    
    # Simulamos: 1er intento falla, 2do intento falla, 3er intento funciona
    mock_port.create_ticket.side_effect = [
        Exception("Error de red temporal 1"),
        Exception("Error de red temporal 2"),
        {"success": True, "id": 999}
    ]
    
    set_ticket_port(mock_port)
    
    try:
        # Intentamos crear un ticket
        result = create_ticket.invoke({
            "asunto": "Test", 
            "descripcion": "Test", 
            "ticket_type_id": "1", 
            "category_id": "1", 
            "urgency_id": "1", 
            "impact_id": "1", 
            "priority_id": "1", 
            "user_id": "1"
        })
        print(f"Resultado final: {result}")
        assert result["success"] is True
        assert mock_port.create_ticket.call_count == 3
        print("✅ PRUEBA PASADA: El sistema reintentó y finalmente tuvo éxito.")
    except Exception as e:
        print(f"❌ PRUEBA FALLIDA: {e}")

def test_resilience_failure_after_max_retries():
    print("\n--- TEST 2: Fallo tras agotar todos los reintentos (Límite alcanzado) ---")
    mock_port = MagicMock()
    
    # Simulamos que falla siempre
    mock_port.create_ticket.side_effect = Exception("Odoo caído permanentemente")
    
    set_ticket_port(mock_port)
    
    try:
        create_ticket.invoke({
            "asunto": "Test", 
            "descripcion": "Test", 
            "ticket_type_id": "1", 
            "category_id": "1", 
            "urgency_id": "1", 
            "impact_id": "1", 
            "priority_id": "1", 
            "user_id": "1"
        })
        print("❌ PRUEBA FALLIDA: Debería haber lanzado una excepción tras 3 reintentos.")
    except Exception as e:
        # Tenacity reraise=True hará que salga la excepción original (Exception)
        print(f"Capturada excepción esperada: {e}")
        assert mock_port.create_ticket.call_count == 3
        print("✅ PRUEBA PASADA: El sistema se rindió tras 3 intentos exactos.")

if __name__ == "__main__":
    test_resilience_success_after_retries()
    test_resilience_failure_after_max_retries()
