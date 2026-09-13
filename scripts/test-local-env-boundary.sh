#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
ENV_FILE="$ROOT/.env"
BACKUP="${ENV_FILE}.test-boundary-backup"
FAKE=$(mktemp -d)
cleanup() {
  rm -f "$ENV_FILE"
  if [ -f "$BACKUP" ]; then mv "$BACKUP" "$ENV_FILE"; fi
  rmdir "$FAKE" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
if [ -e "$ENV_FILE" ]; then mv "$ENV_FILE" "$BACKUP"; fi
printf '%s\n' 'LLM_API_KEY=op://Test/LLM/credential' > "$ENV_FILE"
cat > "$FAKE/oprun" <<'SH'
#!/bin/sh
[ "$1" = "--env-file" ] && [ "$2" = "$EXPECTED_ENV_FILE" ] && [ "$3" = "--" ] || exit 97
shift 3
exec "$@"
SH
chmod 755 "$FAKE/oprun"
EXPECTED_ENV_FILE="$ENV_FILE" PATH="$FAKE:$PATH" "$ROOT/scripts/with-local-env.sh" sh -c 'test "$#" -eq 0'
if PATH="/usr/bin:/bin" "$ROOT/scripts/with-local-env.sh" true 2>/dev/null; then
  echo 'wrapper accepted a local .env without oprun' >&2
  exit 1
fi
rm -f "$ENV_FILE"
PATH="/usr/bin:/bin" "$ROOT/scripts/with-local-env.sh" true
