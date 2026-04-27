"""
Multi-user dialog test.

Simula 5 personas interactuando con el agente de forma concurrente.
- Lado humano: OpenRouter (modelo free) genera mensajes realistas por persona
- Lado agente: Ollama local (gemma4:26b) responde
- Resultado: guardado en dialog_test_YYYYMMDD_HHMMSS.txt
"""

import asyncio
import httpx
import os
import sys
import json
import uuid
from datetime import datetime
from dotenv import load_dotenv
from openai import AsyncOpenAI

# Forzar UTF-8 en stdout para el log en consola
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

load_dotenv()

# ── Configuración ──────────────────────────────────────────────────────────────

AGENT_URL  = "http://127.0.0.1:8001/agent/chat"
AGENT_KEY  = os.getenv("AGENT_API_KEY", "dev-key-change-in-prod")
MAX_TURNS  = 6   # turnos máximos por conversación
DELAY_BETWEEN_TURNS = 2  # segundos entre turnos (evita saturar Ollama)

OPENROUTER_KEY   = os.getenv("OPENROUTER_API_KEY", "")
GROQ_KEY         = os.getenv("GROQ_API_KEY", "")

# Cliente para simular humanos — Groq preferido (menos rate limit), OpenRouter como fallback
def _build_human_client() -> tuple[AsyncOpenAI, str]:
    if GROQ_KEY:
        client = AsyncOpenAI(
            api_key=GROQ_KEY,
            base_url="https://api.groq.com/openai/v1",
        )
        model = "llama-3.1-8b-instant"
        print(f"[simulador] Groq -> {model}")
        return client, model

    if OPENROUTER_KEY:
        client = AsyncOpenAI(
            api_key=OPENROUTER_KEY,
            base_url="https://openrouter.ai/api/v1",
        )
        model = "meta-llama/llama-3.3-70b-instruct:free"
        print(f"[simulador] OpenRouter -> {model}")
        return client, model

    raise RuntimeError(
        "Se requiere OPENROUTER_API_KEY o GROQ_API_KEY para simular usuarios.\n"
        "Agrega al menos una en el .env."
    )


# ── Personas ───────────────────────────────────────────────────────────────────

PERSONAS = [
    {
        "name":   "Ana Torres",
        "user_id": 1,
        "rol":    "creador",
        "icon":   "[U]",
        "scenario": (
            "Eres Ana Torres, contadora. Tu computadora portatil no enciende desde esta manana. "
            "Hay un cierre contable importante hoy. Estas frustrada pero eres educada. "
            "Proporciona detalles cuando te los pidan: es una Dell Latitude, "
            "hubo un corte de luz ayer y desde entonces no enciende."
        ),
    },
    {
        "name":   "Luis Mendez",
        "user_id": 2,
        "rol":    "creador",
        "icon":   "[U]",
        "scenario": (
            "Eres Luis Mendez, vendedor. No puedes acceder al sistema ERP desde hace 2 horas, "
            "te sale error 'usuario bloqueado'. Tienes una presentacion con un cliente en 1 hora. "
            "Eres impaciente y pides solucion rapida. "
            "Tu usuario es lmendez, usas el ERP Odoo en el navegador Chrome."
        ),
    },
    {
        "name":   "Carlos Ruiz",
        "user_id": 3,
        "rol":    "resueltor",
        "icon":   "[T]",
        "scenario": (
            "Eres Carlos Ruiz, tecnico de soporte nivel 1. "
            "Acabas de iniciar tu turno y quieres ver que tickets tienes asignados. "
            "Luego quieres resolver uno de ellos (el mas urgente). "
            "Eres metodico y preguntas el estado actual antes de actuar."
        ),
    },
    {
        "name":   "Maria Gonzalez",
        "user_id": 4,
        "rol":    "resueltor",
        "icon":   "[T]",
        "scenario": (
            "Eres Maria Gonzalez, tecnica de redes. "
            "Estas investigando un incidente de conectividad reportado en el piso 3. "
            "Quieres ver los tickets abiertos de categoria Red, "
            "luego actualizar el estado de uno indicando que ya encontraste la causa raiz "
            "(un switch mal configurado)."
        ),
    },
    {
        "name":   "Pedro Supervisor",
        "user_id": 5,
        "rol":    "supervisor",
        "icon":   "[S]",
        "scenario": (
            "Eres Pedro Supervisor, jefe de la mesa de ayuda. "
            "Es lunes por la manana y necesitas un panorama general: "
            "cuantos tickets abiertos hay, cuales son los mas urgentes, "
            "y quienes son los agentes con mas carga. "
            "Tambien quieres asignar un ticket urgente a Carlos Ruiz (ID 3)."
        ),
    },
]


# ── Simulador de usuario ───────────────────────────────────────────────────────

