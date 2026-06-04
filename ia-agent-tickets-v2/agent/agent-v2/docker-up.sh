#!/bin/bash
# Production startup: builds the agent image and starts the full stack.
#
# Linux native:   bash docker-up.sh
# WSL2 (Ubuntu):  sudo bash docker-up.sh
#                 or add user to docker group first: sudo usermod -aG docker $USER && newgrp docker

set -e

cd "$(dirname "$(readlink -f "$0")")"

# Detect host IP for host.docker.internal resolution.
# On Linux native, host-gateway (default in docker-compose.yml) already works.
# This export is needed on WSL2 where host-gateway resolves to the Docker bridge instead of the host.
DOCKER_HOST_IP=$(ip route show default | awk '/default/ {print $3}' | head -1)
echo "[docker-up] Host IP: $DOCKER_HOST_IP"
export DOCKER_HOST_IP

# Ensure Docker daemon is running
if ! docker info >/dev/null 2>&1; then
  echo "[docker-up] Docker not accessible. Trying to start..."
  sudo systemctl start docker 2>/dev/null \
    || sudo service docker start 2>/dev/null \
    || { echo "[docker-up] ERROR: Cannot start Docker."; echo "            Run: sudo systemctl start docker"; exit 1; }
  sleep 2
fi

docker compose up -d

echo "[docker-up] Stack started. Logs (last 30 lines):"
sleep 8
docker compose logs --tail=30
