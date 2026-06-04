# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
Tests calibrados para SARA v2 — nuevos prompts con Vercel AI Gateway.

Cubre los flujos reales tal como los nuevos prompts los definen:
  CREADOR    — saludo SARA, ver tickets, incidente laptop (con system_equipment),
               solicitud de software (flujo de aprobación), usuario frustrado
  RESUELTOR  — tickets ordenados por SLA, detalle, RAG, resolver con causa raíz
  SUPERVISOR — dashboard ACCIÓN REQUERIDA, aprobar ticket, asignar con carga

Diferencias clave respecto a test_rol.py:
  - Puerto configurable (--port, default 8002)
  - Flujo creador con paso extra de sistema/equipo afectado
  - Keywords más amplias y tolerantes al estilo conversacional de SARA
  - Turno de solicitud de software con flujo de aprobación
  - Verificación de identidad SARA
  - Respuesta completa en modo --verbose

Uso (desde agent-v2/):
    uv run python scratch/test_sara.py creador
    uv run python scratch/test_sara.py resueltor
    uv run python scratch/test_sara.py supervisor
    uv run python scratch/test_sara.py software        # flujo solicitud instalación
    uv run python scratch/test_sara.py all
    uv run python scratch/test_sara.py creador --port 8001 --delay 3 --verbose
