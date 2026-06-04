# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
Test de flujo completo — 1 usuario por rol, end-to-end.

Cubre:
  CREADOR  — ver tickets, buscar solucion RAG, crear ticket, ver detalle, feedback
  RESUELTOR— ver asignados, ver detalle, resolver ticket (actualiza RAG)
  SUPERVISOR— ver todos, asignar ticket, reabrir ticket

El thread_id se mantiene entre turnos de cada rol para validar memoria de conversacion.
Los resultados por turno se evaluan con criterios simples (palabras clave esperadas).

Ejecutar desde agent-v2/ con agente en :8001 y backend en :8000:
    py scratch/test_fullflow.py
"""

import time
import json
import urllib.request
import urllib.error

AGENT_URL  = "http://127.0.0.1:8001/agent/chat"
HEALTH_URL = "http://127.0.0.1:8001/health"
HEADERS    = {"Content-Type": "application/json", "X-Agent-Key": "dev-key-change-in-prod"}
TIMEOUT    = 300  # 5 min — needed for local CPU inference (qwen3:14b ~60-120s/turn)

# Unique run ID — ensures each test run gets fresh checkpoint threads.
# Without this, same-day re-runs reuse user-{id}-{date} thread and accumulate
# conversation history, causing 413 (request too large) after a few runs.
RUN_ID = int(time.time())

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

results = []


# ─── HTTP helper ──────────────────────────────────────────────────────────────

def chat(user_id: int, rol: str, message: str, thread_id: str = None) -> dict:
    payload = {"user_id": user_id, "user_rol": rol, "message": message, "thread_id": thread_id}
    body    = json.dumps(payload).encode("utf-8")
    req     = urllib.request.Request(AGENT_URL, data=body, headers=HEADERS, method="POST")
    start   = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data    = json.loads(resp.read().decode("utf-8"))
            elapsed = time.monotonic() - start
            return {"ok": True, "reply": data.get("reply", ""), "thread_id": data.get("thread_id"), "elapsed": elapsed}
    except urllib.error.HTTPError as e:
        return {"ok": False, "error": f"HTTP {e.code}: {e.read().decode()[:300]}", "elapsed": time.monotonic() - start}
    except Exception as e:
        return {"ok": False, "error": str(e), "elapsed": time.monotonic() - start}


# ─── Evaluacion por turno ─────────────────────────────────────────────────────

def evaluate(label: str, result: dict, expect_any: list[str] = None, forbidden: list[str] = None):
    if not result["ok"]:
        results.append((FAIL, label, result.get("error", "HTTP error")))
        print(f"  [{FAIL}] {label}")
        print(f"         Error: {result.get('error','')}")
        return

    reply = result["reply"].lower()
    elapsed = result["elapsed"]

    # Verificar palabras clave esperadas
    if expect_any:
        matched = any(kw.lower() in reply for kw in expect_any)
        if not matched:
            results.append((WARN, label, f"Respuesta no contiene ninguna de: {expect_any}"))
            print(f"  [{WARN}] {label}  ({elapsed:.1f}s)")
            print(f"         Esperaba alguna de: {expect_any}")
            print(f"         Respuesta: {result['reply'][:200]}")
            return

    # Verificar palabras prohibidas (prompt leakage, errores)
    if forbidden:
        leaked = [kw for kw in forbidden if kw.lower() in reply]
        if leaked:
            results.append((FAIL, label, f"Respuesta contiene texto prohibido: {leaked}"))
            print(f"  [{FAIL}] {label}  ({elapsed:.1f}s)")
            print(f"         Texto prohibido encontrado: {leaked}")
            return

    results.append((PASS, label, ""))
    print(f"  [{PASS}] {label}  ({elapsed:.1f}s)")
    print(f"         {result['reply'][:180].replace(chr(10),' ')}")


# ─── BLOQUE 1: CREADOR ────────────────────────────────────────────────────────

def test_creador():
    print(f"\n{'='*65}")
    print("  BLOQUE 1 — ROL CREADOR  (Ana Torres, user_id=1)")
    print(f"{'='*65}")
    tid = f"test-{RUN_ID}-user-1"

    # 1.1 Saludo y ver tickets existentes
    print("\n  Turno 1.1 — Consulta de tickets abiertos")
    r = chat(1, "creador", "Hola, me puedes mostrar mis tickets abiertos?")
    tid = r.get("thread_id", tid)
    evaluate(
        "Creador: consulta tickets abiertos",
        r,
        expect_any=["ticket", "TCK", "abierto", "no tienes", "sin tickets", "no hay"],
        forbidden=["paso 1", "paso 2", "paso 3", "infiere lo que puedas", "campos requeridos:"]
    )

    # 1.2 Reportar problema — activa flujo de RAG antes de crear ticket
    print("\n  Turno 1.2 — Reportar problema (debe buscar solucion RAG primero)")
    r = chat(1, "creador", "Mi laptop no enciende, la presiono y no pasa nada.", tid)
    tid = r.get("thread_id", tid)
    evaluate(
        "Creador: reporta problema — respuesta empatica",
        r,
        expect_any=["entiendo", "lamento", "problema", "laptop", "solucion", "intentaste", "verificar", "ticket"],
        forbidden=["paso 1", "paso 2", "campos requeridos:"]
    )

    # 1.3 Confirmar que no hay solucion conocida — debe crear ticket
    print("\n  Turno 1.3 — Confirma que no hay solucion, solicita crear ticket")
    r = chat(1, "creador", "No, ya intente todo eso. Por favor crea el ticket.", tid)
    tid = r.get("thread_id", tid)
    evaluate(
        "Creador: solicita datos para crear ticket",
        r,
        expect_any=["tipo", "categoria", "urgencia", "TCK", "creado", "ticket", "informacion", "datos", "confirmar"],
        forbidden=["paso 1", "campos requeridos:"]
    )

    # 1.4 Proporcionar datos del ticket
    print("\n  Turno 1.4 — Proporciona detalles del problema")
    r = chat(1, "creador", "Es un incidente de hardware, laptop Dell Latitude. Urgencia alta, impacto alto. El equipo no enciende desde esta manana.", tid)
    tid = r.get("thread_id", tid)
    evaluate(
        "Creador: ticket creado o solicita confirmacion",
        r,
        expect_any=["TCK", "creado", "registrado", "confirmas", "confirmar", "hardware", "incidente"],
        forbidden=["paso 1", "campos requeridos:"]
    )

    # 1.5 Feedback del agente
    print("\n  Turno 1.5 — Feedback del agente")
    r = chat(1, "creador", "Muy bien, muchas gracias. Le doy un 5 de satisfaccion.", tid)
    tid = r.get("thread_id", tid)
    evaluate(
        "Creador: feedback registrado o agradecimiento",
        r,
        expect_any=["gracias", "encantado", "ayudo", "satisfaccion", "5", "feedback", "registrado", "placer"],
    )

    return tid


# ─── BLOQUE 2: RESUELTOR ──────────────────────────────────────────────────────

def test_resueltor():
    print(f"\n{'='*65}")
    print("  BLOQUE 2 — ROL RESUELTOR  (Carlos Ruiz, user_id=3)")
    print(f"{'='*65}")
    tid = f"test-{RUN_ID}-user-3"

    # 2.1 Ver tickets asignados
    print("\n  Turno 2.1 — Ver tickets asignados")
    r = chat(3, "resueltor", "Que tickets tengo asignados?")
    tid = r.get("thread_id", tid)
    evaluate(
        "Resueltor: lista tickets asignados",
        r,
        expect_any=["TCK", "ticket", "asignado", "tienes", "no tienes", "pendiente"],
        forbidden=["paso 1", "campos requeridos:"]
    )

    # 2.2 Pedir detalle del primer ticket
    print("\n  Turno 2.2 — Detalle del primer ticket")
    r = chat(3, "resueltor", "Dame el detalle del primer ticket que aparece.", tid)
    tid = r.get("thread_id", tid)
    evaluate(
        "Resueltor: detalle de ticket",
        r,
        expect_any=["TCK", "urgencia", "descripcion", "categoria", "estado", "asunto", "ticket"],
        forbidden=["paso 1", "campos requeridos:"]
    )

    # 2.3 Buscar solucion en RAG
    print("\n  Turno 2.3 — Buscar solucion conocida")
    r = chat(3, "resueltor", "Hay alguna solucion conocida para este tipo de problema?", tid)
    tid = r.get("thread_id", tid)
    evaluate(
        "Resueltor: busqueda RAG de solucion",
        r,
        expect_any=["solucion", "similar", "encontre", "conocida", "anteriormente", "base", "no encontre", "no hay"],
        forbidden=["paso 1", "campos requeridos:"]
    )

    # 2.4 Resolver el ticket
    print("\n  Turno 2.4 — Resolver ticket")
    r = chat(3, "resueltor", "Listo, el problema era el cable de poder suelto. Resuelve el primer ticket de mi lista, causa raiz: cable desconectado, resolucion: se reconecto el cable de poder del disco duro.", tid)
    tid = r.get("thread_id", tid)
    evaluate(
        "Resueltor: ticket resuelto o solicita confirmacion",
        r,
        expect_any=["resuelto", "confirmas", "confirmar", "TCK", "resolver", "cable", "cerrado"],
        forbidden=["paso 1", "campos requeridos:"]
    )

    # 2.5 Confirmar resolucion
    print("\n  Turno 2.5 — Confirmar resolucion")
    r = chat(3, "resueltor", "Si, confirmo.", tid)
    tid = r.get("thread_id", tid)
    evaluate(
        "Resueltor: confirmacion de resolucion procesada",
        r,
        expect_any=["resuelto", "exitoso", "actualizado", "TCK", "listo", "correcto", "ok", "gracias"],
    )

    return tid


# ─── BLOQUE 3: SUPERVISOR ────────────────────────────────────────────────────

def test_supervisor():
    print(f"\n{'='*65}")
    print("  BLOQUE 3 — ROL SUPERVISOR  (Pedro, user_id=5)")
    print(f"{'='*65}")
    tid = f"test-{RUN_ID}-user-5"

    # 3.1 Vision general del sistema
    print("\n  Turno 3.1 — Vision general")
    r = chat(5, "supervisor", "Dame un resumen del estado actual de los tickets.")
    tid = r.get("thread_id", tid)
    evaluate(
        "Supervisor: resumen general de tickets",
        r,
        expect_any=["ticket", "TCK", "total", "estado", "abierto", "resuelto", "sistema"],
        forbidden=["paso 1", "campos requeridos:"]
    )

    # 3.2 Tickets sin asignar
    print("\n  Turno 3.2 — Tickets criticos sin asignar")
    r = chat(5, "supervisor", "Hay tickets criticos o urgentes sin asignar?", tid)
    tid = r.get("thread_id", tid)
    evaluate(
        "Supervisor: identifica tickets urgentes sin asignar",
        r,
        expect_any=["urgente", "critico", "sin asignar", "TCK", "asignar", "no hay", "todos asignados", "ticket"],
        forbidden=["paso 1", "campos requeridos:"]
    )

    # 3.3 Asignar ticket a resueltor
    print("\n  Turno 3.3 — Asignar ticket a Carlos Ruiz")
    r = chat(5, "supervisor", "Asigna el TCK-0002 a Carlos Ruiz.", tid)
    tid = r.get("thread_id", tid)
    evaluate(
        "Supervisor: asignacion o solicita confirmacion",
        r,
        expect_any=["asignado", "confirmas", "confirmar", "TCK-0002", "Carlos", "asignar", "resueltor"],
        forbidden=["paso 1", "campos requeridos:"]
    )

    # 3.4 Confirmar asignacion
    print("\n  Turno 3.4 — Confirmar asignacion")
    r = chat(5, "supervisor", "Si, confirmo la asignacion.", tid)
    tid = r.get("thread_id", tid)
    evaluate(
        "Supervisor: asignacion confirmada",
        r,
        expect_any=["asignado", "exitoso", "listo", "ok", "correcto", "TCK-0002", "Carlos"],
    )

    return tid


# ─── Verificacion previa ──────────────────────────────────────────────────────

def check_health() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"  Agente: {data}")
            return True
    except Exception as e:
        print(f"  Sin conexion: {e}")
    return False


# ─── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\nVerificando agente...")
    if not check_health():
        print("ERROR: El agente no esta corriendo en :8001")
        sys.exit(1)

    start_total = time.monotonic()

    test_creador()
    test_resueltor()
    test_supervisor()

    total = time.monotonic() - start_total

    # ─── Resumen ──────────────────────────────────────────────────────────────
    print(f"\n\n{'='*65}")
    print("  RESUMEN FINAL")
    print(f"{'='*65}")

    passed = [r for r in results if r[0] == PASS]
    warned = [r for r in results if r[0] == WARN]
    failed = [r for r in results if r[0] == FAIL]

    for status, label, detail in results:
        marker = "OK" if status == PASS else ("!!" if status == WARN else "XX")
        print(f"  [{marker}] {label}")
        if detail:
            print(f"       {detail[:120]}")

    print(f"\n  {len(passed)}/{len(results)} pasaron  |  {len(warned)} advertencias  |  {len(failed)} fallaron")
    print(f"  Tiempo total: {total:.1f}s  (~{total/len(results):.1f}s promedio por turno)")

    if failed:
        print(f"\n  RESULTADO: FALLO — {len(failed)} turnos con error critico")
    elif warned:
        print(f"\n  RESULTADO: PARCIAL — el agente responde pero algunas respuestas son imprecisas")
    else:
        print(f"\n  RESULTADO: EXCELENTE — todos los turnos pasaron")

    print(f"{'='*65}\n")
    sys.exit(0 if not failed else 1)
