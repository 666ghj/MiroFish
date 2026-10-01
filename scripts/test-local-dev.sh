#!/usr/bin/env bash
set -euo pipefail

repo_root=$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
wrapper="$repo_root/scripts/local-dev.sh"
tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT

cat > "$tmpdir/fake-oprun" <<'FAKE'
#!/usr/bin/env bash
set -euo pipefail
printf '%s\n' "$@" > "$OPRUN_ARGS_FILE"
while (($#)); do
  if [[ "$1" == "--" ]]; then
    shift
    export LLM_API_KEY=resolved-llm ZEP_API_KEY=resolved-zep
    exec "$@"
  fi
  shift
done
exit 64
FAKE
chmod +x "$tmpdir/fake-oprun"
printf 'LLM_API_KEY=op://Thrivbe-Core/Example/credential\nZEP_API_KEY=op://Thrivbe-Core/Zep/credential\n' > "$tmpdir/op.env"
OPRUN_ARGS_FILE="$tmpdir/args" OPRUN_BIN="$tmpdir/fake-oprun" SWARM_PREDICTION_ENV_FILE="$tmpdir/op.env" \
  "$wrapper" sh -c 'test "$LLM_API_KEY" = resolved-llm && test "$ZEP_API_KEY" = resolved-zep'
rg -qx -- '--env-file' "$tmpdir/args"
rg -qx -- "$tmpdir/op.env" "$tmpdir/args"
rg -qx -- '--' "$tmpdir/args"

LLM_API_KEY=injected-llm ZEP_API_KEY=injected-zep SWARM_PREDICTION_ENV_FILE="$tmpdir/missing.env" \
  "$wrapper" sh -c 'test "$LLM_API_KEY" = injected-llm && test "$ZEP_API_KEY" = injected-zep'

if LLM_API_KEY='op://Thrivbe-Core/Example/credential' ZEP_API_KEY=injected-zep SWARM_PREDICTION_ENV_FILE="$tmpdir/missing.env" "$wrapper" true 2>"$tmpdir/error"; then
  echo 'expected unresolved injected reference to fail' >&2
  exit 1
fi
rg -q 'unresolved 1Password reference' "$tmpdir/error"

if env -u LLM_API_KEY -u ZEP_API_KEY SWARM_PREDICTION_ENV_FILE="$tmpdir/missing.env" "$wrapper" true 2>"$tmpdir/missing-error"; then
  echo 'expected missing environment to fail' >&2
  exit 1
fi
rg -q 'required injected credentials are absent' "$tmpdir/missing-error"

echo 'local-dev wrapper tests passed'
