#!/bin/bash
# Development startup: postgres + agent with hot reload.
#
# Linux native:   bash docker-up-dev.sh
# WSL2 (Ubuntu):  sudo bash docker-up-dev.sh
#                 or add user to docker group first: sudo usermod -aG docker $USER && newgrp docker

set -e

cd "$(dirname "$(readlink -f "$0")")"

# Detect host IP for host.docker.internal resolution.
# On Linux native, host-gateway (default in docker-compose.yml) already works.
# This export is only needed on WSL2 where host-gateway resolves to the Docker bridge instead of Windows.
DOCKER_HOST_IP=$(ip route show default | awk '/default/ {print $3}' | head -1)
echo "[dev] Host IP: $DOCKER_HOST_IP"
export DOCKER_HOST_IP

# Ensure Docker daemon is running
if ! docker info >/dev/null 2>&1; then
  echo "[dev] Docker not accessible. Trying to start..."
  sudo systemctl start docker 2>/dev/null \
    || sudo service docker start 2>/dev/null \
    || { echo "[dev] ERROR: Cannot start Docker."; echo "      Run: sudo systemctl start docker"; exit 1; }
  sleep 2
fi

# Start postgres in background, wait for healthy
docker compose -f docker-compose.yml -f docker-compose.dev.yml up -d postgres

echo "[dev] Waiting for postgres..."
until docker inspect helpdesk-postgres --format '{{.State.Health.Status}}' 2>/dev/null | grep -q healthy; do
  sleep 2
done
echo "[dev] Postgres ready."

# Start agent in foreground (Ctrl+C to stop)
echo "[dev] Starting agent with hot reload on port 8001..."
echo "[dev] Code changes reload automatically (~2s delay)"
echo "[dev] First run: HuggingFace model downloads into hf_cache_dev volume (1-2 min)"
echo ""
docker compose -f docker-compose.yml -f docker-compose.dev.yml up agent
