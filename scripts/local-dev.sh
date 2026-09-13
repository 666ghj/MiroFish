#!/usr/bin/env bash
# Run a local command with 1Password references resolved, while allowing
# explicitly injected/hosted environments to bypass a local .env file.
set -euo pipefail

repo_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
env_file=${SWARM_PREDICTION_ENV_FILE:-"$repo_root/.env"}
raw_env=${SWARM_PREDICTION_RAW_ENV:-0}

if (($# == 0)); then
  echo "usage: $0 <command> [args...]" >&2
  exit 64
fi

is_unresolved_reference() {
  [[ "${1#${1%%[![:space:]]*}}" == op://* ]]
}

has_injected_required_environment() {
  local key value
  for key in LLM_API_KEY ZEP_API_KEY; do
    value=${!key-}
    [[ -n "${value//[[:space:]]/}" ]] || return 1
    if is_unresolved_reference "$value"; then
      echo "$key contains an unresolved 1Password reference; run through oprun." >&2
      exit 1
    fi
  done
  return 0
}

# Platforms and CI inject process environment directly. This mode is also a
# deliberate escape hatch for a developer who does not want to read .env.
if [[ "$raw_env" == "1" ]]; then
  exec "$@"
fi

if [[ ! -f "$env_file" ]]; then
  if has_injected_required_environment; then
    exec "$@"
  fi
  echo "No local environment file at $env_file and required injected credentials are absent." >&2
  echo "Set SWARM_PREDICTION_RAW_ENV=1 for a hosted/injected environment, or create .env." >&2
  exit 1
fi

if rg -q '^[[:space:]]*[A-Za-z_][A-Za-z0-9_]*[[:space:]]*=[[:space:]]*op://' "$env_file"; then
  oprun_bin=${OPRUN_BIN:-oprun}
  if ! command -v "$oprun_bin" >/dev/null 2>&1; then
    echo "Found 1Password references in $env_file, but oprun is unavailable. Refusing to pass unresolved references to the app." >&2
    exit 1
  fi
  exec "$oprun_bin" --env-file "$env_file" -- "$@"
fi

# A legacy non-reference local file remains supported while it is migrated.
exec "$@"
