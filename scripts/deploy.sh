#!/usr/bin/env bash
# ============================================================================
#  Foresight 先见之明 - 一键部署脚本
# ============================================================================
#
#  用法:
#    ./scripts/deploy.sh                  # 默认: 部署后端 + 重启 Flask
#    ./scripts/deploy.sh --backend        # 只部署后端
#    ./scripts/deploy.sh --frontend       # 只部署前端 (build + COS + CDN purge)
#    ./scripts/deploy.sh --full           # 后端 + 前端全量部署
#    ./scripts/deploy.sh --no-restart     # 部署后端但不重启 Flask
#    ./scripts/deploy.sh --dry-run        # 只显示会做什么，不实际执行
#
#  前置要求:
#    - SSH key: /Users/liyizhouai/Desktop/openclaw/船长/liyizhouAI.pem
#    - SSH passwordless sudo on ubuntu@124.223.92.72
#    - coscmd 已安装并配置 (~/.cos.conf 指向 foresight-1317962478)
#    - tccli 已安装并配置 (用于 CDN 刷新)
#    - 本地有 rsync
#
#  脚本保证:
#    - 后端 Python 语法检查后才上传
#    - Flask 重启后自动 verify /health，失败则报错
#    - 前端 vite build 失败则停止
#    - 不上传 .venv/ / __pycache__/ / uploads/ 等运行时文件
# ============================================================================

set -euo pipefail

# ---------- 配置 ----------
SSH_KEY="/Users/liyizhouai/Desktop/openclaw/船长/liyizhouAI.pem"
SSH_HOST="ubuntu@124.223.92.72"
REMOTE_BACKEND="/opt/foresight/backend"
REMOTE_FRONTEND="/opt/foresight/frontend"
API_HEALTH_URL="https://api.foresight.yizhou.chat/health"
PROD_URL="https://foresight.yizhou.chat"
COS_BUCKET="foresight-1317962478"
FRONTEND_API_BASE_URL="${VITE_API_BASE_URL:-https://api.foresight.yizhou.chat}"
FRONTEND_DEMO_PASSWORD="${VITE_DEMO_PASSWORD:-}"
FRONTEND_DEPLOY_TARGET="${FRONTEND_DEPLOY_TARGET:-server}"
CDN_ORIGIN_IP="${CDN_ORIGIN_IP:-124.223.92.72}"

# 定位项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
LOCAL_BACKEND="$PROJECT_ROOT/backend"
LOCAL_FRONTEND="$PROJECT_ROOT/frontend"

# ---------- 参数 ----------
DEPLOY_BACKEND=true
DEPLOY_FRONTEND=false
RESTART_FLASK=true
DRY_RUN=false

for arg in "$@"; do
  case "$arg" in
    --backend)       DEPLOY_BACKEND=true;  DEPLOY_FRONTEND=false ;;
    --frontend)      DEPLOY_BACKEND=false; DEPLOY_FRONTEND=true  ;;
    --full)          DEPLOY_BACKEND=true;  DEPLOY_FRONTEND=true  ;;
    --no-restart)    RESTART_FLASK=false ;;
    --dry-run)       DRY_RUN=true ;;
    -h|--help)
      sed -n '2,20p' "$0" | sed 's/^# \?//'
      exit 0
      ;;
    *)
      echo "❌ 未知参数: $arg"
      echo "用 --help 查看用法"
      exit 1
      ;;
  esac
done

# ---------- 颜色 ----------
C_BLUE='\033[0;34m'
C_GREEN='\033[0;32m'
C_YELLOW='\033[0;33m'
C_RED='\033[0;31m'
C_DIM='\033[2m'
C_RESET='\033[0m'

log()     { printf "${C_BLUE}▶${C_RESET} %s\n" "$*"; }
ok()      { printf "${C_GREEN}✓${C_RESET} %s\n" "$*"; }
warn()    { printf "${C_YELLOW}⚠${C_RESET} %s\n" "$*"; }
fail()    { printf "${C_RED}✗${C_RESET} %s\n" "$*" >&2; exit 1; }
section() { printf "\n${C_BLUE}=== %s ===${C_RESET}\n" "$*"; }

maybe() {
  if $DRY_RUN; then
    printf "${C_DIM}(dry-run) %s${C_RESET}\n" "$*"
  else
    "$@"
  fi
}

