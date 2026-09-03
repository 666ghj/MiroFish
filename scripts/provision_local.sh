#!/usr/bin/env bash
#
# provision_local.sh — bring up SoSim entirely on this machine.
#
# Target: NVIDIA DGX Spark (GB10, aarch64, 128GB unified memory), Ubuntu-based.
# Works on any aarch64/x86_64 Linux box with Docker + an NVIDIA runtime.
#
#   ./scripts/provision_local.sh setup     # deps, submodule, .env, models  (needs network)
#   ./scripts/provision_local.sh start     # bring every service up        (offline)
#   ./scripts/provision_local.sh all       # setup + start
#   ./scripts/provision_local.sh status | logs [svc] | stop | doctor | test
#
# Add -v (or VERBOSE=1) to echo every external command as it runs.
#
# Failures never pass silently: each one is printed as it happens, the offending
# service's log tail is dumped, and every failure is listed again at exit with a
# non-zero status.
#
# Nothing here talks to a hosted API at runtime. `setup` is the only stage that
# needs the internet, and only to download packages and model weights.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# uv and `uv tool install` put binaries here. Export unconditionally: doing it
# only inside install_uv meant that on a second run (uv already present) the
# path was never added, and the `hf` CLI installed later could not be found.
case ":$PATH:" in
  *":$HOME/.local/bin:"*) ;;
  *) export PATH="$HOME/.local/bin:$PATH" ;;
esac

DATA_DIR="$ROOT/data"
RUN_DIR="$DATA_DIR/run"
LOG_DIR="$DATA_DIR/logs"
HF_CACHE="${HF_CACHE_DIR:-$DATA_DIR/hf-cache}"

# --- tunables (override via environment) -------------------------------------

# NGC's vLLM build is the tested path on GB10. Upstream vllm/vllm-openai has
# been reported broken on this chip (its bundled torch compiles only through
# sm_120; GB10 is sm_121) — `doctor` checks for that explicitly.
VLLM_IMAGE="${VLLM_IMAGE:-nvcr.io/nvidia/vllm:26.05.post1-py3}"
# Embeddings run on the SAME vLLM image. HuggingFace TEI was the obvious
# choice but publishes no arm64 image at all — every cpu-* tag is amd64-only
# (checked against the registry), and the arm64 CUDA tag its docs mention does
# not resolve. Reusing the vLLM image means one fewer dependency and a
# guaranteed arm64 build.
EMBED_IMAGE="${EMBED_IMAGE:-$VLLM_IMAGE}"
FALKORDB_IMAGE="${FALKORDB_IMAGE:-falkordb/falkordb:latest}"
FALKORDB_VOLUME="${FALKORDB_VOLUME:-sosim_falkordb}"

# Names this stack used before the product was renamed to SoSim. The containers
# ran with --restart unless-stopped, so they come back after a reboot and keep
# holding the GPU and ports 8000/8081/6379; the sosim-* containers cannot bind
# while they are alive, so retire_legacy_infra removes them before start. The
# volume is only reported, never removed — deleting an operator's disk is not
# this script's call, even when the data in it is already written off.
LEGACY_CONTAINERS=(mirofish-llm mirofish-embed mirofish-falkordb)
LEGACY_VOLUME=mirofish_falkordb

LLM_MODEL_REPO="${LLM_MODEL_REPO:-RedHatAI/Qwen3.6-35B-A3B-NVFP4}"
LLM_SERVED_NAME="${LLM_SERVED_NAME:-local-llm}"
EMBED_MODEL_REPO="${EMBED_MODEL_REPO:-BAAI/bge-m3}"

LLM_PORT="${LLM_PORT:-8000}"
EMBED_PORT="${EMBED_PORT:-8081}"
FALKORDB_PORT="${FALKORDB_PORT:-6379}"
FALKORDB_UI_PORT="${FALKORDB_UI_PORT:-3001}"
SHIM_PORT="${SHIM_PORT:-8088}"
BACKEND_PORT="${BACKEND_PORT:-5001}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

# Fraction of TOTAL device memory. On unified memory this competes with the OS,
# the container runtime and the page cache. Published DGX Spark recipes range
# 0.4–0.87; 0.90 has been observed getting the engine SIGTERM'd by earlyoom,
# which does NOT look like an OOM in the logs. Start conservative.
# NOTE: this is a fraction of TOTAL device memory, and the embeddings server is
# a second vLLM process on the same pool, so the two must sum well under 1.0
# alongside the OS and page cache.
GPU_MEM_UTIL="${GPU_MEM_UTIL:-0.70}"
# bge-m3 is ~2.2GB of weights; it needs very little.
EMBED_GPU_MEM_UTIL="${EMBED_GPU_MEM_UTIL:-0.08}"
EMBED_MAX_MODEL_LEN="${EMBED_MAX_MODEL_LEN:-8192}"
MAX_MODEL_LEN="${MAX_MODEL_LEN:-32768}"
# vLLM will admit this many concurrent sequences. Decode on GB10 is
# bandwidth-bound (~273 GB/s) and divides across sequences, so admitting 32
# does not serve 32 at single-stream speed. Sweep before trusting a number.
MAX_NUM_SEQS="${MAX_NUM_SEQS:-16}"
# Qwen3 family. NVIDIA's playbook uses qwen3_xml for some Qwen3.6 builds;
# if tool calls come back malformed, try that instead.
TOOL_CALL_PARSER="${TOOL_CALL_PARSER:-hermes}"

# How containers are given the GPU. `--gpus all` suits the legacy nvidia
# runtime; hosts wired up through CDI may need `--device nvidia.com/gpu=all`
# instead. Override if the LLM container reports "could not select device
# driver".
GPU_FLAGS="${GPU_FLAGS:---gpus all}"

NODE_MAJOR_REQUIRED=20   # vite 7 needs ^20.19 || >=22.12

