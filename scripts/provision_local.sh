#!/usr/bin/env bash
#
# provision_local.sh — bring up MiroFish entirely on this machine.
#
# Target: NVIDIA DGX Spark (GB10, aarch64, 128GB unified memory), Ubuntu-based.
# Works on any aarch64/x86_64 Linux box with Docker + an NVIDIA runtime.
#
#   ./scripts/provision_local.sh setup     # deps, submodule, .env, models  (needs network)
#   ./scripts/provision_local.sh start     # bring every service up        (offline)
#   ./scripts/provision_local.sh all       # setup + start
#   ./scripts/provision_local.sh status | logs [svc] | stop | doctor | test
#
# Nothing here talks to a hosted API at runtime. `setup` is the only stage that
# needs the internet, and only to download packages and model weights.
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

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

NODE_MAJOR_REQUIRED=20   # vite 7 needs ^20.19 || >=22.12

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

have() { command -v "$1" >/dev/null 2>&1; }

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
    if docker info --format '{{json .Runtimes}}' 2>/dev/null | grep -q nvidia; then
      ok "nvidia container runtime registered"
    else
      warn "nvidia runtime not listed by 'docker info'. Install nvidia-container-toolkit,"
      warn "or the LLM container will fail to see the GPU. Continuing anyway."
    fi
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
    warn "no apt-get; install the equivalents of: build-essential python3-dev git curl fonts-noto-cjk"
    return
  fi
  # build-essential + python3-dev are NOT optional: psutil is pinned to 5.9.8,
  # which publishes no linux-aarch64 wheel, so uv builds it from source. It is
  # the only package in the lockfile that does.
  local pkgs=(build-essential python3-dev git curl ca-certificates
              fonts-noto-cjk fonts-jetbrains-mono)
  local missing=()
  for p in "${pkgs[@]}"; do
    dpkg -s "$p" >/dev/null 2>&1 || missing+=("$p")
  done
  if [[ ${#missing[@]} -eq 0 ]]; then ok "all present"; return; fi
  note "installing: ${missing[*]}"
  note "this needs sudo — enter your password if prompted"
  sudo apt-get update -qq
  sudo apt-get install -y "${missing[@]}" || warn "some packages failed; continuing"
  ok "installed"
}

install_uv() {
  step "uv"
  if have uv; then ok "uv $(uv --version | cut -d' ' -f2)"; return; fi
  curl -fsSL https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  have uv || die "uv install failed; add \$HOME/.local/bin to PATH and re-run."
  ok "installed uv"
}

install_node() {
  step "Node.js"
  local major=0
  if have node; then major=$(node -v | sed 's/^v\([0-9]*\).*/\1/'); fi
  if (( major >= NODE_MAJOR_REQUIRED )); then ok "node $(node -v)"; return; fi

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
  if [[ ! -f "$ROOT/third_party/graphiti/pyproject.toml" ]]; then
    git submodule update --init --recursive
  else
    git submodule update --init --recursive --remote=false
  fi
  [[ -f "$ROOT/third_party/graphiti/server/graph_service/zep_compat/router.py" ]] \
    || die "submodule is missing the zep_compat layer. Is third_party/graphiti on the right commit?"
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
}

install_python_deps() {
  step "Python dependencies"
  note "backend (this compiles psutil from source on aarch64; be patient)"
  (cd "$ROOT/backend" && uv sync --frozen)
  ok "backend"
  note "zep-compat shim"
  (cd "$ROOT/third_party/graphiti/server" && uv sync --extra dev)
  ok "shim"
}

install_node_deps() {
  step "Frontend dependencies"
  note "npm ci for the root workspace, then the frontend (a few minutes)"
  npm ci --no-audit --no-fund
  npm ci --prefix frontend --no-audit --no-fund
  ok "installed"
}

fetch_models() {
  step "Model weights  (the only stage that needs the internet)"
  export HF_HOME="$HF_CACHE"
  local hf_bin=""
  if have hf; then hf_bin=hf
  elif have huggingface-cli; then hf_bin=huggingface-cli
  else
    note "installing huggingface_hub CLI"
    uv tool install -q "huggingface_hub[cli]" || pip install -q --user "huggingface_hub[cli]"
    hf_bin=$(have hf && echo hf || echo huggingface-cli)
  fi

  for repo in "$LLM_MODEL_REPO" "$EMBED_MODEL_REPO"; do
    note "downloading $repo"
    HF_HUB_OFFLINE=0 "$hf_bin" download "$repo" || warn "failed to download $repo"
  done

  # A Twitter simulation loads this at runtime; a Reddit-only run never does.
  # Fetch it now or the first Twitter run fails with HF_HUB_OFFLINE=1 set.
  note "downloading Twitter/twhin-bert-base (OASIS Twitter recommender, ~1GB)"
  HF_HUB_OFFLINE=0 "$hf_bin" download Twitter/twhin-bert-base || \
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
    docker pull "$image" || warn "could not pull $image"
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

wait_for_http() {
  local url="$1" name="$2" tries="${3:-120}"
  printf '    waiting for %s ' "$name"
  for _ in $(seq "$tries"); do
    if curl -fsS -o /dev/null --max-time 2 "$url"; then printf ' %sup%s\n' "$G" "$N"; return 0; fi
    printf '.'; sleep 2
  done
  printf ' %stimeout%s\n' "$R" "$N"
  return 1
}

container_up() { [[ -n "$(docker ps -q -f "name=^$1$" 2>/dev/null)" ]]; }

start_falkordb() {
  step "FalkorDB"
  if container_up mirofish-falkordb; then ok "already running"; return; fi
  docker rm -f mirofish-falkordb >/dev/null 2>&1 || true
  docker run -d --name mirofish-falkordb --restart unless-stopped \
    -p "127.0.0.1:$FALKORDB_PORT:6379" -p "127.0.0.1:$FALKORDB_UI_PORT:3000" \
    -v mirofish_falkordb:/var/lib/falkordb/data \
    -e BROWSER=1 \
    "$FALKORDB_IMAGE" >/dev/null
  ok "started on 127.0.0.1:$FALKORDB_PORT"
}

start_llm() {
  step "LLM server (vLLM)"
  if container_up mirofish-llm; then ok "already running"; return; fi
  docker rm -f mirofish-llm >/dev/null 2>&1 || true

  # Unified memory means the OS page cache eats into the KV cache budget.
  note "dropping the page cache to free unified memory (sudo; skipped if refused)"
  sync
  run_bounded 20 sudo -n sh -c 'echo 3 > /proc/sys/vm/drop_caches' 2>/dev/null || \
    note "page cache not dropped (needs passwordless sudo); fine, just less headroom"

  # Two independent needs, both served by this one endpoint:
  #  - OASIS agents use native OpenAI tool calling  -> the tool-call flags
  #  - Graphiti uses response_format json_schema    -> constrained decoding
  docker run -d --name mirofish-llm --restart unless-stopped \
    --gpus all --ipc=host \
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
      --tool-call-parser "$TOOL_CALL_PARSER" >/dev/null
  ok "starting (first load can take several minutes)"
}

start_embeddings() {
  step "Embeddings server"
  if container_up mirofish-embed; then ok "already running"; return; fi
  docker rm -f mirofish-embed >/dev/null 2>&1 || true
  # vLLM in pooling mode exposes an OpenAI-compatible /v1/embeddings.
  # `--runner pooling` supersedes the older `--task embed`; copying an older
  # recipe with --task embed will fail on a current image.
  docker run -d --name mirofish-embed --restart unless-stopped \
    --gpus all --ipc=host \
    -p "127.0.0.1:$EMBED_PORT:8000" \
    -v "$HF_CACHE:/hf" \
    -e HF_HOME=/hf -e HF_HUB_OFFLINE=1 -e TRANSFORMERS_OFFLINE=1 \
    -e HF_HUB_DISABLE_TELEMETRY=1 \
    "$EMBED_IMAGE" \
    vllm serve "$EMBED_MODEL_REPO" \
      --runner pooling \
      --host 0.0.0.0 --port 8000 \
      --gpu-memory-utilization "$EMBED_GPU_MEM_UTIL" \
      --max-model-len "$EMBED_MAX_MODEL_LEN" >/dev/null
  ok "starting on 127.0.0.1:$EMBED_PORT (model id: $EMBED_MODEL_REPO)"
}

pidfile() { echo "$RUN_DIR/$1.pid"; }

start_bg() {
  local name="$1"; shift
  local pf; pf="$(pidfile "$name")"
  if [[ -f "$pf" ]] && kill -0 "$(cat "$pf")" 2>/dev/null; then
    ok "$name already running (pid $(cat "$pf"))"
    return
  fi
  mkdir -p "$RUN_DIR" "$LOG_DIR"
  # setsid so the child gets its own process group: MiroFish's simulation
  # runner spawns OASIS children with start_new_session=True and cleans them
  # up via killpg on SIGTERM. A hard kill of the parent orphans that whole
  # group, which keeps holding the sqlite DB and burning LLM capacity.
  setsid "$@" >>"$LOG_DIR/$name.log" 2>&1 &
  echo $! >"$pf"
  ok "$name started (pid $(cat "$pf")), logging to data/logs/$name.log"
}

start_shim() {
  step "Zep-compatible shim (Graphiti-backed)"
  local venv="$ROOT/third_party/graphiti/server/.venv/bin/python"
  [[ -x "$venv" ]] || die "shim venv missing. Run: $0 setup"
  ( cd "$ROOT/third_party/graphiti/server" && \
    ZEP_COMPAT_DB_PATH="${ZEP_COMPAT_DB_PATH:-$DATA_DIR/zep_compat.sqlite3}" \
    start_bg zep-shim "$venv" -m uvicorn graph_service.zep_compat.app:app \
      --host 127.0.0.1 --port "$SHIM_PORT" )
}

start_backend() {
  step "MiroFish backend"
  # Must be the venv interpreter: simulation_runner spawns children with
  # sys.executable, so a system python here means every simulation child dies
  # on `import oasis`.
  local venv="$ROOT/backend/.venv/bin/python"
  [[ -x "$venv" ]] || die "backend venv missing. Run: $0 setup"
  ( cd "$ROOT/backend" && start_bg backend "$venv" run.py )
}

start_frontend() {
  step "Frontend"
  ( cd "$ROOT/frontend" && start_bg frontend npm run dev -- --port "$FRONTEND_PORT" )
}

do_start() {
  load_env
  start_falkordb
  start_embeddings
  start_llm
  wait_for_http "http://127.0.0.1:$EMBED_PORT/v1/models" "embeddings" 180 || \
    warn "embeddings not healthy — check: $0 logs embed"
  wait_for_http "http://127.0.0.1:$LLM_PORT/v1/models" "LLM" 300 || \
    warn "LLM not healthy — check: $0 logs llm"
  start_shim
  wait_for_http "http://127.0.0.1:$SHIM_PORT/healthcheck" "shim" 90 || \
    warn "shim not healthy — check: $0 logs zep-shim"
  start_backend
  wait_for_http "http://127.0.0.1:$BACKEND_PORT/health" "backend" 90 || \
    warn "backend not healthy — check: $0 logs backend"
  start_frontend
  wait_for_http "http://127.0.0.1:$FRONTEND_PORT" "frontend" 90 || \
    warn "frontend not healthy — check: $0 logs frontend"
  summary
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
  for c in mirofish-llm mirofish-embed mirofish-falkordb; do
    docker stop "$c" >/dev/null 2>&1 && ok "$c stopped" || true
  done
}

do_status() {
  step "Status"
  printf '  %-12s %-9s %s\n' SERVICE STATE ENDPOINT
  for row in "falkordb:mirofish-falkordb:127.0.0.1:$FALKORDB_PORT" \
             "embeddings:mirofish-embed:http://127.0.0.1:$EMBED_PORT/v1/models" \
             "llm:mirofish-llm:http://127.0.0.1:$LLM_PORT/v1/models"; do
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
    llm)        docker logs -f --tail 200 mirofish-llm ;;
    embed*)     docker logs -f --tail 200 mirofish-embed ;;
    emb)        docker logs -f --tail 200 mirofish-embed ;;
    falkor*)    docker logs -f --tail 200 mirofish-falkordb ;;
    ''|all)     tail -n 100 -f "$LOG_DIR"/*.log ;;
    *)          tail -n 200 -f "$LOG_DIR/$svc.log" ;;
  esac
}

do_test() {
  step "Test suites (no GPU, no network, no database)"
  ( cd "$ROOT/backend" && .venv/bin/python -m pytest tests/ -q ) || warn "backend tests failed"
  ( cd "$ROOT/third_party/graphiti/server" && \
    .venv/bin/python -m pytest tests/ -q --asyncio-mode=auto ) || warn "shim tests failed"
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
  if arches=$(run_bounded 180 docker run --rm --gpus all "$VLLM_IMAGE" \
      python -c 'import torch; print(" ".join(torch.cuda.get_arch_list()))' 2>/dev/null); then
    note "torch arch list: $arches"
    if [[ "$arches" == *sm_121* || "$arches" == *sm_121a* ]]; then
      ok "sm_121 present"
    else
      warn "sm_121 NOT in the arch list — this image may fail on GB10. Try another tag."
    fi
  else
    warn "could not query the image (not pulled yet, or no GPU access)"
  fi
}

do_doctor() {
  step "Doctor"
  preflight
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
    || warn "ZEP_BASE_URL unset — MiroFish would talk to Zep Cloud."
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

$(printf '%s' "$G")MiroFish is up.$(printf '%s' "$N")

  Open:  http://$ip:$FRONTEND_PORT

  Expose ONLY this port on the network:

    $FRONTEND_PORT/tcp   frontend (Vite). It proxies /api to the backend, so this
                         single port serves the whole application.

  Everything else is bound to 127.0.0.1 and must NOT be exposed:

    $BACKEND_PORT   backend API        $SHIM_PORT   Zep-compatible shim
    $LLM_PORT   vLLM (OpenAI API)  $EMBED_PORT   embeddings (TEI)
    $FALKORDB_PORT   FalkorDB           $FALKORDB_UI_PORT   FalkorDB browser UI

  To reach the UI by hostname rather than IP, set VITE_ALLOWED_HOSTS in .env.

  $0 status | logs [llm|backend|zep-shim|frontend|embed|falkordb] | stop

EOF
}

# =============================================================================

usage() { sed -n '3,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; }

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
