#!/usr/bin/env bash
# MiroFish up — agent.profikid.nl
#
# Builds the image, brings up mirofish + falkordb sidecar on the
# mirofish_net network, registers Traefik routes. Idempotent.
#
# Usage:
#   ./up.sh              # build + up -d
#   ./up.sh --no-build   # up -d, skip build
#   ./up.sh --rebuild    # force rebuild (no cache)
set -euo pipefail

cd "$(dirname "$0")"

BUILD_FLAGS=()
if [ "${1:-}" = "--no-build" ]; then
  BUILD_FLAGS+=(--no-build)
elif [ "${1:-}" = "--rebuild" ]; then
  BUILD_FLAGS+=(--build --force-rm --no-cache --pull)
else
  BUILD_FLAGS+=(--build)
fi

export COMPOSE_PROJECT_NAME=mirofish
export TRAEFIK_HOST=agent.profikid.nl

echo "[up] COMPOSE_PROJECT_NAME=$COMPOSE_PROJECT_NAME"
echo "[up] TRAEFIK_HOST=$TRAEFIK_HOST"
echo "[up] building..."
docker compose "${BUILD_FLAGS[@]}"

echo "[up] bringing up mirofish + falkordb..."
docker compose up -d

echo "[up] tailing logs for ~20s while healthchecks settle..."
docker compose logs --tail=200 --since=2m &
LOG_PID=$!
sleep 20
kill "$LOG_PID" 2>/dev/null || true

echo
echo "[up] status:"
docker compose ps
echo
echo "URL (after Traefik cert):  https://mirofish.agent.profikid.nl"
echo "E2E test:  ./e2e.sh   (runs the in-container e2e test against real FalkorDB)"