# Health-gate patience, in 2-second polls. Raise these on slower storage (a
# first model load reads tens of GB); lower them to fail fast while testing.
EMBED_WAIT_TRIES="${EMBED_WAIT_TRIES:-180}"      # ~6 min
LLM_WAIT_TRIES="${LLM_WAIT_TRIES:-300}"          # ~10 min
SHIM_WAIT_TRIES="${SHIM_WAIT_TRIES:-90}"         # ~3 min
BACKEND_WAIT_TRIES="${BACKEND_WAIT_TRIES:-90}"
FRONTEND_WAIT_TRIES="${FRONTEND_WAIT_TRIES:-90}"

# --- output helpers ----------------------------------------------------------

if [[ -t 1 ]]; then
  R=$'\033[31m'; G=$'\033[32m'; Y=$'\033[33m'; B=$'\033[34m'; D=$'\033[2m'; N=$'\033[0m'
else
  R=; G=; Y=; B=; D=; N=
fi
step() { printf '\n%s==>%s %s\n' "$B" "$N" "$*"; }
ok()   { printf '  %s✓%s %s\n' "$G" "$N" "$*"; }
warn() { printf '  %s!%s %s\n' "$Y" "$N" "$*" >&2; }
die()  { printf '\n%sERROR:%s %s\n' "$R" "$N" "$*" >&2; exit 1; }
note() { printf '    %s%s%s\n' "$D" "$*" "$N"; }

# VERBOSE=1 (or -v / --verbose) echoes every external command before it runs.
VERBOSE="${VERBOSE:-0}"

# Every non-fatal failure is recorded here and reprinted at exit, so a problem
# 200 lines up the scrollback cannot be missed, and the exit code reflects it.
FAILURES=()

fail() {
  FAILURES+=("$*")
  printf '  %s✗ FAILED:%s %s\n' "$R" "$N" "$*" >&2
}

vrun() {
  if [[ "$VERBOSE" == 1 ]]; then
    printf '    %s$ %s%s\n' "$D" "$*" "$N"
  fi
  "$@"
}

have() { command -v "$1" >/dev/null 2>&1; }

# Print the tail of a service's log. This is what turns "it timed out" into
# something actionable without the operator having to go hunting.
dump_log() {
  local name="$1" lines="${2:-60}"
  printf '\n  %s--- last %s lines of %s ---%s\n' "$Y" "$lines" "$name" "$N" >&2
  case "$name" in
    llm|embed|falkordb)
      docker logs --tail "$lines" "sosim-$name" 2>&1 | sed 's/^/  | /' >&2 \
        || printf '  | (no container logs; was it ever created?)\n' >&2
      ;;
    *)
      if [[ -f "$LOG_DIR/$name.log" ]]; then
        tail -n "$lines" "$LOG_DIR/$name.log" | sed 's/^/  | /' >&2
      else
        printf '  | (no log file at data/logs/%s.log)\n' "$name" >&2
      fi
      ;;
  esac
  printf '  %s--- end %s ---%s\n\n' "$Y" "$name" "$N" >&2
}

# A container that dies on startup (bad flag, wrong arch, OOM) otherwise only
# surfaces as a health-check timeout minutes later. Catch it immediately.
assert_container_alive() {
  local name="$1" grace="${2:-4}"
  sleep "$grace"
  if container_up "sosim-$name"; then
    ok "$name container is running"
    return 0
  fi
  local state
  state=$(docker inspect -f '{{.State.Status}} exit={{.State.ExitCode}} {{.State.Error}}' \
          "sosim-$name" 2>/dev/null || echo 'never created')
  fail "$name container is not running ($state)"
  dump_log "$name" 80
  return 1
}

