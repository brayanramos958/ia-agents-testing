# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
Test por rol individual — conserva cuota diaria de Groq.

Ejecuta solo el bloque que necesitas validar en lugar de los 14 turnos completos.
Cada bloque consume ~50-70K tokens vs ~150K del test_fullflow completo.

Uso (desde agent-v2/, con agente en :8001 y backend en :8000):
    py scratch/test_rol.py creador
    py scratch/test_rol.py resueltor
    py scratch/test_rol.py supervisor
    py scratch/test_rol.py all                   # igual que test_fullflow.py pero modular
    py scratch/test_rol.py creador --delay 5     # 5s entre turnos (evita picos de TPM)

Presupuesto estimado por bloque (tokens Groq):
    creador:    5 turnos × ~12K avg  ≈  60K tokens
    resueltor:  5 turnos × ~12K avg  ≈  60K tokens
    supervisor: 4 turnos × ~12K avg  ≈  50K tokens
    all:                             ≈ 170K tokens  (1/3 del TPD diario de 500K)
"""

import time
import json
import argparse
import urllib.request
import urllib.error

AGENT_URL  = "http://127.0.0.1:8001/agent/chat"
HEALTH_URL = "http://127.0.0.1:8001/health"
HEADERS    = {"Content-Type": "application/json", "X-Agent-Key": "dev-key-change-in-prod"}
TIMEOUT    = 300

RUN_ID = int(time.time())

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

results        = []
total_chars_in  = 0   # proxy de tokens de entrada  (chars / 4 ≈ tokens)
total_chars_out = 0   # proxy de tokens de salida


# ─── HTTP helper ──────────────────────────────────────────────────────────────

def chat(user_id: int, rol: str, message: str, thread_id: str, delay: int = 0) -> dict:
    global total_chars_in, total_chars_out
    if delay:
        time.sleep(delay)

    payload = {"user_id": user_id, "user_rol": rol, "message": message, "thread_id": thread_id}
    body    = json.dumps(payload).encode("utf-8")
    total_chars_in += len(message)

    req   = urllib.request.Request(AGENT_URL, data=body, headers=HEADERS, method="POST")
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data    = json.loads(resp.read().decode("utf-8"))
            elapsed = time.monotonic() - start
            reply   = data.get("reply", "")
            total_chars_out += len(reply)
            return {"ok": True, "reply": reply, "thread_id": data.get("thread_id"), "elapsed": elapsed}
    except urllib.error.HTTPError as e:
        body_err = e.read().decode()[:300]
        return {"ok": False, "error": f"HTTP {e.code}: {body_err}", "elapsed": time.monotonic() - start}
    except Exception as e:
        return {"ok": False, "error": str(e), "elapsed": time.monotonic() - start}


# ─── Evaluacion ───────────────────────────────────────────────────────────────

def evaluate(label: str, result: dict, expect_any: list = None, forbidden: list = None):
    if not result["ok"]:
        results.append((FAIL, label, result.get("error", "")))
        print(f"  [FAIL] {label}")
        print(f"         Error: {result.get('error','')[:200]}")
        return

    reply   = result["reply"].lower()
    elapsed = result["elapsed"]

    if expect_any and not any(kw.lower() in reply for kw in expect_any):
        results.append((WARN, label, f"No contiene ninguna de: {expect_any}"))
        print(f"  [WARN] {label}  ({elapsed:.1f}s)")
        print(f"         Esperaba: {expect_any}")
        print(f"         Respuesta: {result['reply'][:200]}")
        return

    if forbidden:
        leaked = [kw for kw in forbidden if kw.lower() in reply]
        if leaked:
            results.append((FAIL, label, f"Texto prohibido: {leaked}"))
            print(f"  [FAIL] {label}  ({elapsed:.1f}s)")
            print(f"         Prohibido encontrado: {leaked}")
            return

    results.append((PASS, label, ""))
    print(f"  [PASS] {label}  ({elapsed:.1f}s)")
    print(f"         {result['reply'][:180].replace(chr(10), ' ')}")


# ─── BLOQUE 1: CREADOR ────────────────────────────────────────────────────────

def bloque_creador(delay: int):
    print(f"\n{'='*65}")
    print("  BLOQUE 1 — ROL CREADOR  (Ana Torres, user_id=1)")
    print(f"  thread_id: test-{RUN_ID}-user-1")
    print(f"{'='*65}")
    tid = f"test-{RUN_ID}-user-1"

    print("\n  T1.1 — Consulta de tickets abiertos")
    r = chat(1, "creador", "Hola, me puedes mostrar mis tickets abiertos?", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("Creador: consulta tickets abiertos", r,
        expect_any=["ticket", "TCK", "abierto", "no tienes", "sin tickets", "no hay"],
        forbidden=["paso 1", "campos requeridos:"])

    print("\n  T1.2 — Reportar problema (debe buscar solucion RAG primero)")
    r = chat(1, "creador", "Mi laptop no enciende, la presiono y no pasa nada.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("Creador: reporta problema — respuesta empatica", r,
        expect_any=["entiendo", "lamento", "problema", "laptop", "solucion", "intentaste", "verificar", "ticket"],
        forbidden=["paso 1", "campos requeridos:"])

    print("\n  T1.3 — Confirma que no hay solucion, solicita crear ticket")
    r = chat(1, "creador", "No, ya intente todo eso. Por favor crea el ticket.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("Creador: solicita datos para crear ticket", r,
        expect_any=["tipo", "categoria", "urgencia", "TCK", "creado", "ticket", "informacion", "datos", "confirmar"],
        forbidden=["paso 1", "campos requeridos:"])

    print("\n  T1.4 — Proporciona detalles del problema")
    r = chat(1, "creador",
        "Es un incidente de hardware, laptop Dell Latitude. Urgencia alta, impacto alto. "
        "Descripcion: el equipo no enciende desde esta manana, presiono el boton y no hay respuesta.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("Creador: ticket creado o solicita confirmacion", r,
        expect_any=["TCK", "creado", "registrado", "confirmas", "confirmar", "hardware", "incidente"],
        forbidden=["paso 1", "campos requeridos:"])

    print("\n  T1.5 — Feedback del agente")
    r = chat(1, "creador", "Muy bien, muchas gracias. Le doy un 5 de satisfaccion.", tid, delay)
    evaluate("Creador: feedback registrado o agradecimiento", r,
        expect_any=["gracias", "encantado", "ayudo", "satisfaccion", "5", "feedback", "registrado", "placer"])


# ─── BLOQUE 2: RESUELTOR ──────────────────────────────────────────────────────

def bloque_resueltor(delay: int):
    print(f"\n{'='*65}")
    print("  BLOQUE 2 — ROL RESUELTOR  (Carlos Ruiz, user_id=3)")
    print(f"  thread_id: test-{RUN_ID}-user-3")
    print(f"{'='*65}")
    tid = f"test-{RUN_ID}-user-3"

    print("\n  T2.1 — Ver tickets asignados")
    r = chat(3, "resueltor", "Que tickets tengo asignados?", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("Resueltor: lista tickets asignados", r,
        expect_any=["TCK", "ticket", "asignado", "tienes", "no tienes", "pendiente"],
        forbidden=["paso 1", "campos requeridos:"])

    print("\n  T2.2 — Detalle del primer ticket")
    r = chat(3, "resueltor", "Dame el detalle del primer ticket que aparece.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("Resueltor: detalle de ticket", r,
        expect_any=["TCK", "urgencia", "descripcion", "categoria", "estado", "asunto", "ticket"],
        forbidden=["paso 1", "campos requeridos:"])

    print("\n  T2.3 — Buscar solucion RAG")
    r = chat(3, "resueltor", "Hay alguna solucion conocida para este tipo de problema?", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("Resueltor: busqueda RAG de solucion", r,
        expect_any=["solucion", "similar", "encontre", "conocida", "anteriormente", "base", "no encontre", "no hay"],
        forbidden=["paso 1", "campos requeridos:"])

    print("\n  T2.4 — Resolver ticket")
    r = chat(3, "resueltor",
        "Listo, el problema era el cable de poder suelto. "
        "Resuelve el primer ticket de mi lista, causa raiz: cable desconectado, "
        "resolucion: se reconecto el cable de poder del disco duro.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("Resueltor: ticket resuelto o solicita confirmacion", r,
        expect_any=["resuelto", "confirmas", "confirmar", "TCK", "resolver", "cable", "cerrado"],
        forbidden=["paso 1", "campos requeridos:"])

    print("\n  T2.5 — Confirmar resolucion")
    r = chat(3, "resueltor", "Si, confirmo.", tid, delay)
    evaluate("Resueltor: confirmacion procesada", r,
        expect_any=["resuelto", "exitoso", "actualizado", "TCK", "listo", "correcto", "ok", "gracias",
                    "registrado", "confirmaci", "procesado", "completado"])


# ─── BLOQUE 3: SUPERVISOR ────────────────────────────────────────────────────

def bloque_supervisor(delay: int):
    print(f"\n{'='*65}")
    print("  BLOQUE 3 — ROL SUPERVISOR  (Pedro, user_id=5)")
    print(f"  thread_id: test-{RUN_ID}-user-5")
    print(f"{'='*65}")
    tid = f"test-{RUN_ID}-user-5"

    print("\n  T3.1 — Vision general")
    r = chat(5, "supervisor", "Dame un resumen del estado actual de los tickets.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("Supervisor: resumen general de tickets", r,
        expect_any=["ticket", "TCK", "total", "estado", "abierto", "resuelto", "sistema"],
        forbidden=["paso 1", "campos requeridos:"])

    print("\n  T3.2 — Tickets criticos sin asignar")
    r = chat(5, "supervisor", "Hay tickets criticos o urgentes sin asignar?", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("Supervisor: identifica tickets urgentes sin asignar", r,
        expect_any=["urgente", "critico", "sin asignar", "TCK", "asignar", "no hay", "todos asignados", "ticket"],
        forbidden=["paso 1", "campos requeridos:"])

    print("\n  T3.3 — Asignar ticket a Carlos Ruiz")
    r = chat(5, "supervisor", "Asigna el TCK-0002 a Carlos Ruiz.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("Supervisor: asignacion o solicita confirmacion", r,
        expect_any=["asignado", "confirmas", "confirmar", "TCK-0002", "Carlos", "asignar", "resueltor"],
        forbidden=["paso 1", "campos requeridos:"])

    print("\n  T3.4 — Confirmar asignacion")
    r = chat(5, "supervisor", "Si, confirmo la asignacion.", tid, delay)
    evaluate("Supervisor: asignacion confirmada", r,
        expect_any=["asignado", "exitoso", "listo", "ok", "correcto", "TCK-0002", "Carlos"])


# ─── Health check ─────────────────────────────────────────────────────────────

def check_health() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"  Agente: {data}")
            return True
    except Exception as e:
        print(f"  Sin conexion: {e}")
    return False


# ─── Resumen final ────────────────────────────────────────────────────────────

def print_summary(total_secs: float, roles_run: list):
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

    tokens_in_est  = total_chars_in  // 4
    tokens_out_est = total_chars_out // 4
    tokens_total   = tokens_in_est + tokens_out_est

    print(f"\n  {len(passed)}/{len(results)} pasaron  |  {len(warned)} advertencias  |  {len(failed)} fallaron")
    print(f"  Roles ejecutados: {', '.join(roles_run)}")
    print(f"  Tiempo total: {total_secs:.1f}s  (~{total_secs/max(len(results),1):.1f}s promedio por turno)")
    print(f"  Tokens estimados consumidos: ~{tokens_total:,}  (in: ~{tokens_in_est:,} | out: ~{tokens_out_est:,})")
    print(f"  Nota: el estimado de tokens es aproximado (chars/4). El real incluye system prompt + tool schemas.")

    if failed:
        print(f"\n  RESULTADO: FALLO — {len(failed)} turnos con error critico")
    elif warned:
        print(f"\n  RESULTADO: PARCIAL — respuestas imprecisas en {len(warned)} turno(s)")
    else:
        print(f"\n  RESULTADO: EXCELENTE — todos los turnos pasaron")

    print(f"{'='*65}\n")
    return len(failed)


# ─── Main ─────────────────────────────────────────────────────────────────────

ROLES_DISPONIBLES = ["creador", "resueltor", "supervisor", "all"]

def main():
    parser = argparse.ArgumentParser(
        description="Test por rol — conserva cuota Groq ejecutando solo el bloque necesario."
    )
    parser.add_argument(
        "rol",
        choices=ROLES_DISPONIBLES,
        help="Rol a probar: creador | resueltor | supervisor | all"
    )
    parser.add_argument(
        "--delay", type=int, default=0, metavar="SEG",
        help="Segundos de espera entre turnos (reduce picos de TPM). Default: 0."
    )
    args = parser.parse_args()

    print(f"\nVerificando agente...")
    if not check_health():
        print("ERROR: El agente no esta corriendo en :8001")
        sys.exit(1)

    print(f"\nRol(es): {args.rol.upper()}  |  Delay: {args.delay}s entre turnos  |  RUN_ID: {RUN_ID}")

    start_total = time.monotonic()
    roles_run   = []

    if args.rol in ("creador", "all"):
        bloque_creador(args.delay)
        roles_run.append("creador")

    if args.rol in ("resueltor", "all"):
        bloque_resueltor(args.delay)
        roles_run.append("resueltor")

    if args.rol in ("supervisor", "all"):
        bloque_supervisor(args.delay)
        roles_run.append("supervisor")

    failed_count = print_summary(time.monotonic() - start_total, roles_run)
    sys.exit(0 if failed_count == 0 else 1)


if __name__ == "__main__":
    main()