# ---------- 前置检查 ----------
preflight() {
  section "前置检查"

  [[ -f "$SSH_KEY" ]] || fail "SSH key 不存在: $SSH_KEY"
  ok "SSH key 存在"

  ssh -i "$SSH_KEY" -o ConnectTimeout=10 "$SSH_HOST" 'echo ok' >/dev/null 2>&1 \
    || fail "SSH 连接失败"
  ok "SSH 可达 $SSH_HOST"

  if $DEPLOY_FRONTEND; then
    if [[ "$FRONTEND_DEPLOY_TARGET" == "cos" ]]; then
      command -v coscmd >/dev/null 2>&1 || fail "coscmd 未安装 (pip install coscmd)"
      ok "coscmd 可用"
      [[ -f ~/.cos.conf ]] || fail "~/.cos.conf 不存在"
      ok "~/.cos.conf 存在"
    elif [[ "$FRONTEND_DEPLOY_TARGET" == "server" ]]; then
      ok "前端部署目标: server ($SSH_HOST:$REMOTE_FRONTEND)"
    else
      fail "未知 FRONTEND_DEPLOY_TARGET: $FRONTEND_DEPLOY_TARGET (支持 server/cos)"
    fi
    command -v tccli >/dev/null 2>&1 || warn "tccli 未安装，跳过 CDN 自动刷新"
  fi

  if $DEPLOY_BACKEND; then
    [[ -d "$LOCAL_BACKEND" ]] || fail "本地 backend 目录不存在"
    ok "本地 backend: $LOCAL_BACKEND"
  fi

  if $DEPLOY_FRONTEND; then
    [[ -d "$LOCAL_FRONTEND" ]] || fail "本地 frontend 目录不存在"
    ok "本地 frontend: $LOCAL_FRONTEND"
  fi
}

# ---------- 后端语法检查 ----------
backend_syntax_check() {
  log "Python 语法检查..."
  local failed=0
  while IFS= read -r f; do
    if ! python3 -m py_compile "$f" 2>/dev/null; then
      warn "语法错误: $f"
      failed=1
    fi
  done < <(find "$LOCAL_BACKEND/app" "$LOCAL_BACKEND/scripts" -name '*.py' -type f 2>/dev/null)
  (( failed == 0 )) || fail "语法检查未通过，部署中止"
  ok "全部通过"
}

# ---------- 后端 rsync ----------
deploy_backend() {
  section "部署后端"
  backend_syntax_check

  log "rsync backend/app → $SSH_HOST:$REMOTE_BACKEND/app"
  maybe rsync -az --delete \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    --exclude '.pytest_cache/' \
    -e "ssh -i $SSH_KEY" \
    --rsync-path="sudo rsync" \
    "$LOCAL_BACKEND/app/" \
    "$SSH_HOST:$REMOTE_BACKEND/app/"

  log "rsync backend/scripts → $SSH_HOST:$REMOTE_BACKEND/scripts"
  maybe rsync -az --delete \
    --exclude '__pycache__/' \
    --exclude '*.pyc' \
    -e "ssh -i $SSH_KEY" \
    --rsync-path="sudo rsync" \
    "$LOCAL_BACKEND/scripts/" \
    "$SSH_HOST:$REMOTE_BACKEND/scripts/"

  log "chown ubuntu:ubuntu"
  maybe ssh -i "$SSH_KEY" "$SSH_HOST" \
    "sudo chown -R ubuntu:ubuntu $REMOTE_BACKEND/app $REMOTE_BACKEND/scripts"

  ok "后端代码已同步"
}

# ---------- 重启 Flask ----------
restart_flask() {
  section "重启 Flask"

  if $DRY_RUN; then
    warn "dry-run: 不实际重启 Flask"
    return
  fi

  log "kill 旧 Flask 进程..."
  ssh -i "$SSH_KEY" "$SSH_HOST" '
    OLD=$(sudo ss -tlnp 2>/dev/null | grep 5001 | grep -oP "pid=\K[0-9]+" | head -1)
    if [[ -n "$OLD" ]]; then
      echo "killing PID $OLD"
      sudo kill -9 "$OLD" 2>/dev/null || true
    else
      echo "no old Flask running"
    fi
  '
  sleep 2

  log "启动新 Flask..."
  ssh -i "$SSH_KEY" "$SSH_HOST" '
    sudo -u ubuntu bash -lc "cd /opt/foresight/backend && setsid ./.venv-311/bin/python run.py --host 0.0.0.0 >> logs/server.log 2>&1 < /dev/null &"
  '
  sleep 4

  log "验证 /health..."
  local attempts=0
  local max_attempts=5
  while (( attempts < max_attempts )); do
    if curl -sf -m 5 "$API_HEALTH_URL" >/dev/null 2>&1; then
      local new_pid
      new_pid=$(ssh -i "$SSH_KEY" "$SSH_HOST" 'sudo ss -tlnp 2>/dev/null | grep 5001 | grep -oP "pid=\K[0-9]+" | head -1')
      ok "Flask 已就绪 (PID $new_pid)"
      return 0
    fi
    attempts=$(( attempts + 1 ))
    sleep 2
  done
  fail "Flask 健康检查超时 ($max_attempts 次尝试失败)"
}

