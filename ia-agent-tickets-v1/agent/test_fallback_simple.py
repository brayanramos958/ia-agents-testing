import os
import sys
from dotenv import load_dotenv

load_dotenv()

os.environ["GROQ_API_KEY"] = "gsk_invalid_key_for_testing_1234567890"

from langchain_groq import ChatGroq
from langchain_openai import ChatOpenAI

primary_llm = ChatGroq(
    model="llama-3.1-8b-instant",
    temperature=0.1
)

fallback_llm = ChatOpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
    model="meta-llama/llama-3-8b-instruct:free",
    temperature=0.1
)

llm = primary_llm.with_fallbacks([fallback_llm], exceptions_to_handle=(Exception,))

print("Probando invocación directa (sin LangGraph)...")
try:
    resp = llm.invoke("Hola, di 'funcionó el fallback'")
    print("ÉXITO:\n", resp)
except Exception as e:
    print("ERROR:\n", e)
