# -*- coding: utf-8 -*-
import sys
sys.stdout.reconfigure(encoding="utf-8")

"""
Prueba concurrente multi-actor del agente.

Simula 5 usuarios reales del sistema trabajando SIMULTANEAMENTE en
conversaciones multi-turno. Usa ThreadPoolExecutor para concurrencia real.

Ejecutar desde agent-v2/:
    py scratch/test_multiactor.py
"""

import time
import json
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Optional

AGENT_URL  = "http://127.0.0.1:8001/agent/chat"
HEALTH_URL = "http://127.0.0.1:8001/health"
HEADERS = {
    "Content-Type": "application/json",
    "X-Agent-Key": "dev-key-change-in-prod",
}
TIMEOUT = 180


# ─── Actores ──────────────────────────────────────────────────────────────────

@dataclass
class Actor:
    name: str
    user_id: int
    rol: str
    turns: list
    thread_id: Optional[str] = None
    results: list = field(default_factory=list)


ACTORS = [
    Actor(
        name="Ana Torres",
        user_id=1,
        rol="creador",
        turns=[
            "Hola, cuales tickets tengo abiertos actualmente?",
            "Mi computadora no enciende desde esta manana, me podrias ayudar a crear un ticket?",
            "Es una Dell Latitude 2022. El problema ocurre al presionar el boton de encendido, no hace nada.",
        ],
    ),
    Actor(
        name="Luis Mendez",
        user_id=2,
        rol="creador",
        turns=[
            "Hola, necesito reportar un problema con el sistema ERP.",
            "El sistema se congela al intentar generar facturas. Pasa en toda el area de ventas.",
            "Existe alguna solucion conocida para este tipo de problema?",
        ],
    ),
    Actor(
        name="Carlos Ruiz",
        user_id=3,
        rol="resueltor",
        turns=[
            "Que tickets tengo asignados hoy?",
            "Dame el detalle del primer ticket que tengo pendiente.",
        ],
    ),
    Actor(
        name="Maria Gonzalez",
        user_id=4,
        rol="resueltor",
        turns=[
            "Hola, cuales son mis tickets asignados?",
            "Hay tickets de alta prioridad que deba atender primero?",
        ],
    ),
    Actor(
        name="Pedro Supervisor",
        user_id=5,
        rol="supervisor",
        turns=[
            "Dame un resumen general del estado de los tickets en el sistema.",
            "Hay tickets criticos sin asignar?",
        ],
    ),
]


# ─── Runner por actor (síncrono, corre en thread separado) ────────────────────

def run_actor(actor: Actor) -> Actor:
    print(f"\n{'='*60}")
    print(f"  ACTOR: {actor.name} [{actor.rol.upper()}]  (user_id={actor.user_id})")
    print(f"{'='*60}")

    for i, message in enumerate(actor.turns, 1):
        preview = message[:80] + ("..." if len(message) > 80 else "")
        print(f"\n  [Turno {i}] {actor.name}: {preview}")

        payload = {
            "user_id": actor.user_id,
            "user_rol": actor.rol,
            "message": message,
            "thread_id": actor.thread_id,
        }

        start = time.monotonic()
        try:
            body = json.dumps(payload).encode("utf-8")
            req  = urllib.request.Request(AGENT_URL, data=body, headers=HEADERS, method="POST")
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                elapsed = time.monotonic() - start
                data    = json.loads(resp.read().decode("utf-8"))
                actor.thread_id = data.get("thread_id", actor.thread_id)
                reply = data.get("reply", "")
                reply_preview = reply[:300].replace("\n", " ")
                print(f"  [{elapsed:.1f}s] {reply_preview}{'...' if len(reply) > 300 else ''}")
                actor.results.append({"ok": True, "reply": reply, "elapsed": elapsed})

        except urllib.error.HTTPError as e:
            elapsed = time.monotonic() - start
            error = f"HTTP {e.code}: {e.read().decode('utf-8')[:200]}"
            print(f"  [ERROR] {error}")
            actor.results.append({"ok": False, "error": error, "elapsed": elapsed})
        except TimeoutError:
            actor.results.append({"ok": False, "error": f"TIMEOUT tras {TIMEOUT}s", "elapsed": TIMEOUT})
            print(f"  [TIMEOUT] No respondio en {TIMEOUT}s")
        except Exception as e:
            elapsed = time.monotonic() - start
            actor.results.append({"ok": False, "error": str(e), "elapsed": elapsed})
            print(f"  [ERROR] {e}")

        time.sleep(0.5)

    return actor


# ─── Orquestador ──────────────────────────────────────────────────────────────

def run_all_concurrent():
    print("\n" + "=" * 60)
    print(f"  TEST MULTI-ACTOR CONCURRENTE")
    print(f"  {len(ACTORS)} actores — {sum(len(a.turns) for a in ACTORS)} turnos en total")
    print("=" * 60)

    start_total = time.monotonic()

    with ThreadPoolExecutor(max_workers=len(ACTORS)) as pool:
        futures = {pool.submit(run_actor, actor): actor for actor in ACTORS}
        completed_actors = []
        for future in as_completed(futures):
            completed_actors.append(future.result())

    total_elapsed = time.monotonic() - start_total

    # ─── Resumen ──────────────────────────────────────────────────────────────
    print("\n\n" + "=" * 60)
    print("  RESUMEN DE RESULTADOS")
    print("=" * 60)

    total_ok = total_fail = 0

    for actor in ACTORS:
        ok_count   = sum(1 for r in actor.results if r["ok"])
        fail_count = sum(1 for r in actor.results if not r["ok"])
        times      = [r["elapsed"] for r in actor.results]
        avg_time   = sum(times) / len(times) if times else 0
        errors     = [r["error"] for r in actor.results if not r["ok"]]
        status     = "OK" if fail_count == 0 else "FALLO"

        print(f"\n  {actor.name} [{actor.rol}]")
        print(f"    Turnos:       {ok_count}/{len(actor.results)} exitosos")
        print(f"    Tiempo prom:  {avg_time:.1f}s por turno")
        print(f"    Thread ID:    {actor.thread_id or 'N/A'}")
        print(f"    Estado:       {status}")
        for e in errors:
            print(f"    Error:        {e}")

        total_ok   += ok_count
        total_fail += fail_count

    total_turns = total_ok + total_fail
    print(f"\n{'-'*60}")
    print(f"  TOTAL: {total_ok}/{total_turns} turnos exitosos  |  {total_fail} fallidos")
    print(f"  Tiempo total:  {total_elapsed:.1f}s")

    print(f"\n{'-'*60}")
    print("  DIAGNOSTICO — Hilo de conversacion")
    print(f"{'-'*60}")
    for actor in ACTORS:
        if len(actor.results) >= 2:
            multi_ok = all(r["ok"] for r in actor.results[1:])
            label = "Hilo mantenido" if multi_ok else "Posible ruptura de hilo"
            print(f"  {actor.name}: {label}  (thread: {actor.thread_id})")

    print(f"\n{'='*60}")
    print("  FIN DEL TEST")
    print(f"{'='*60}\n")

    return total_fail == 0


# ─── Verificacion previa ──────────────────────────────────────────────────────

def check_health() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            print(f"  Agente online: {data}")
            return True
    except Exception as e:
        print(f"  Error de conexion: {e}")
    print(f"  ERROR: El agente no responde en {HEALTH_URL}")
    return False


if __name__ == "__main__":
    print("\nVerificando estado del agente...")
    if not check_health():
        sys.exit(1)
    success = run_all_concurrent()
    sys.exit(0 if success else 1)
