"""
Script de seed para el backend de desarrollo.
Crea usuarios de prueba y tickets de ejemplo.

Uso:
    # Levanta el backend primero en otra terminal:
    #   uvicorn main:app --port 8000 --reload
    python populate_db.py
"""

import requests

BASE = "http://127.0.0.1:8000"
TICKETS_URL = f"{BASE}/api/tickets/"
USERS_URL = f"{BASE}/api/users/"

# ── Usuarios de prueba ────────────────────────────────────────────────────────
# Se insertan directamente en la DB via SQLAlchemy para no necesitar un endpoint POST /users

def seed_users():
    from database import SessionLocal
    import models

    db = SessionLocal()
    try:
        if db.query(models.User).count() > 0:
            print("⏭  Usuarios ya existentes — omitiendo seed de usuarios.")
            return

        users = [
            models.User(name="Ana Torres",      email="ana@helpdesk.dev",    rol="creador"),
            models.User(name="Luis Méndez",      email="luis@helpdesk.dev",   rol="creador"),
            models.User(name="Carlos Ruiz",      email="carlos@helpdesk.dev", rol="resueltor"),
            models.User(name="María González",   email="maria@helpdesk.dev",  rol="resueltor"),
            models.User(name="Pedro Supervisor", email="pedro@helpdesk.dev",  rol="supervisor"),
        ]
        db.add_all(users)
        db.commit()
        print(f"✅ {len(users)} usuarios creados.")
    finally:
        db.close()


# ── Tickets de prueba ─────────────────────────────────────────────────────────

TICKETS = [
    {
        "tipo_requerimiento": "Incidente",
        "categoria": "Red",
        "descripcion": "Sin acceso a internet en contabilidad desde hace 2 horas.",
        "urgencia": "alta",
        "impacto": "alto",
        "prioridad": "urgente",
        "created_by": 1,
    },
    {
        "tipo_requerimiento": "Incidente",
        "categoria": "Hardware",
        "descripcion": "Impresora láser atascada en piso 2, no permite imprimir facturas.",
        "urgencia": "media",
        "impacto": "medio",
        "prioridad": "media",
        "created_by": 2,
    },
    {
        "tipo_requerimiento": "Solicitud",
        "categoria": "Software",
        "descripcion": "Creación de cuenta de usuario para nuevo pasante de RRHH.",
        "urgencia": "baja",
        "impacto": "bajo",
        "prioridad": "baja",
        "created_by": 1,
    },
    {
        "tipo_requerimiento": "Problema",
        "categoria": "Software",
        "descripcion": "Sistema ERP lento en horas pico, afecta a todo el departamento de ventas.",
        "urgencia": "alta",
        "impacto": "alto",
        "prioridad": "urgente",
        "created_by": 2,
    },
    {
        "tipo_requerimiento": "Incidente",
        "categoria": "Seguridad",
        "descripcion": "Usuario reporta correos de phishing recibidos con archivo adjunto.",
        "urgencia": "critica",
        "impacto": "alto",
        "prioridad": "urgente",
        "created_by": 1,
    },
]

# Ticket resuelto para seed del RAG
TICKET_RESUELTO = {
    "tipo_requerimiento": "Incidente",
    "categoria": "Red",
    "descripcion": "VPN sin conexión para usuarios remotos.",
    "urgencia": "alta",
    "impacto": "alto",
    "prioridad": "urgente",
    "created_by": 2,
}
RESOLUCION = (
    "Se reinició el servicio OpenVPN en el servidor principal. "
    "La causa raíz fue un certificado expirado. Se renovó y se configuró alerta de renovación automática."
)


def populate():
    print("\n--- Poblando Tickets ---")
    created_ids = []

    for t in TICKETS:
        r = requests.post(TICKETS_URL, json=t)
        if r.status_code == 200:
            data = r.json()
            print(f"  ✅ {data['name']} — {data['tipo_requerimiento']} / {data['categoria']}")
            created_ids.append(data["id"])
        else:
            print(f"  ❌ Error: {r.text}")

    # Ticket resuelto (para seed del RAG)
    print("\n--- Creando ticket resuelto para RAG ---")
    r = requests.post(TICKETS_URL, json=TICKET_RESUELTO)
    if r.status_code == 200:
        resolved_id = r.json()["id"]
        r2 = requests.put(
            f"{TICKETS_URL}{resolved_id}/resolve",
            json={"resolucion": RESOLUCION},
            headers={"x-user-id": "3", "x-user-rol": "resueltor"},
        )
        if r2.status_code == 200:
            print(f"  ✅ Ticket resuelto TCK-{resolved_id:04d} listo para RAG seed.")
        else:
            print(f"  ❌ Error al resolver: {r2.text}")

    # Verificación final
    print("\n--- Verificación ---")
    r = requests.get(TICKETS_URL)
    total = len(r.json()) if r.status_code == 200 else "?"
    print(f"  Total tickets en DB: {total}")

    r = requests.get(f"{BASE}/api/users/")
    total_users = len(r.json()) if r.status_code == 200 else "?"
    print(f"  Total usuarios en DB: {total_users}")


if __name__ == "__main__":
    seed_users()
    populate()
