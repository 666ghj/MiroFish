#!/bin/sh
# Resolve the repository's local 1Password references before a local entry point.
# Hosted/CI callers without .env keep the raw command path and supply their own env.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="$ROOT/.env"

if [ ! -f "$ENV_FILE" ]; then
  exec "$@"
fi

if ! command -v oprun >/dev/null 2>&1; then
  echo "Local .env requires oprun to resolve 1Password references." >&2
  exit 127
fi

exec oprun --env-file "$ENV_FILE" -- "$@"