HUMAN_SYSTEM = """
Eres {name}, un usuario real interactuando con un sistema de helpdesk por chat.
Contexto de tu situación: {scenario}

REGLAS IMPORTANTES:
- Escribe mensajes cortos y naturales como lo haría un usuario real (máximo 3 oraciones)
- Responde según el contexto de lo que el agente te dijo
- Si el agente te pide información, proporciónala
- Si tu problema fue resuelto o tu tarea completada, di "gracias, hasta luego" o similar para terminar
- NO te salgas de tu rol
- NO menciones que eres una IA
- Escribe SOLO el mensaje del usuario, sin prefijos ni explicaciones
""".strip()


async def generate_human_message(
    client: AsyncOpenAI,
    model: str,
    persona: dict,
    history: list[dict],
) -> str:
    system = HUMAN_SYSTEM.format(
        name=persona["name"],
        scenario=persona["scenario"],
    )
    messages = [{"role": "system", "content": system}] + history

    for attempt in range(3):
        resp = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.8,
            max_tokens=200,
        )
        text = resp.choices[0].message.content.strip()
        if text:
            return text
        # Groq devolvio vacio — reintenta con prompt mas directo
        messages = [{"role": "system", "content": system + "\n\nIMPORTANTE: debes responder con al menos una oracion."}] + history

    # Si sigue vacio, devuelve un mensaje de cierre natural para no romper el flujo
    return "Gracias por la ayuda, hasta luego."


# ── Cliente del agente ─────────────────────────────────────────────────────────

async def call_agent(
    http: httpx.AsyncClient,
    persona: dict,
    message: str,
    thread_id: str,
) -> str:
    resp = await http.post(
        AGENT_URL,
        headers={
            "Content-Type": "application/json",
            "X-Agent-Key": AGENT_KEY,
        },
        json={
            "user_id":   persona["user_id"],
            "user_rol":  persona["rol"],
            "message":   message,
            "thread_id": thread_id,
        },
        timeout=120.0,
    )
    resp.raise_for_status()
    return resp.json()["reply"]


# ── Conversación de una persona ────────────────────────────────────────────────

async def run_conversation(
    persona: dict,
    client: AsyncOpenAI,
    model: str,
    semaphore: asyncio.Semaphore,
    log_lines: list[str],
) -> None:
    thread_id = f"dialog-test-{persona['user_id']}-{uuid.uuid4().hex[:8]}"
    history: list[dict] = []  # historial para el simulador humano

    header = (
        f"\n{'='*70}\n"
        f"  {persona['icon']} {persona['name'].upper()}  |  rol: {persona['rol']}  |  thread: {thread_id}\n"
        f"{'='*70}"
    )
    log_lines.append(header)
    print(header)

    async with httpx.AsyncClient() as http:
        for turn in range(1, MAX_TURNS + 1):
            async with semaphore:
                # 1. Generar mensaje humano
                human_msg = await generate_human_message(client, model, persona, history)

                turn_header = f"\n[Turno {turn}]"
                user_line   = f"  {persona['icon']} {persona['name']}: {human_msg}"
                log_lines.append(turn_header)
                log_lines.append(user_line)
                print(turn_header)
                print(user_line)

                # 2. Llamar al agente
                try:
                    agent_reply = await call_agent(http, persona, human_msg, thread_id)
                except Exception as exc:
                    err = f"  [AGENTE ERROR]: {type(exc).__name__}: {exc}"
                    log_lines.append(err)
                    print(err)
                    break

                agent_line = f"  [A] Agente: {agent_reply}"
                log_lines.append(agent_line)
                print(agent_line)

                # 3. Actualizar historial del simulador
                history.append({"role": "user",      "content": human_msg})
                history.append({"role": "assistant",  "content": agent_reply})

                # 4. Detectar fin de conversación
                farewells = [
                    "gracias", "hasta luego", "adiós", "adios",
                    "bye", "perfecto", "listo", "resuelto",
                ]
                if any(w in human_msg.lower() for w in farewells):
                    log_lines.append("  [FIN] Conversacion finalizada por el usuario.")
                    print("  [FIN] Conversacion finalizada por el usuario.")
                    break

            await asyncio.sleep(DELAY_BETWEEN_TURNS)

    log_lines.append(f"\n{'─'*70}")


# ── Orquestador principal ──────────────────────────────────────────────────────

async def main() -> None:
    output_file = f"dialog_test_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
    log_lines: list[str] = []

    title = (
        f"REPORTE DE DIALOGO — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        f"Agente: Ollama gemma4:26b @ localhost:8001\n"
        f"Personas: {len(PERSONAS)} usuarios simultáneos\n"
        f"Turnos máximos por conversación: {MAX_TURNS}\n"
    )
    log_lines.append(title)
    print(title)

    client, model = _build_human_client()

    # Ollama es single-threaded — ejecutar conversaciones de forma secuencial
    # para que cada persona tenga su dialogo completo sin interleaving
    semaphore = asyncio.Semaphore(1)

    for persona in PERSONAS:
        await run_conversation(persona, client, model, semaphore, log_lines)

    # Guardar resultado
    content = "\n".join(log_lines)
    with open(output_file, "w", encoding="utf-8", errors="replace") as f:
        f.write(content)

    print(f"\n[OK] Dialogos guardados en: {output_file}")


if __name__ == "__main__":
    asyncio.run(main())
