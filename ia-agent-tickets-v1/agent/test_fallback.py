import os
import sys
from dotenv import load_dotenv

load_dotenv()

# Sobrescribimos a propósito la llave de Groq para que sea inválida
os.environ["GROQ_API_KEY"] = "gsk_invalid_key_for_testing_1234567890"

from graph import create_agent, get_response
from langchain_core.messages import HumanMessage

print("Inicializando agente...")
print(f"Llave de Groq forzada a: {os.environ.get('GROQ_API_KEY')}")
print(f"Llave de OpenRouter: {'Configurada' if os.environ.get('OPENROUTER_API_KEY') else 'NO CONFIGURADA'}")

try:
    graph = create_agent()

    print("Enviando mensaje...")
    messages = [HumanMessage(content="Hola, ¿con qué modelo estoy hablando? (Responde muy corto)")]
    
    # get_response requiere: graph, messages, thread_id, user_id, user_rol
    response = get_response(graph, messages, "test-thread", 1, "owner")
    
    print("\n✅ ¡RESPUESTA EXITOSA (Fallback funcionando)!\n")
    print(response)
                        
except Exception as e:
    print("\n❌ FALLÓ LA PRUEBA:\n")
    import traceback
    traceback.print_exc()
