#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# SARA v2 — Backup diario de PostgreSQL + SQLite
#
# Qué backupea:
#   - PostgreSQL: checkpoints de conversaciones + alertas SLA
#   - SQLite:     feedback.db (ratings IA) + checkpoints.db (si se usa sqlite)
#
# Dónde: ./backups/postgres_YYYY-MM-DD_HHMMSS.sql.gz
#
# Configurar cron en el host (ejecutar desde el directorio del proyecto):
#   0 3 * * * cd /ruta/a/agent-v2 && bash scripts/backup.sh >> /var/log/sara-backup.log 2>&1
#
# Requisitos:
#   - Contenedor sara-postgres-prod corriendo
#   - Contenedor sara-agent-prod corriendo (para SQLite via docker cp)
#   - docker sin sudo (usuario en grupo docker)
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

# ── Configuración ────────────────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"
RETENTION_DAYS=7  # Mantener últimos 7 días

# Nombres de contenedores (deben coincidir con docker-compose.prod.yml)
PG_CONTAINER="sara-postgres-prod"
AGENT_CONTAINER="sara-agent-prod"

# Credenciales PostgreSQL (deben coincidir con docker-compose.prod.yml)
PG_USER="${POSTGRES_USER:-helpdesk_agent}"
PG_PASSWORD="${POSTGRES_PASSWORD:-helpdesk2024}"
PG_DB="${POSTGRES_DB:-helpdesk_checkpoints}"

# ── Init ────────────────────────────────────────────────────────────────────
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +%Y-%m-%d_%H%M%S)
FAILED=0

echo "═══════════════════════════════════════════════════════════════"
echo " SARA v2 Backup — $(date '+%Y-%m-%d %H:%M:%S')"
echo "═══════════════════════════════════════════════════════════════"

# ── 1. Backup PostgreSQL ─────────────────────────────────────────────────────
echo ""
echo "[1/3] PostgreSQL (pg_dump)..."

if docker inspect "$PG_CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q true; then
    BACKUP_FILE="$BACKUP_DIR/postgres_${TIMESTAMP}.sql.gz"

    if docker exec -e PGPASSWORD="$PG_PASSWORD" "$PG_CONTAINER" \
        pg_dump -U "$PG_USER" -d "$PG_DB" --clean --if-exists 2>/dev/null \
        | gzip > "$BACKUP_FILE"; then

        SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
        echo "  ✓ PostgreSQL → postgres_${TIMESTAMP}.sql.gz (${SIZE})"
    else
        echo "  ✗ ERROR: pg_dump failed. ¿Contenedor no tiene la DB iniciada?"
        FAILED=1
    fi
else
    echo "  ⚠ WARNING: PostgreSQL container '$PG_CONTAINER' not running. Skipping."
    FAILED=1
fi

# ── 2. Backup SQLite (feedback.db) ──────────────────────────────────────────
echo ""
echo "[2/3] SQLite (feedback.db)..."

if docker exec "$AGENT_CONTAINER" test -f "/app/data/feedback.db" 2>/dev/null; then
    docker cp "$AGENT_CONTAINER:/app/data/feedback.db" "$BACKUP_DIR/feedback_${TIMESTAMP}.db" 2>/dev/null
    echo "  ✓ feedback.db → feedback_${TIMESTAMP}.db"
else
    echo "  ℹ feedback.db not found in container (vacío o no inicializado)"
fi

# ── 3. Backup SQLite (checkpoints.db) ────────────────────────────────────────
echo ""
echo "[3/3] SQLite (checkpoints.db)..."

if docker exec "$AGENT_CONTAINER" test -f "/app/data/checkpoints.db" 2>/dev/null; then
    docker cp "$AGENT_CONTAINER:/app/data/checkpoints.db" "$BACKUP_DIR/checkpoints_${TIMESTAMP}.db" 2>/dev/null
    echo "  ✓ checkpoints.db → checkpoints_${TIMESTAMP}.db"
else
    echo "  ℹ checkpoints.db not found (normal si checkpoint_backend=postgres)"
fi

# ── 4. Rotación — eliminar backups más viejos que RETENTION_DAYS ────────────
echo ""
echo "[Rotación] Limpiando backups de más de ${RETENTION_DAYS} días..."

DELETED_SQL=$(find "$BACKUP_DIR" -name "postgres_*.sql.gz" -mtime +$RETENTION_DAYS -delete -print 2>/dev/null | wc -l)
DELETED_DB=$(find "$BACKUP_DIR" -name "*.db" -mtime +$RETENTION_DAYS -delete -print 2>/dev/null | wc -l)

echo "  Eliminados: ${DELETED_SQL} SQL + ${DELETED_DB} SQLite"

# ── Resumen ────────────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo " Backups en: $BACKUP_DIR"
echo "═══════════════════════════════════════════════════════════════"
ls -lh "$BACKUP_DIR" | tail -10
echo ""

exit $FAILED
