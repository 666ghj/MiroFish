#!/usr/bin/env bash
# MiroFish host bootstrap — agent.profikid.nl
#
# Run this ONCE on the host (after cloning the repo to /docker/mirofish/).
# It creates the project directory layout and verifies Docker + Traefik are
# reachable. Does NOT actually deploy — that's the `up.sh` next to this file.
#
# Usage:  ./bootstrap.sh
set -euo pipefail

cd "$(dirname "$0")"

echo "[bootstrap] creating /docker/mirofish/ if missing..."
sudo mkdir -p /docker/mirofish
sudo chown -R "$USER":"$USER" /docker/mirofish || true

echo "[bootstrap] required files present:"
for f in docker-compose.yml secrets.env Dockerfile Dockerfile.e2e e2e_test.py; do
  if [ ! -f "$f" ] && [ ! -f "../$f" ] && [ ! -f "../deploy/$f" ]; then
    echo "  MISSING: $f" >&2
    exit 1
  fi
  echo "  OK: $f"
done

echo "[bootstrap] checking docker..."
docker --version
docker compose version

echo "[bootstrap] checking traefik network..."
docker network ls --format '{{.Name}}' | grep -q '^traefik$' \
  || { echo "  WARN: 'traefik' network not found. Traefik must be on a network called 'traefik' (or edit docker-compose.yml)." >&2; }

echo "[bootstrap] DNS for agent.profikid.nl (must resolve to 69.62.114.199)..."
RESOLVED=$(getent hosts agent.profikid.nl | awk '{print $1; exit}')
if [ "$RESOLVED" != "69.62.114.199" ]; then
  echo "  WARN: agent.profikid.nl resolves to $RESOLVED, expected 69.62.114.199" >&2
fi

echo
echo "[bootstrap] all checks passed."
echo
echo "Next: edit secrets.env if you need to change LLM keys, then run ./up.sh"
