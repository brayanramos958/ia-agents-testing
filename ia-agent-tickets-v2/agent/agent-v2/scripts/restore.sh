#!/bin/bash
# ──────────────────────────────────────────────────────────────────────────────
# SARA v2 — Restaurar backup de PostgreSQL
#
# Uso:
#   bash scripts/restore.sh backups/postgres_2024-06-01_030000.sql.gz
#   bash scripts/restore.sh                    ← muestra backups disponibles
#
# ADVERTENCIA: Destruye la base de datos actual y la reemplaza.
#              Requiere confirmación interactiva.
# ──────────────────────────────────────────────────────────────────────────────

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
BACKUP_DIR="$PROJECT_DIR/backups"
BACKUP_FILE="${1:-}"

# Nombres de contenedores (deben coincidir con docker-compose.prod.yml)
PG_CONTAINER="sara-postgres-prod"
AGENT_CONTAINER="sara-agent-prod"

PG_USER="${POSTGRES_USER:-helpdesk_agent}"
PG_PASSWORD="${POSTGRES_PASSWORD:-helpdesk2024}"
PG_DB="${POSTGRES_DB:-helpdesk_checkpoints}"

# ── Sin argumento → mostrar backups disponibles ─────────────────────────────
if [ -z "$BACKUP_FILE" ]; then
    echo "Backups PostgreSQL disponibles:"
    echo ""
    if ls "$BACKUP_DIR"/postgres_*.sql.gz 1>/dev/null 2>&1; then
        ls -1h "$BACKUP_DIR"/postgres_*.sql.gz 2>/dev/null
    else
        echo "  (ninguno en $BACKUP_DIR)"
    fi
    echo ""
    echo "Uso: bash scripts/restore.sh backups/postgres_YYYY-MM-DD_HHMMSS.sql.gz"
    exit 0
fi

# ── Validar archivo ─────────────────────────────────────────────────────────
if [ ! -f "$BACKUP_FILE" ]; then
    echo "ERROR: Archivo no encontrado: $BACKUP_FILE"
    echo ""
    echo "Backups disponibles:"
    ls -1 "$BACKUP_DIR"/postgres_*.sql.gz 2>/dev/null || echo "  (ninguno)"
    exit 1
fi

# ── Verificar que el contenedor postgres esté corriendo ──────────────────────
if ! docker inspect "$PG_CONTAINER" --format '{{.State.Running}}' 2>/dev/null | grep -q true; then
    echo "ERROR: Contenedor PostgreSQL '$PG_CONTAINER' no está corriendo."
    echo "       Arrancalo con: docker compose -f docker-compose.prod.yml up -d postgres"
    exit 1
fi

# ── Confirmación ────────────────────────────────────────────────────────────
echo "═══════════════════════════════════════════════════════════════"
echo " ⚠  RESTAURAR BASE DE DATOS"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "  Backup:     $BACKUP_FILE ($(du -h "$BACKUP_FILE" | cut -f1))"
echo "  Destino:    $PG_DB @ $PG_USER"
echo "  Contenedor: $PG_CONTAINER"
echo ""
echo "  Esto DESTRUIRÁ la base de datos actual y la reemplazará."
echo "  Los checkpoints de conversaciones activas se perderán."
echo ""

read -p "  ¿Estás seguro? Escribí 'yes' para continuar: " confirm
if [ "$confirm" != "yes" ]; then
    echo "  Abortado."
    exit 0
fi

echo ""

# ── 1. Dropear y recrear la base de datos ───────────────────────────────────
echo "[1/3] Dropeando base de datos '$PG_DB'..."
docker exec -e PGPASSWORD="$PG_PASSWORD" "$PG_CONTAINER" \
    psql -U "$PG_USER" -d postgres \
    -c "DROP DATABASE IF EXISTS \"$PG_DB\";" 2>/dev/null

echo "[2/3] Creando base de datos '$PG_DB'..."
docker exec -e PGPASSWORD="$PG_PASSWORD" "$PG_CONTAINER" \
    psql -U "$PG_USER" -d postgres \
    -c "CREATE DATABASE \"$PG_DB\";" 2>/dev/null

# ── 2. Restaurar desde backup ───────────────────────────────────────────────
echo "[3/3] Restaurando desde backup..."
gunzip -c "$BACKUP_FILE" | docker exec -i -e PGPASSWORD="$PG_PASSWORD" "$PG_CONTAINER" \
    psql -U "$PG_USER" -d "$PG_DB" 2>&1 | tail -5

echo ""

# ── 3. Verificar ─────────────────────────────────────────────────────────────
TABLE_COUNT=$(docker exec -e PGPASSWORD="$PG_PASSWORD" "$PG_CONTAINER" \
    psql -U "$PG_USER" -d "$PG_DB" -tAc \
    "SELECT count(*) FROM information_schema.tables WHERE table_schema = 'public';" 2>/dev/null || echo "0")

echo "═══════════════════════════════════════════════════════════════"
echo " ✓ Base de datos restaurada: ${TABLE_COUNT} tablas"
echo ""
echo " Próximo paso: reiniciar el agente para que use la nueva DB"
echo "   docker restart $AGENT_CONTAINER"
echo "═══════════════════════════════════════════════════════════════"