# ---------- 前端构建 + 部署 ----------
deploy_frontend() {
  section "部署前端"

  log "vite build..."
  if $DRY_RUN; then
    warn "dry-run: 跳过 vite build"
  else
    ( cd "$LOCAL_FRONTEND" && \
      VITE_API_BASE_URL="$FRONTEND_API_BASE_URL" \
      VITE_DEMO_PASSWORD="$FRONTEND_DEMO_PASSWORD" \
      npx vite build 2>&1 | tail -10 ) \
      || fail "vite build 失败"
  fi
  ok "构建完成"

  if [[ "$FRONTEND_DEPLOY_TARGET" == "server" ]]; then
    log "rsync frontend/dist → $SSH_HOST:$REMOTE_FRONTEND"
    maybe rsync -az --delete \
      --exclude '.DS_Store' \
      -e "ssh -i $SSH_KEY" \
      "$LOCAL_FRONTEND/dist/" \
      "$SSH_HOST:/tmp/foresight-frontend-dist/"

    maybe ssh -i "$SSH_KEY" "$SSH_HOST" \
      "sudo mkdir -p '$REMOTE_FRONTEND' && sudo rsync -az --delete /tmp/foresight-frontend-dist/ '$REMOTE_FRONTEND'/ && sudo chown -R www-data:www-data '$REMOTE_FRONTEND'"
    ok "已上传到云服务器静态目录"

    if command -v tccli >/dev/null 2>&1 && ! $DRY_RUN; then
      log "确认 CDN 回源为云服务器..."
      tccli cdn UpdateDomainConfig --cli-unfold-argument \
        --Domain "${PROD_URL#https://}" \
        --Origin.Origins "$CDN_ORIGIN_IP" \
        --Origin.OriginType ip \
        --Origin.ServerName "${PROD_URL#https://}" \
        --Origin.OriginPullProtocol http >/dev/null
      ok "CDN 回源: $CDN_ORIGIN_IP"
    fi
  else
    log "coscmd upload dist/ → cos://$COS_BUCKET/"
    maybe bash -c "cd '$LOCAL_FRONTEND' && coscmd upload -r dist/ / --ignore .DS_Store" 2>&1 | tail -15
    ok "已上传到 COS"
  fi

  # CDN 刷新 (可选)
  if command -v tccli >/dev/null 2>&1; then
    log "刷新 CDN 缓存..."
    if $DRY_RUN; then
      warn "dry-run: 跳过 CDN 刷新"
    else
      local task_id
      task_id=$(tccli cdn PurgePathCache --cli-unfold-argument \
        --Paths "$PROD_URL/" --FlushType flush 2>&1 \
        | python3 -c "import json,sys; print(json.load(sys.stdin).get('TaskId','unknown'))" 2>/dev/null \
        || echo "failed")
      ok "CDN 刷新任务: $task_id (1-3 分钟生效)"
    fi
  else
    warn "tccli 未安装，需要手动刷新 CDN"
  fi
}

# ---------- 最终验证 ----------
final_verify() {
  section "最终验证"

  if $DEPLOY_BACKEND && ! $DRY_RUN; then
    log "API health check..."
    if curl -sf -m 5 "$API_HEALTH_URL" >/dev/null 2>&1; then
      ok "API $API_HEALTH_URL"
    else
      warn "API 不可达: $API_HEALTH_URL"
    fi
  fi

  if $DEPLOY_FRONTEND && ! $DRY_RUN; then
    log "前端 HTML check..."
    if curl -sfI -m 5 "$PROD_URL" 2>&1 | head -1 | grep -q "200"; then
      ok "前端 $PROD_URL"
    else
      warn "前端 HTML 不可达: $PROD_URL"
    fi
  fi
}

# ---------- main ----------
main() {
  section "Foresight 部署"
  printf "Mode: "
  $DEPLOY_BACKEND && printf "backend "
  $DEPLOY_FRONTEND && printf "frontend "
  $RESTART_FLASK && printf "+restart "
  $DRY_RUN && printf "(DRY-RUN) "
  printf "\n"

  preflight

  if $DEPLOY_BACKEND; then
    deploy_backend
    $RESTART_FLASK && restart_flask
  fi

  if $DEPLOY_FRONTEND; then
    deploy_frontend
  fi

  final_verify

  section "部署完成"
  ok "全部步骤成功"
}

main "$@"
