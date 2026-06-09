#!/usr/bin/env bash
# Quick healthcheck — /health endpoint, container status, FalkorDB ping.
set -euo pipefail
cd "$(dirname "$0")"

echo "[health] docker compose ps:"
docker compose ps

echo
echo "[health] mirofish /health:"
docker compose exec -T mirofish curl -sS -m 5 http://127.0.0.1:3000/health || echo "  /health FAILED"

echo
echo "[health] falkordb ping:"
docker compose exec -T falkordb redis-cli ping || echo "  redis-cli FAILED"

echo
echo "[health] falkordb graph list:"
docker compose exec -T falkordb redis-cli GRAPH.LIST || echo "  GRAPH.LIST FAILED"