report_failures() {
  if (( ${#FAILURES[@]} == 0 )); then
    return 0
  fi
  printf '\n%s================ %s FAILURE(S) ================%s\n' \
    "$R" "${#FAILURES[@]}" "$N" >&2
  local i=1
  for f in "${FAILURES[@]}"; do
    printf '  %s%s.%s %s\n' "$R" "$i" "$N" "$f" >&2
    i=$((i + 1))
  done
  printf '\n  Inspect a service:  %s logs [llm|embed|falkordb|zep-shim|backend|frontend]\n' "$0" >&2
  printf '  Re-check config:    %s doctor\n\n' "$0" >&2
  return 1
}

# Report the exact line and command on an unexpected abort, and always print the
# failure summary on the way out.
trap 'rc=$?; if (( rc != 0 )); then printf "\n%sABORTED%s line %s: %s (exit %s)\n" "$R" "$N" "$LINENO" "$BASH_COMMAND" "$rc" >&2; fi' ERR
trap 'rc=$?; report_failures || rc=1; exit $rc' EXIT

# Run a command with a hard deadline. Every probe in this script goes through
# this: an unbounded `docker run` probe is what made an earlier version of the
# script appear to hang forever with no output.
run_bounded() {
  local seconds="$1"; shift
  if have timeout; then
    timeout "$seconds" "$@"
    return $?
  fi
  # Fallback for hosts without coreutils timeout.
  "$@" & local pid=$!
  local waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if (( waited >= seconds )); then
      kill -TERM "$pid" 2>/dev/null || true
      return 124
    fi
    sleep 1; waited=$((waited + 1))
  done
  wait "$pid"
}

# Ask the embeddings server for one vector and report its width.
probe_embedding_dim() {
  local body
  body=$(printf '{"model":"%s","input":"dimension probe"}' "$EMBED_MODEL_REPO")
  run_bounded 30 curl -fsS "http://127.0.0.1:$EMBED_PORT/v1/embeddings" \
    -H 'Content-Type: application/json' -d "$body" 2>/dev/null \
    | python3 -c 'import json,sys; print(len(json.load(sys.stdin)["data"][0]["embedding"]))' 2>/dev/null
}

# =============================================================================
# preflight
# =============================================================================

preflight() {
  step "Preflight"

  [[ "$(uname -s)" == "Linux" ]] || warn "Not Linux ($(uname -s)); GPU containers will not work."
  ok "arch: $(uname -m)"

  have docker || die "docker not found. Install Docker Engine, then re-run."
  docker info >/dev/null 2>&1 || die "cannot talk to the Docker daemon (add yourself to the 'docker' group?)."
  ok "docker: $(docker --version | cut -d' ' -f3 | tr -d ,)"

  if have nvidia-smi; then
    ok "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1)"
    # Check the runtime is registered by asking the daemon. Do NOT probe by
    # running a container: `docker run --rm --gpus all <image> true` looks
    # harmless but pulls the image and, for any image with an ENTRYPOINT (e.g.
    # falkordb's run.sh), `true` becomes an argument that the entrypoint
    # ignores — so the container starts its real service and never exits.
    # Report the evidence rather than guessing. Not finding the legacy runtime
    # is NOT conclusive: hosts wired up through CDI expose the GPU without it.
    # The definitive test is the LLM container itself, and if `docker run`
    # cannot get a device it says so and start_llm reports the failure.
    local gpu_evidence=()
    docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia \
      && gpu_evidence+=("docker runtime")
    have nvidia-container-runtime && gpu_evidence+=("nvidia-container-runtime")
    have nvidia-ctk && gpu_evidence+=("nvidia-ctk")
    compgen -G "/etc/cdi/*.yaml" >/dev/null 2>&1 && gpu_evidence+=("CDI /etc/cdi")
    compgen -G "/var/run/cdi/*.yaml" >/dev/null 2>&1 && gpu_evidence+=("CDI /var/run/cdi")
    if (( ${#gpu_evidence[@]} > 0 )); then
      ok "GPU container support: ${gpu_evidence[*]}"
    else
      warn "no nvidia container runtime or CDI spec found. If the LLM container"
      warn "reports 'could not select device driver', install nvidia-container-toolkit"
      warn "or set GPU_FLAGS (e.g. GPU_FLAGS='--device nvidia.com/gpu=all')."
    fi
    note "containers will request the GPU with: $GPU_FLAGS"
  else
    warn "nvidia-smi not found. The LLM container needs a working NVIDIA container runtime."
  fi

  # -Pk is POSIX and works on both GNU and BSD df; --output=avail is GNU-only.
  local free_gb
  free_gb=$(df -Pk "$ROOT" 2>/dev/null | awk 'NR==2 {printf "%d", $4/1048576}')
  if [[ -n "$free_gb" && "$free_gb" -lt 120 ]]; then
    warn "only ${free_gb}GB free here. Model weights alone run 25–65GB; 120GB+ recommended."
  else
    ok "disk: ${free_gb}GB free"
  fi
}

# =============================================================================
# setup
# =============================================================================

install_system_deps() {
  step "System packages"
  if ! have apt-get; then
    warn "no apt-get; install the equivalents of: build-essential python3-dev git curl fonts-inter"
    return
  fi
  # build-essential + python3-dev are NOT optional: psutil is pinned to 5.9.8,
  # which publishes no linux-aarch64 wheel, so uv builds it from source. It is
  # the only package in the lockfile that does.
  # The UI ships no webfont (an air-gapped box cannot fetch one), so the font
  # stack falls back to whatever is installed. fonts-inter and
  # fonts-jetbrains-mono are what the design tokens ask for.
  local pkgs=(build-essential python3-dev git curl ca-certificates
              fonts-inter fonts-jetbrains-mono)
  local missing=()
  for p in "${pkgs[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then ok "all present"; return; fi
  note "installing: ${missing[*]}"
  note "this needs sudo — enter your password if prompted"
  vrun sudo apt-get update -qq || fail "apt-get update failed"
  vrun sudo apt-get install -y "${missing[@]}" \
    || fail "apt-get install failed for: ${missing[*]}"
  ok "installed"
}

install_uv() {
  step "uv"
  if have uv; then ok "uv $(uv --version | cut -d' ' -f2)"; return 0; fi
  curl -fsSL https://astral.sh/uv/install.sh | sh
  hash -r 2>/dev/null || true
  have uv || die "uv install failed; add \$HOME/.local/bin to PATH and re-run."
  ok "installed uv"
}

install_node() {
  step "Node.js"
  local major=0 current="not installed"
  if have node; then
    current=$(node -v)
    major=$(node -v | sed 's/^v\([0-9]*\).*/\1/')
  fi
  if (( major >= NODE_MAJOR_REQUIRED )); then ok "node $current"; return 0; fi
  warn "node: $current (need >= $NODE_MAJOR_REQUIRED)"

  # The repo's package.json claims node>=18, but the pinned vite@7 and
  # @vitejs/plugin-vue@6 both require ^20.19 || >=22.12. npm ci only warns
  # about the mismatch, so an 18.x box installs cleanly and then misbehaves.
  warn "node ${major:-none} is too old (vite 7 needs >= $NODE_MAJOR_REQUIRED). Installing Node 22 LTS."
  if have apt-get; then
    note "this needs sudo — enter your password if prompted"
    curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash -
    sudo apt-get install -y nodejs
  else
    die "install Node 22 LTS manually, then re-run."
  fi
  ok "node $(node -v)"
}

init_submodule() {
  step "Graphiti submodule"
  # Checks out the commit this repo records — which is what we want, and is
  # already the default. Do NOT add --remote: that advances the submodule to the
  # tip of its branch, silently moving off the pinned commit. (An earlier
  # version wrote `--remote=false` trying to be explicit; --remote is a boolean
  # flag with no value, so git rejected the entire command with a usage error.)
  if ! vrun git submodule update --init --recursive; then
    fail "git submodule update failed — check SSH access to the graphiti fork"
    return 1
  fi
  if [[ ! -f "$ROOT/third_party/graphiti/server/graph_service/zep_compat/router.py" ]]; then
    fail "submodule is present but has no zep_compat layer; third_party/graphiti is on the wrong commit"
    note "expected the commit recorded by this repo: $(git ls-tree HEAD third_party/graphiti | awk '{print substr($3,1,12)}')"
    note "got: $(git -C third_party/graphiti rev-parse --short=12 HEAD 2>/dev/null || echo '<none>')"
    return 1
  fi
  ok "graphiti @ $(git -C third_party/graphiti rev-parse --short HEAD)"
}

make_env() {
  step "Environment file"
  mkdir -p "$DATA_DIR" "$RUN_DIR" "$LOG_DIR" "$HF_CACHE"
  if [[ -f "$ROOT/.env" ]]; then
    ok ".env exists (left untouched)"
  else
    cp "$ROOT/.env.example" "$ROOT/.env"
    ok "created .env from .env.example"
  fi
  # Keep the served model name in .env consistent with what vLLM will answer to.
  if ! grep -q "^LLM_MODEL_NAME=$LLM_SERVED_NAME$" "$ROOT/.env" 2>/dev/null; then
    note "check LLM_MODEL_NAME in .env matches LLM_SERVED_NAME ($LLM_SERVED_NAME)"
  fi

  # Couple the simulation's concurrency to what this vLLM will actually run at
  # once. Both platforms run together, so the endpoint sees twice the
  # per-platform cap; half of --max-num-seqs keeps the running batch full with
  # no standing queue. Left uncoupled, the client default (30 per platform, 60
  # total) floods a 16-slot server and every request times out waiting in line.
  local want_semaphore=$(( MAX_NUM_SEQS / 2 ))
  (( want_semaphore >= 1 )) || want_semaphore=1
  ensure_env_key SIM_LLM_SEMAPHORE "$want_semaphore" \
    "half of vLLM --max-num-seqs=$MAX_NUM_SEQS, and both platforms run at once"
  ensure_env_key SIM_MODEL_TIMEOUT 300 \
    "a queued request's wait counts against this"
  ensure_env_key SIM_MODEL_MAX_RETRIES 1 \
    "a retry re-enters the same queue, so retries multiply load"
}

# ensure_env_key <key> <value> [why]
# Add the key with this value when .env does not set it at all. An existing
# value is never overwritten — it may have been tuned deliberately — but a
# disagreement is reported, because a silent mismatch here is what makes a
# simulation die on timeouts.
ensure_env_key() {
  local key="$1" value="$2" why="${3:-}" current
  if grep -qE "^${key}=" "$ROOT/.env" 2>/dev/null; then
    current=$(grep -E "^${key}=" "$ROOT/.env" | head -1 | cut -d= -f2-)
    if [[ "$current" != "$value" ]]; then
      note "$key=$current in .env (this host suggests $value)"
    fi
    return 0
  fi
  {
    printf '\n# Added by provision_local.sh'
    [[ -n "$why" ]] && printf ' — %s' "$why"
    printf '\n%s=%s\n' "$key" "$value"
  } >> "$ROOT/.env"
  ok "set $key=$value in .env"
}

install_python_deps() {
  step "Python dependencies"
  note "backend (this compiles psutil from source on aarch64; be patient)"
  if ( cd "$ROOT/backend" && vrun uv sync --frozen ); then
    ok "backend"
  else
    fail "backend dependency install failed (uv sync --frozen in backend/)"
  fi
  note "zep-compat shim"
  if ( cd "$ROOT/third_party/graphiti/server" && vrun uv sync --extra dev ); then
    ok "shim"
  else
    fail "shim dependency install failed (uv sync --extra dev in third_party/graphiti/server/)"
  fi
}

install_node_deps() {
  step "Frontend dependencies"
  note "npm ci for the root workspace, then the frontend (a few minutes)"
  vrun npm ci --no-audit --no-fund || fail "npm ci failed in the repo root"
  vrun npm ci --prefix frontend --no-audit --no-fund || fail "npm ci failed in frontend/"
  [[ -d "$ROOT/frontend/node_modules" ]] || fail "frontend/node_modules is missing after npm ci"
  ok "installed"
}

fetch_models() {
  step "Model weights  (the only stage that needs the internet)"
  export HF_HOME="$HF_CACHE"
  local hf_bin=""
  if have hf; then hf_bin=hf
  elif have huggingface-cli; then hf_bin=huggingface-cli
  else
    note "installing the huggingface_hub CLI"
    uv tool install -q "huggingface_hub[cli]" \
      || pip install -q --user "huggingface_hub[cli]" \
      || fail "could not install the huggingface_hub CLI"
    hash -r 2>/dev/null || true
    if have hf; then
      hf_bin=hf
    elif have huggingface-cli; then
      hf_bin=huggingface-cli
    else
      fail "no hf/huggingface-cli on PATH after install; model weights not downloaded"
      return 1
    fi
  fi
  note "using: $hf_bin"

  for repo in "$LLM_MODEL_REPO" "$EMBED_MODEL_REPO"; do
    note "downloading $repo"
    HF_HUB_OFFLINE=0 vrun "$hf_bin" download "$repo" \
      || fail "failed to download model weights: $repo"
  done

  # A Twitter simulation loads this at runtime; a Reddit-only run never does.
  # Fetch it now or the first Twitter run fails with HF_HUB_OFFLINE=1 set.
  note "downloading Twitter/twhin-bert-base (OASIS Twitter recommender, ~1GB)"
  HF_HUB_OFFLINE=0 vrun "$hf_bin" download Twitter/twhin-bert-base || \
    warn "twhin-bert-base not cached — Twitter simulations will fail offline (Reddit is fine)"

  if grep -q '^GRAPHITI_RERANKER=bge' "$ROOT/.env" 2>/dev/null; then
    note "downloading BAAI/bge-reranker-v2-m3 (GRAPHITI_RERANKER=bge)"
    HF_HUB_OFFLINE=0 "$hf_bin" download BAAI/bge-reranker-v2-m3 || warn "reranker not cached"
  fi
  ok "models cached under $HF_CACHE"
}

pull_images() {
  step "Container images"
  note "the vLLM image is several GB; progress is shown so a long pull is not"
  note "mistaken for a hang"
  for image in $(printf '%s\n' "$FALKORDB_IMAGE" "$VLLM_IMAGE" "$EMBED_IMAGE" | sort -u); do
    printf '\n  --- %s\n' "$image"
    if docker image inspect "$image" >/dev/null 2>&1; then
      ok "already present"
      continue
    fi
    vrun docker pull "$image" || fail "could not pull $image"
  done
  ok "done"
}

# =============================================================================
# service control
# =============================================================================

# shellcheck disable=SC1090
load_env() {
  [[ -f "$ROOT/.env" ]] || die ".env missing. Run: $0 setup"
  set -a
  source "$ROOT/.env"
  set +a
  export HF_HOME="${HF_HOME:-$HF_CACHE}"
}

# Wait for an HTTP endpoint. On failure the caller gets a dumped log, so a
# timeout always comes with a reason attached.
wait_for_http() {
  local url="$1" name="$2" tries="${3:-120}" logname="${4:-}"
  printf '    waiting for %s (%s, up to %ss) ' "$name" "$url" "$((tries * 2))"
  for _ in $(seq "$tries"); do
    # Quiet while polling: -S would print a connection error on every attempt
    # and bury the progress dots. The real error is reported once, below.
    if curl -fsS -o /dev/null --max-time 2 "$url" 2>/dev/null; then
      printf ' %sup%s\n' "$G" "$N"
      return 0
    fi
    printf '.'; sleep 2
  done
  printf ' %sTIMEOUT%s\n' "$R" "$N"
  local last_error
  last_error=$(curl -sS -o /dev/null --max-time 2 "$url" 2>&1 || true)
  [[ -n "$last_error" ]] && note "curl says: $last_error"
  fail "$name did not become healthy at $url within $((tries * 2))s"
  [[ -n "$logname" ]] && dump_log "$logname" 80
  return 1
}

container_up() { [[ -n "$(docker ps -q -f "name=^$1$" 2>/dev/null)" ]]; }
container_exists() { [[ -n "$(docker ps -aq -f "name=^$1$" 2>/dev/null)" ]]; }
volume_exists() { docker volume inspect "$1" >/dev/null 2>&1; }

# The containers and the FalkorDB volume were renamed mirofish-* -> sosim-* with
# no data migration. Two consequences, and both are handled here rather than
# left for the operator to discover:
#
#   1. The old containers must go, or the new ones cannot bind their ports. They
#      are removed, not stopped: --restart unless-stopped would revive a stopped
#      one on the next boot.
#   2. The old volume is now unreferenced and every graph in it is unreachable.
#      That is by design, but it is not something to discover from a mysteriously
#      empty graph list, so it is stated plainly and the reclaim command printed.
#
# Idempotent: a machine that never ran the old names sees a single "none found".
retire_legacy_infra() {
  step "Pre-rename containers and volume"

  local stale=()
  local c
  for c in "${LEGACY_CONTAINERS[@]}"; do
    container_exists "$c" && stale+=("$c")
  done

  if (( ${#stale[@]} == 0 )); then
    ok "none found"
  else
    note "these predate the SoSim rename and hold ports $LLM_PORT, $EMBED_PORT and $FALKORDB_PORT"
    for c in "${stale[@]}"; do
      if vrun docker rm -f "$c" >/dev/null 2>&1; then
        ok "removed $c"
      else
        fail "could not remove the pre-rename container $c; sosim-${c#mirofish-} cannot bind its port while it exists"
      fi
    done
  fi

  if volume_exists "$LEGACY_VOLUME"; then
    warn "the pre-rename volume '$LEGACY_VOLUME' is now orphaned."
    warn "FalkorDB starts on '$FALKORDB_VOLUME', which is empty, so EVERY graph built"
    warn "before the rename is gone. That is deliberate: there is no data migration."
    warn "Nothing reads '$LEGACY_VOLUME' again. To reclaim the disk it holds, run:"
    warn "    docker volume rm $LEGACY_VOLUME"
  fi
}

start_falkordb() {
  step "FalkorDB"
  if container_up sosim-falkordb; then ok "already running"; return 0; fi
  docker rm -f sosim-falkordb >/dev/null 2>&1 || true
  if ! vrun docker run -d --name sosim-falkordb --restart unless-stopped \
    -p "127.0.0.1:$FALKORDB_PORT:6379" -p "127.0.0.1:$FALKORDB_UI_PORT:3000" \
    -v "$FALKORDB_VOLUME:/var/lib/falkordb/data" \
    -e BROWSER=1 \
    "$FALKORDB_IMAGE" >/dev/null; then
    fail "could not create the FalkorDB container"
    return 1
  fi
  note "started on 127.0.0.1:$FALKORDB_PORT"
  assert_container_alive falkordb 3
}

start_llm() {
  step "LLM server (vLLM)"
  if container_up sosim-llm; then ok "already running"; return; fi
  docker rm -f sosim-llm >/dev/null 2>&1 || true

  # Unified memory means the OS page cache eats into the KV cache budget.
  note "dropping the page cache to free unified memory (sudo; skipped if refused)"
  sync
  run_bounded 20 sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || \
    note "page cache not dropped (needs passwordless sudo); fine, just less headroom"

  # Two independent needs, both served by this one endpoint:
  #  - OASIS agents use native OpenAI tool calling  -> the tool-call flags
  #  - Graphiti uses response_format json_schema    -> constrained decoding
  note "model=$LLM_MODEL_REPO  gpu-mem=$GPU_MEM_UTIL  max-len=$MAX_MODEL_LEN"
  note "max-num-seqs=$MAX_NUM_SEQS  tool-call-parser=$TOOL_CALL_PARSER"
  if ! vrun docker run -d --name sosim-llm --restart unless-stopped \
    $GPU_FLAGS --ipc=host \
    -p "127.0.0.1:$LLM_PORT:8000" \
    -v "$HF_CACHE:/hf" \
    -e HF_HOME=/hf -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
    -e HF_HUB_DISABLE_TELEMETRY=1 \
    "$VLLM_IMAGE" \
    vllm serve "$LLM_MODEL_REPO" \
      --served-model-name "$LLM_SERVED_NAME" \
      --host 0.0.0.0 --port 8000 \
      --gpu-memory-utilization "$GPU_MEM_UTIL" \
      --max-model-len "$MAX_MODEL_LEN" \
      --max-num-seqs "$MAX_NUM_SEQS" \
      --enable-auto-tool-choice \
      --tool-call-parser "$TOOL_CALL_PARSER" >/dev/null; then
    fail "could not create the vLLM container"
    return 1
  fi
  note "starting (first load can take several minutes)"
  # 12s: long enough for an immediate flag/arch rejection to show up.
  assert_container_alive llm 12
}

start_embeddings() {
  step "Embeddings server"
  if container_up sosim-embed; then ok "already running"; return; fi
  docker rm -f sosim-embed >/dev/null 2>&1 || true
  # vLLM in pooling mode exposes an OpenAI-compatible /v1/embeddings.
  # `--runner pooling` supersedes the older `--task embed`; copying an older
  # recipe with --task embed will fail on a current image.
  note "model=$EMBED_MODEL_REPO  gpu-mem=$EMBED_GPU_MEM_UTIL"
  if ! vrun docker run -d --name sosim-embed --restart unless-stopped \
    $GPU_FLAGS --ipc=host \
    -p "127.0.0.1:$EMBED_PORT:8000" \
    -v "$HF_CACHE:/hf" \
    -e HF_HOME=/hf -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
    -e HF_HUB_DISABLE_TELEMETRY=1 \
    "$EMBED_IMAGE" \
    vllm serve "$EMBED_MODEL_REPO" \
      --runner pooling \
      --host 0.0.0.0 --port 8000 \
      --gpu-memory-utilization "$EMBED_GPU_MEM_UTIL" \
      --max-model-len "$EMBED_MAX_MODEL_LEN" >/dev/null; then
    fail "could not create the embeddings container"
    return 1
  fi
  note "starting on 127.0.0.1:$EMBED_PORT (model id: $EMBED_MODEL_REPO)"
  assert_container_alive embed 12
}

pidfile() { echo "$RUN_DIR/$1.pid"; }

# start_bg <name> <cwd> <command...>
# The cwd is an argument rather than the caller using ( cd X && start_bg ... ):
# a subshell would discard everything fail() appends to FAILURES, and swallow
# the return code too.
start_bg() {
  local name="$1" cwd="$2"; shift 2
  local pf; pf="$(pidfile "$name")"
  if [[ -f "$pf" ]] && kill -0 "$(cat "$pf")" 2>/dev/null; then
    ok "$name already running (pid $(cat "$pf"))"
    return
  fi
  mkdir -p "$RUN_DIR" "$LOG_DIR"
  # setsid so the child gets its own process group: SoSim's simulation
  # runner spawns OASIS children with start_new_session=True and cleans them
  # up via killpg on SIGTERM. A hard kill of the parent orphans that whole
  # group, which keeps holding the sqlite DB and burning LLM capacity.
  if [[ "$VERBOSE" == 1 ]]; then
    printf '    %s$ %s%s\n' "$D" "$*" "$N"
  fi
  printf '=== started %s at %s in %s: %s\n' \
    "$name" "$(date -u +%FT%TZ)" "$cwd" "$*" >>"$LOG_DIR/$name.log"
  # setsid gives the child its own process group so do_stop can signal the
  # whole tree (see the killpg note above). Not every host ships it (macOS does
  # not), so branch rather than expanding a possibly-empty array — that trips
  # `set -u` on bash 3.2.
  if have setsid; then
    ( cd "$cwd" && exec setsid "$@" ) >>"$LOG_DIR/$name.log" 2>&1 &
  else
    warn "setsid not found; $name will not get its own process group"
    ( cd "$cwd" && exec "$@" ) >>"$LOG_DIR/$name.log" 2>&1 &
  fi
  local pid=$!
  echo "$pid" >"$pf"
  # A process that exits immediately (bad interpreter, import error, port in
  # use) would otherwise only show up as a health-check timeout.
  sleep 2
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pf"
    fail "$name exited immediately after launch"
    dump_log "$name" 80
    return 1
  fi
  ok "$name started (pid $pid), logging to data/logs/$name.log"
}

start_shim() {
  step "Zep-compatible shim (Graphiti-backed)"
  local venv="$ROOT/third_party/graphiti/server/.venv/bin/python"
  if [[ ! -x "$venv" ]]; then
    fail "shim venv missing at $venv — run: $0 setup"
    return 1
  fi
  export ZEP_COMPAT_DB_PATH="${ZEP_COMPAT_DB_PATH:-$DATA_DIR/zep_compat.sqlite3}"
  note "sqlite state: $ZEP_COMPAT_DB_PATH"
  start_bg zep-shim "$ROOT/third_party/graphiti/server" \
    "$venv" -m uvicorn graph_service.zep_compat.app:app \
    --host 127.0.0.1 --port "$SHIM_PORT"
}

start_backend() {
  step "SoSim backend"
  # Must be the venv interpreter: simulation_runner spawns children with
  # sys.executable, so a system python here means every simulation child dies
  # on `import oasis`.
  local venv="$ROOT/backend/.venv/bin/python"
  if [[ ! -x "$venv" ]]; then
    fail "backend venv missing at $venv — run: $0 setup"
    return 1
  fi
  start_bg backend "$ROOT/backend" "$venv" run.py
}

start_frontend() {
  step "Frontend"
  start_bg frontend "$ROOT/frontend" npm run dev -- --port "$FRONTEND_PORT"
}

do_start() {
  load_env
  # Must run before anything binds a port: the pre-rename containers are still
  # holding 8000, 8081 and 6379 on any machine that ran this stack before.
  retire_legacy_infra || true
  # Each step records its own failures and we deliberately continue, so one
  # broken service still yields a full picture instead of stopping at the first
  # problem. report_failures() (EXIT trap) sets the exit code.
  start_falkordb        || true
  start_embeddings      || true
  start_llm             || true

  wait_for_http "http://127.0.0.1:$EMBED_PORT/v1/models" "embeddings" \
    "$EMBED_WAIT_TRIES" embed || true
  wait_for_http "http://127.0.0.1:$LLM_PORT/v1/models" "LLM" \
    "$LLM_WAIT_TRIES" llm || true

  start_shim || true
  wait_for_http "http://127.0.0.1:$SHIM_PORT/healthcheck" "shim" \
    "$SHIM_WAIT_TRIES" zep-shim || true

  start_backend || true
  wait_for_http "http://127.0.0.1:$BACKEND_PORT/health" "backend" \
    "$BACKEND_WAIT_TRIES" backend || true

  start_frontend || true
  wait_for_http "http://127.0.0.1:$FRONTEND_PORT" "frontend" \
    "$FRONTEND_WAIT_TRIES" frontend || true

  if (( ${#FAILURES[@]} == 0 )); then
    summary
  else
    step "Started with errors"
    warn "the stack is NOT fully up; see the failure list below"
    do_status
  fi
}

do_stop() {
  step "Stopping"
  for name in frontend backend zep-shim; do
    local pf; pf="$(pidfile "$name")"
    if [[ -f "$pf" ]]; then
      local pid; pid="$(cat "$pf")"
      # Negative PID = whole process group, so OASIS children go too.
      kill -TERM "-$pid" 2>/dev/null || kill -TERM "$pid" 2>/dev/null || true
      for _ in $(seq 20); do kill -0 "$pid" 2>/dev/null || break; sleep 0.5; done
      kill -KILL "-$pid" 2>/dev/null || true
      rm -f "$pf"
      ok "$name stopped"
    fi
  done
  for c in sosim-llm sosim-embed sosim-falkordb; do
    docker stop "$c" >/dev/null 2>&1 && ok "$c stopped" || true
  done
}

do_status() {
  step "Status"
  printf '  %-12s %-9s %s\n' SERVICE STATE ENDPOINT
  for row in "falkordb:sosim-falkordb:127.0.0.1:$FALKORDB_PORT" \
             "embeddings:sosim-embed:http://127.0.0.1:$EMBED_PORT/v1/models" \
             "llm:sosim-llm:http://127.0.0.1:$LLM_PORT/v1/models"; do
    IFS=: read -r label container rest <<<"$row"
    local endpoint="${row#"$label:$container:"}"
    if container_up "$container"; then
      printf '  %-12s %s%-9s%s %s\n' "$label" "$G" running "$N" "$endpoint"
    else
      printf '  %-12s %s%-9s%s %s\n' "$label" "$R" down "$N" "$endpoint"
    fi
  done
  for row in "zep-shim:http://127.0.0.1:$SHIM_PORT/healthcheck" \
             "backend:http://127.0.0.1:$BACKEND_PORT/health" \
             "frontend:http://127.0.0.1:$FRONTEND_PORT"; do
    IFS=: read -r label _ <<<"$row"
    local endpoint="${row#"$label:"}"
    local pf; pf="$(pidfile "$label")"
    if [[ -f "$pf" ]] && kill -0 "$(cat "$pf")" 2>/dev/null; then
      printf '  %-12s %s%-9s%s %s\n' "$label" "$G" running "$N" "$endpoint"
    else
      printf '  %-12s %s%-9s%s %s\n' "$label" "$R" down "$N" "$endpoint"
    fi
  done
}

do_logs() {
  local svc="${1:-}"
  case "$svc" in
    llm)        docker logs -f --tail 200 sosim-llm ;;
    embed*)     docker logs -f --tail 200 sosim-embed ;;
    emb)        docker logs -f --tail 200 sosim-embed ;;
    falkor*)    docker logs -f --tail 200 sosim-falkordb ;;
    ''|all)     tail -n 100 -f "$LOG_DIR"/*.log ;;
    *)          tail -n 200 -f "$LOG_DIR/$svc.log" ;;
  esac
}

do_test() {
  step "Test suites (no GPU, no network, no database)"
  local suite
  for suite in "backend:$ROOT/backend" "shim:$ROOT/third_party/graphiti/server"; do
    local label="${suite%%:*}" dir="${suite#*:}"
    if [[ ! -x "$dir/.venv/bin/python" ]]; then
      fail "$label venv missing at $dir/.venv — run: $0 setup"
      continue
    fi
    printf '\n  --- %s\n' "$label"
    if ( cd "$dir" && vrun .venv/bin/python -m pytest tests/ -q ); then
      ok "$label suite passed"
    else
      fail "$label test suite failed (see the pytest output above)"
    fi
  done
}

check_gpu_arch() {
  step "GPU architecture support in $VLLM_IMAGE"
  # GB10 is sm_121. A torch that only compiles through sm_120 fails at runtime
  # with errors that do not mention the architecture at all.
  local arches
  if ! docker image inspect "$VLLM_IMAGE" >/dev/null 2>&1; then
    warn "$VLLM_IMAGE not pulled yet; run '$0 setup' first to check this"
    return 0
  fi
  # Bounded, and only against an image already on disk — see run_bounded.
  if arches=$(run_bounded 180 docker run --rm $GPU_FLAGS "$VLLM_IMAGE" \
      python -c 'import torch; print(" ".join(torch.cuda.get_arch_list()))' 2>/dev/null); then
    note "torch arch list: $arches"
    if [[ "$arches" == *sm_121* || "$arches" == *sm_121a* ]]; then
      ok "sm_121 present"
    else
      warn "sm_121 NOT in the arch list — this image may fail on GB10. Try another tag."
    fi
  else
    warn "could not run the image with GPU access ($GPU_FLAGS)."
    warn "This doubles as the GPU passthrough test. If the LLM container also"
    warn "fails, try: GPU_FLAGS='--device nvidia.com/gpu=all' $0 start"
  fi
}

# Read-only counterpart to retire_legacy_infra: doctor reports, start removes.
report_legacy_infra() {
  step "Pre-rename leftovers"
  local found=0 c
  for c in "${LEGACY_CONTAINERS[@]}"; do
    if container_exists "$c"; then
      warn "$c still exists and blocks the matching sosim-* container; '$0 start' removes it"
      found=1
    fi
  done
  if volume_exists "$LEGACY_VOLUME"; then
    warn "volume '$LEGACY_VOLUME' is orphaned; its graphs are gone by design."
    warn "Reclaim the disk with:  docker volume rm $LEGACY_VOLUME"
    found=1
  fi
  (( found == 0 )) && ok "nothing left from the pre-rename names"
  return 0
}

do_doctor() {
  step "Doctor"
  preflight
  report_legacy_infra
  check_gpu_arch

  step "arm64 manifests"
  for image in $(printf '%s\n' "$FALKORDB_IMAGE" "$VLLM_IMAGE" "$EMBED_IMAGE" | sort -u); do
    local manifest
    manifest=$(run_bounded 60 docker manifest inspect "$image" 2>&1) || manifest=""
    if [[ -z "$manifest" || "$manifest" == *"manifest unknown"* || "$manifest" == *"no such manifest"* ]]; then
      warn "$image: manifest not found — that tag probably does not exist"
    elif grep -q '"architecture": *"arm64"' <<<"$manifest"; then
      ok "$image has an arm64 build"
    elif ! grep -q '"manifests"' <<<"$manifest"; then
      ok "$image is a single-arch image (assuming it matches this host)"
    else
      warn "$image has NO arm64 build. It will not run on this host."
      warn "  architectures offered: $(grep -o '"architecture": *"[a-z0-9]*"' <<<"$manifest" \
            | grep -v unknown | sed 's/.*"\([a-z0-9]*\)"$/\1/' | sort -u | tr '\n' ' ')"
    fi
  done

  step "Embedding dimension"
  # EMBEDDING_DIM is a one-way door: the vector index is created with it, so a
  # mismatch means re-embedding every graph later. And Graphiti TRUNCATES longer
  # vectors silently rather than erroring. Check it live while that is cheap.
  local dim
  dim=$(probe_embedding_dim) || dim=""
  if [[ -z "$dim" ]]; then
    note "embeddings server not reachable; start the stack and re-run doctor"
  elif [[ "$dim" == "${EMBEDDING_DIM:-1024}" ]]; then
    ok "server returns $dim dims, matching EMBEDDING_DIM"
  else
    warn "server returns $dim dims but EMBEDDING_DIM=${EMBEDDING_DIM:-1024}."
    warn "Fix this BEFORE ingesting anything — Graphiti truncates silently."
  fi

  step "Config sanity"
  load_env
  [[ -n "${ZEP_BASE_URL:-}" ]] && ok "ZEP_BASE_URL=$ZEP_BASE_URL" \
    || warn "ZEP_BASE_URL unset — SoSim would talk to Zep Cloud."
  [[ -z "${ZEP_API_URL:-}" ]] && ok "ZEP_API_URL unset (required)" \
    || die "ZEP_API_URL is set; the app refuses to boot. Use ZEP_BASE_URL."
  [[ "${GRAPHITI_TELEMETRY_ENABLED:-}" == "false" ]] && ok "Graphiti telemetry off" \
    || warn "GRAPHITI_TELEMETRY_ENABLED is not false — Graphiti will call out to PostHog."
  [[ "${FLASK_DEBUG:-false}" == "false" ]] && ok "FLASK_DEBUG off" \
    || warn "FLASK_DEBUG is on; the reloader fork breaks simulation process tracking."
  if grep -qE '^LLM_BOOST_[A-Z_]+=\s*$' "$ROOT/.env"; then
    warn "LLM_BOOST_* keys are present but blank. They must be absent entirely."
  fi
  [[ -d "$HF_CACHE/hub" ]] && ok "HF cache present at $HF_CACHE" \
    || warn "no HF cache yet; run '$0 setup' before going offline."
}

summary() {
  local ip; ip=$(hostname -I 2>/dev/null | awk '{print $1}'); ip="${ip:-<this-host>}"
  cat <<EOF

$(printf '%s' "$G")SoSim is up.$(printf '%s' "$N")

  Open:  http://$ip:$FRONTEND_PORT

  Expose ONLY this port on the network:

    $FRONTEND_PORT/tcp   frontend (Vite). It proxies /api to the backend, so this
                         single port serves the whole application.

  Everything else is bound to 127.0.0.1 and must NOT be exposed:

    $BACKEND_PORT   backend API        $SHIM_PORT   Zep-compatible shim
    $LLM_PORT   vLLM (OpenAI API)  $EMBED_PORT   embeddings (vLLM)
    $FALKORDB_PORT   FalkorDB           $FALKORDB_UI_PORT   FalkorDB browser UI

  To reach the UI by hostname rather than IP, set VITE_ALLOWED_HOSTS in .env.

  $0 status | logs [llm|backend|zep-shim|frontend|embed|falkordb] | stop

EOF
}

# =============================================================================

usage() { sed -n '3,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

# -v/--verbose anywhere in the arguments echoes every external command.
ARGS=()
for arg in "$@"; do
  case "$arg" in
    -v|--verbose) VERBOSE=1 ;;
    *) ARGS+=("$arg") ;;
  esac
done
set -- "${ARGS[@]:-}"

if [[ "$VERBOSE" == 1 ]]; then
  note "verbose mode: every external command is echoed before it runs"
fi

case "${1:-all}" in
  setup)
    preflight; install_system_deps; install_uv; install_node
    init_submodule; make_env; install_python_deps; install_node_deps
    pull_images; fetch_models
    step "Setup complete"; note "next: $0 start"
    ;;
  start)  do_start ;;
  all)
    preflight; install_system_deps; install_uv; install_node
    init_submodule; make_env; install_python_deps; install_node_deps
    pull_images; fetch_models; do_start
    ;;
  stop)   do_stop ;;
  status) do_status ;;
  logs)   shift; do_logs "${1:-}" ;;
  test)   do_test ;;
  doctor) do_doctor ;;
  -h|--help|help) usage ;;
  *) usage; die "unknown command: $1" ;;
esac
