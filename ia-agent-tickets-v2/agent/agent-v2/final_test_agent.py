import requests
import json

AGENT_URL = "http://127.0.0.1:8001/agent/chat"
HEADERS = {
    "Content-Type": "application/json",
    "X-Agent-Key": "dev-key-change-in-prod"
}

def test_chat(user_id, role, message, thread_id=None):
    payload = {
        "user_id": user_id,
        "user_rol": role,
        "message": message,
        "thread_id": thread_id
    }
    print(f"\n--- Probando Rol: {role} (ID: {user_id}) ---")
    print(f"Mensaje: {message}")
    response = requests.post(AGENT_URL, headers=HEADERS, json=payload)
    if response.status_code == 200:
        data = response.json()
        print(f"Respuesta del Agente:\n{data['reply']}")
        return data.get("thread_id")
    else:
        print(f"❌ Error: {response.status_code} - {response.text}")
        return None

if __name__ == "__main__":
    # Test 1: Creador lista sus tickets
    test_chat(1, "creador", "Hola, enumera mis tickets por favor.")

    # Test 2: Resueltor ve sus tareas
    # Nota: Antes asignamos el TCK-0002 al ID 3
    test_chat(3, "resueltor", "¿Qué tickets tengo asignados para hoy?")

    # Test 3: Supervisor
    test_chat(5, "supervisor", "Dame un reporte rápido de los tickets en el sistema.")
