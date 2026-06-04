import os
from dotenv import load_dotenv

load_dotenv()

from langchain_openai import ChatOpenAI

fallback_llm = ChatOpenAI(
    api_key=os.environ.get("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
    model="google/gemini-2.0-flash-lite-preview-02-05:free",
    temperature=0.1
)

print("Probando fallback_llm directamente...")
try:
    resp = fallback_llm.invoke("Hola")
    print("ÉXITO:\n", resp)
except Exception as e:
    print("ERROR:\n", type(e), e)