"""

import time
import json
import argparse
import urllib.request
import urllib.error

# ─── Configuración ─────────────────────────────────────────────────────────────

DEFAULT_PORT = 8002
TIMEOUT      = 200   # 3+ min por turno — supervisor encadena 3+ tool calls con Groq
HEADERS      = {"Content-Type": "application/json", "X-Agent-Key": "dev-key-change-in-prod"}
RUN_ID       = int(time.time())

PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"

results         = []
total_chars_in  = 0
total_chars_out = 0
verbose         = False
AGENT_URL       = ""
HEALTH_URL      = ""


# ─── HTTP helper ───────────────────────────────────────────────────────────────

def chat(user_id: int, rol: str, message: str, thread_id: str, delay: int = 0) -> dict:
    global total_chars_in, total_chars_out
    if delay:
        time.sleep(delay)

    total_chars_in += len(message)
    payload = {"user_id": user_id, "user_rol": rol, "message": message, "thread_id": thread_id}
    body    = json.dumps(payload).encode("utf-8")
    req     = urllib.request.Request(AGENT_URL, data=body, headers=HEADERS, method="POST")
    start   = time.monotonic()

    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
            data    = json.loads(resp.read().decode("utf-8"))
            elapsed = time.monotonic() - start
            reply   = data.get("reply", "")
            total_chars_out += len(reply)
            return {"ok": True, "reply": reply, "thread_id": data.get("thread_id"), "elapsed": elapsed}
    except urllib.error.HTTPError as e:
        body_err = e.read().decode()[:400]
        return {"ok": False, "error": f"HTTP {e.code}: {body_err}", "elapsed": time.monotonic() - start}
    except Exception as e:
        return {"ok": False, "error": str(e), "elapsed": time.monotonic() - start}


# ─── Evaluación ────────────────────────────────────────────────────────────────

def evaluate(label: str, result: dict, expect_any: list = None, forbidden: list = None):
    if not result["ok"]:
        results.append((FAIL, label, result.get("error", "")))
        print(f"  [FAIL] {label}")
        print(f"         Error: {result.get('error', '')[:300]}")
        return

    reply   = result["reply"].lower()
    elapsed = result["elapsed"]

    preview = result["reply"] if verbose else result["reply"][:200].replace("\n", " ")

    if expect_any and not any(kw.lower() in reply for kw in expect_any):
        results.append((WARN, label, f"No contiene ninguna de: {expect_any}"))
        print(f"  [WARN] {label}  ({elapsed:.1f}s)")
        print(f"         Esperaba: {expect_any}")
        print(f"         Respuesta: {preview}")
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
    print(f"         {preview}")


# ─── BLOQUE CREADOR — Incidente laptop ────────────────────────────────────────
# Flujo real de los nuevos prompts:
#   Saludo → ver tickets → reportar problema → SARA pregunta afectados →
#   SARA pregunta equipo → RAG / verificación → datos + confirmación →
#   ticket creado → feedback

def bloque_creador(delay: int):
    print(f"\n{'='*65}")
    print("  BLOQUE CREADOR — Incidente laptop  (Ana Torres, user_id=1)")
    print(f"  thread_id: test-{RUN_ID}-c1")
    print(f"{'='*65}")
    tid = f"test-{RUN_ID}-c1"

    # T1.1 — Saludo: SARA se identifica y pregunta en qué ayuda
    print("\n  T1.1 — Saludo e identidad de SARA")
    r = chat(1, "creador", "Hola, buenos días.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: saludo e identidad", r,
        expect_any=["sara", "hola", "ayud", "bienvenid", "soporte", "mesa", "its"],
        forbidden=["paso 1", "campos requeridos:", "herramientas disponibles"])

    # T1.2 — Ver tickets propios
    print("\n  T1.2 — Consulta tickets abiertos")
    r = chat(1, "creador", "Puedes mostrarme mis tickets que tengo abiertos?", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: lista tickets del usuario", r,
        expect_any=["TCK", "ticket", "abierto", "no tienes", "no hay", "solicitud", "incidente"],
        forbidden=["paso 1", "campos requeridos:"])

    # T1.3 — Reporta problema: SARA escucha con empatía
    print("\n  T1.3 — Usuario reporta problema con laptop")
    r = chat(1, "creador", "Tengo un problema urgente, mi laptop Dell no enciende desde esta mañana.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: empatía y pregunta inicial", r,
        expect_any=["entiendo", "lamento", "cuéntame", "laptop", "encender", "problema",
                    "intentaste", "verificar", "mañana", "qué", "pasando", "ayudar"],
        forbidden=["paso 1", "campos requeridos:"])

    # T1.4 — SARA pregunta cuántos afectados / equipo (nuevos pasos del prompt)
    print("\n  T1.4 — Contexto: afectados y equipo")
    r = chat(1, "creador",
        "Solo me pasa a mí. Es mi laptop de trabajo, una Dell Latitude 5520. "
        "Ya intenté desconectarla y volverla a conectar pero nada.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: procesa contexto y busca solución", r,
        expect_any=["solucion", "encontr", "intentar", "paso", "verificar", "técnico",
                    "ticket", "crear", "equipo", "sistema", "batería", "encender"],
        forbidden=["paso 1", "campos requeridos:"])

    # T1.5 — Usuario pide crear el ticket con datos completos
    print("\n  T1.5 — Solicita crear ticket con datos")
    r = chat(1, "creador",
        "No, ya intenté todo eso y no funcionó. Por favor crea el ticket. "
        "Es urgente, afecta solo mi equipo y necesito mi laptop para trabajar.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: resumen para confirmación o ticket creado", r,
        expect_any=["confirmas", "confirmar", "TCK", "INC", "creado", "registrado",
                    "incidente", "hardware", "resumen", "crear", "urgente"],
        forbidden=["paso 1", "campos requeridos:"])

    # T1.6 — Confirmación explícita
    print("\n  T1.6 — Confirmación de creación")
    r = chat(1, "creador", "Sí, confirmo. Crea el ticket.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: ticket creado con número", r,
        expect_any=["TCK", "INC", "SR", "creado", "registrado", "ticket", "número",
                    "soporte", "revisará", "pronto"],
        forbidden=["paso 1", "campos requeridos:"])

    # T1.7 — Feedback 5/5
    print("\n  T1.7 — Feedback del servicio")
    r = chat(1, "creador", "Muy bien, muchas gracias SARA. Te doy un 5 de satisfacción.", tid, delay)
    evaluate("SARA: registra feedback y despide", r,
        expect_any=["gracias", "satisfacción", "calificación", "placer", "encantado",
                    "registrad", "ayud", "cualquier"])


# ─── BLOQUE CREADOR SOFTWARE — Solicitud de instalación ───────────────────────
# Flujo diferenciado: SARA explica proceso de aprobación ANTES de pedir datos

def bloque_software(delay: int):
    print(f"\n{'='*65}")
    print("  BLOQUE CREADOR SOFTWARE — Instalación Adobe  (user_id=1)")
    print(f"  thread_id: test-{RUN_ID}-sw1")
    print(f"{'='*65}")
    tid = f"test-{RUN_ID}-sw1"

    # TS.1 — Usuario pide instalar software
    print("\n  TS.1 — Solicitud de instalación de software")
    r = chat(1, "creador",
        "Necesito que me instalen Adobe Photoshop en mi equipo para un proyecto.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: explica flujo de aprobación antes de pedir datos", r,
        expect_any=["aprobación", "aprobado", "jef", "revisar", "solicitud",
                    "proceso", "instalación", "autorizar", "soporte", "listo"],
        forbidden=["paso 1", "campos requeridos:", "urgencia primero"])

    # TS.2 — Usuario responde Q1 (nombre del software) y da contexto completo
    print("\n  TS.2 — Usuario da nombre del software y justificación")
    r = chat(1, "creador",
        "Adobe Photoshop CC. Lo necesito para diseñar folletos y materiales de marketing "
        "para el lanzamiento de un producto la próxima semana. Es urgente. "
        "Por favor procede a registrar la solicitud.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: crea SR- o pide confirmación con datos", r,
        expect_any=["SR", "solicitud", "registrad", "creado", "TCK", "confirmas",
                    "photoshop", "adobe", "instalación", "aprobación", "jefatura",
                    "confirmar", "resumen", "procedo"],
        forbidden=["paso 1", "campos requeridos:"])

    # TS.3 — Confirmación y feedback
    print("\n  TS.3 — Confirmación y feedback")
    r = chat(1, "creador", "Sí, confirmo. Y te doy un 5 de satisfacción.", tid, delay)
    evaluate("SARA: confirma SR creado y registra feedback", r,
        expect_any=["SR", "TCK", "registrad", "creado", "aprobación", "jefatura",
                    "gracias", "satisfacción", "placer", "encantado",
                    "solicitud", "listo", "registrada"])


# ─── BLOQUE RESUELTOR ─────────────────────────────────────────────────────────
# Flujo real: SARA muestra tickets ordenados por SLA, detalle con alerta si vence,
#             RAG search, resolución con motivo + causa raíz, feedback

def bloque_resueltor(delay: int):
    print(f"\n{'='*65}")
    print("  BLOQUE RESUELTOR  (Carlos Ruiz, user_id=3)")
    print(f"  thread_id: test-{RUN_ID}-r1")
    print(f"{'='*65}")
    tid = f"test-{RUN_ID}-r1"

    # T2.1 — Inicio sesión: tickets ordenados por prioridad SLA
    print("\n  T2.1 — Ver tickets asignados (ordenados por SLA)")
    r = chat(3, "resueltor", "Qué tickets tengo asignados?", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: lista tickets con prioridad SLA", r,
        expect_any=["TCK", "ticket", "asignado", "tienes", "no tienes",
                    "sla", "vence", "pendiente", "urgente", "priorit"],
        forbidden=["paso 1", "campos requeridos:"])

    # T2.2 — Ver detalle del ticket
    print("\n  T2.2 — Detalle del primer ticket")
    r = chat(3, "resueltor", "Muéstrame el detalle completo del TCK-0002.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: detalle con campos clave", r,
        expect_any=["TCK-0002", "urgencia", "descripción", "descripcion",
                    "categoría", "categoria", "estado", "asunto", "dell", "laptop"],
        forbidden=["paso 1", "campos requeridos:"])

    # T2.3 — Buscar solución RAG
    print("\n  T2.3 — Buscar solución conocida en historial")
    r = chat(3, "resueltor", "Hay alguna solución conocida para laptops Dell que no encienden?", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: resultado de búsqueda RAG", r,
        expect_any=["solucion", "solución", "encontr", "historial", "conocida",
                    "similar", "base", "conocimiento", "no hay", "no encontr"],
        forbidden=["paso 1", "campos requeridos:"])

    # T2.4 — Dar solución completa y pedir resolución
    print("\n  T2.4 — Resolver ticket con motivo y causa raíz")
    r = chat(3, "resueltor",
        "Listo, ya resolví el problema. El cable de poder interno estaba suelto. "
        "Resolución: se abrió el equipo y se reconectó el cable de poder del disco duro. "
        "Causa raíz: el cable se soltó por vibración durante el transporte.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: muestra resumen y pide confirmación", r,
        expect_any=["confirmas", "confirmar", "resuelto", "TCK", "cable",
                    "solución", "causa", "raíz", "cerrar"],
        forbidden=["paso 1", "campos requeridos:"])

    # T2.5 — Confirmar resolución
    print("\n  T2.5 — Confirmar resolución")
    r = chat(3, "resueltor", "Sí, confirmo la resolución.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: ticket resuelto + mención de base de conocimiento", r,
        expect_any=["resuelto", "cerrado", "TCK", "notificad", "registrad",
                    "conocimiento", "historial", "solicitante", "listo"],
        forbidden=["paso 1", "campos requeridos:"])

    # T2.6 — Feedback
    print("\n  T2.6 — Feedback del resolutor")
    r = chat(3, "resueltor", "Gracias SARA, muy buena ayuda. Te doy un 5.", tid, delay)
    evaluate("SARA: registra feedback resolutor", r,
        expect_any=["gracias", "satisfacción", "satisfaccion", "calificación",
                    "placer", "encantado", "registrad", "ayud"])


# ─── BLOQUE SUPERVISOR ────────────────────────────────────────────────────────
# Flujo real: dashboard con ACCIÓN REQUERIDA, aprobar ticket pendiente,
#             asignar con sugerencia de carga, estadísticas

def bloque_supervisor(delay: int):
    print(f"\n{'='*65}")
    print("  BLOQUE SUPERVISOR  (Pedro, user_id=5)")
    print(f"  thread_id: test-{RUN_ID}-s1")
    print(f"{'='*65}")
    tid = f"test-{RUN_ID}-s1"

    # T3.1 — Dashboard ejecutivo con ACCIÓN REQUERIDA
    print("\n  T3.1 — Dashboard ejecutivo")
    r = chat(5, "supervisor", "Dame el resumen del estado del sistema.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: dashboard con secciones prioritarias", r,
        expect_any=["acción", "accion", "requerida", "aprobación", "aprobacion",
                    "sla", "ticket", "total", "abierto", "sin asignar", "estado"],
        forbidden=["paso 1", "campos requeridos:"])

    # T3.2 — Tickets sin asignar y críticos
    print("\n  T3.2 — Tickets críticos sin asignar")
    r = chat(5, "supervisor", "Cuáles tickets críticos o urgentes no tienen agente asignado?", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: identifica tickets sin asignar", r,
        expect_any=["sin asignar", "TCK", "ticket", "urgente", "crítico", "critico",
                    "asignar", "no hay", "todos asignados", "riesgo"],
        forbidden=["paso 1", "campos requeridos:"])

    # T3.3 — Asignación con sugerencia de carga
    print("\n  T3.3 — Asignar ticket a Carlos Ruiz")
    r = chat(5, "supervisor", "Asigna el TCK-0002 a Carlos Ruiz, grupo de soporte técnico.", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: confirmar asignación o muestra resumen", r,
        expect_any=["confirmas", "confirmar", "asignad", "TCK-0002", "carlos",
                    "soporte", "grupo", "agente"],
        forbidden=["paso 1", "campos requeridos:"])

    # T3.4 — Verificar estado de la asignación
    print("\n  T3.4 — Verificar que la asignación quedó registrada")
    r = chat(5, "supervisor", "Bien. ¿Puedes confirmarme que el TCK-0002 quedó asignado a Carlos Ruiz?", tid, delay)
    tid = r.get("thread_id", tid)
    evaluate("SARA: asignación confirmada", r,
        expect_any=["asignad", "TCK-0002", "carlos", "listo", "correcto",
                    "notificad", "confirmad", "sí", "registrad", "soporte"],
        forbidden=["paso 1", "campos requeridos:"])

    # T3.5 — Estadísticas con MTTN/MTTR
    print("\n  T3.5 — Estadísticas y métricas")
    r = chat(5, "supervisor",
        "Dame estadísticas de rendimiento: cuántos tickets hay cerrados esta semana "
        "y cuántos están en riesgo de SLA.", tid, delay)
    evaluate("SARA: reporte de estadísticas", r,
        expect_any=["ticket", "TCK", "cerrado", "resuelto", "sla", "riesgo",
                    "total", "vencido", "abierto", "estadístic", "estadistic"])


# ─── Health check ──────────────────────────────────────────────────────────────

def check_health() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            provider = data.get("llm_provider", "desconocido")
            print(f"  Agente: {data}")
            return True
    except Exception as e:
        print(f"  Sin conexión: {e}")
        return False


# ─── Resumen final ─────────────────────────────────────────────────────────────

def print_summary(total_secs: float, roles_run: list) -> int:
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
            print(f"       {detail[:130]}")

    tokens_in  = total_chars_in  // 4
    tokens_out = total_chars_out // 4

    print(f"\n  {len(passed)}/{len(results)} pasaron  |  {len(warned)} advertencias  |  {len(failed)} fallaron")
    print(f"  Roles ejecutados: {', '.join(roles_run)}")
    print(f"  Tiempo total: {total_secs:.1f}s  (~{total_secs/max(len(results),1):.1f}s promedio por turno)")
    print(f"  Tokens estimados: ~{tokens_in + tokens_out:,}  (in: ~{tokens_in:,} | out: ~{tokens_out:,})")
    print(f"  Nota: estimado aproximado (chars/4). El real incluye system prompt + tool schemas.")

    if failed:
        print(f"\n  RESULTADO: FALLO — {len(failed)} turno(s) con error crítico")
    elif warned:
        print(f"\n  RESULTADO: PARCIAL — {len(warned)} turno(s) con respuesta imprecisa")
    else:
        print(f"\n  RESULTADO: EXCELENTE — todos los turnos pasaron")

    print(f"{'='*65}\n")
    return len(failed)


# ─── Main ──────────────────────────────────────────────────────────────────────

ROLES_DISPONIBLES = ["creador", "software", "resueltor", "supervisor", "all"]

def main():
    global verbose, AGENT_URL, HEALTH_URL

    parser = argparse.ArgumentParser(
        description="Tests SARA v2 — calibrados para nuevos prompts con Vercel AI Gateway."
    )
    parser.add_argument(
        "rol",
        choices=ROLES_DISPONIBLES,
        help="Bloque a ejecutar: creador | software | resueltor | supervisor | all"
    )
    parser.add_argument(
        "--port", type=int, default=DEFAULT_PORT, metavar="PORT",
        help=f"Puerto del agente (default: {DEFAULT_PORT})"
    )
    parser.add_argument(
        "--delay", type=int, default=0, metavar="SEG",
        help="Segundos de espera entre turnos. Útil para evitar rate limits. Default: 0."
    )
    parser.add_argument(
        "--verbose", action="store_true",
        help="Muestra la respuesta completa del agente en cada turno."
    )
    args = parser.parse_args()

    verbose    = args.verbose
    AGENT_URL  = f"http://127.0.0.1:{args.port}/agent/chat"
    HEALTH_URL = f"http://127.0.0.1:{args.port}/health"

    print(f"\nVerificando agente en :{args.port}...")
    if not check_health():
        print(f"ERROR: El agente no responde en :{args.port}")
        sys.exit(1)

    print(f"\nRol(es): {args.rol.upper()}  |  Puerto: {args.port}  |  Delay: {args.delay}s  |  RUN_ID: {RUN_ID}")

    start_total = time.monotonic()
    roles_run   = []

    if args.rol in ("creador", "all"):
        bloque_creador(args.delay)
        roles_run.append("creador")

    if args.rol in ("software", "all"):
        bloque_software(args.delay)
        roles_run.append("software")

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
