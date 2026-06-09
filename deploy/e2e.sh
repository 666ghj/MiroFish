#!/usr/bin/env bash
# MiroFish e2e — runs the in-container e2e test against the real FalkorDB
# sidecar. Prints PASS/FAIL and exits accordingly.
set -euo pipefail

cd "$(dirname "$0")"

export COMPOSE_PROJECT_NAME=mirofish

# Make sure the e2e image is built
if ! docker image inspect mirofish-e2e:latest >/dev/null 2>&1; then
  echo "[e2e] building mirofish-e2e image..."
  docker compose --profile e2e build mirofish-e2e
fi

echo "[e2e] running test against falkordb sidecar..."
# `run --rm` creates a one-off container with the e2e profile, runs the test,
# and removes the container on exit. Exit code propagates.
docker compose --profile e2e run --rm mirofish-e2e
RC=$?

echo
if [ "$RC" -eq 0 ]; then
  echo "[e2e] PASS"
else
  echo "[e2e] FAIL (exit $RC)"
fi
exit "$RC"
