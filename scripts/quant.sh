#!/usr/bin/env bash
# Quantifiction 统一启动脚本 — Linux / macOS / iOS(iSH)
# 管理三个常驻进程：影子引擎 / Agent认知层 / Web看板
#
# 用法:
#   ./scripts/quant.sh start            启动全部（读 .env，默认 REST 轮询）
#   ./scripts/quant.sh start --ws       WS 实时模式（经 Clash/透明代理，见下）
#   ./scripts/quant.sh stop             停止全部
#   ./scripts/quant.sh restart [--ws]   重启（无损，进程恢复持久化状态）
#   ./scripts/quant.sh status           查看各进程状态
#   ./scripts/quant.sh logs <engine|agent|web>   跟随日志
#   ./scripts/quant.sh start engine     只启动某一个（engine|agent|web）
#
# WS 实时模式：需要一个“透传 TLS”的代理（如 Clash 混合端口）。
#   默认代理地址 http://127.0.0.1:7890，可用环境变量 QUANT_WS_PROXY 覆盖。
#   服务器直连公网时用 --ws-direct（无需代理）。
set -eu

# --- 定位项目根 ---
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
cd "$ROOT"

PID_DIR="$ROOT/data/pids"
LOG_DIR="$ROOT/data/logs"
mkdir -p "$PID_DIR" "$LOG_DIR"

# 加载 .env（KEY=VALUE，忽略注释/空行）——使脚本自包含（agent 需 GRSAI/OKX 密钥）
if [ -f "$ROOT/.env" ]; then
  while IFS= read -r line || [ -n "$line" ]; do
    case "$line" in
      ''|\#*) continue ;;
      *=*) key="${line%%=*}"; val="${line#*=}"; export "$(echo "$key" | xargs)"="$val" ;;
    esac
  done < "$ROOT/.env"
fi

# --- 探测 Python 解释器 ---
if [ -x "$ROOT/.venv/bin/python" ]; then
  PY="$ROOT/.venv/bin/python"
elif [ -x "$ROOT/.venv/Scripts/python.exe" ]; then
  PY="$ROOT/.venv/Scripts/python.exe"   # Git-Bash on Windows
elif command -v python3 >/dev/null 2>&1; then
  PY="python3"
else
  PY="python"
fi

# --- 服务定义（名称 -> 启动参数）---
svc_args() {
  case "$1" in
    engine) echo "-m quant.research.shadow_engine" ;;
    agent)  echo "-m quant.cognitive.agent_runner" ;;
    web)    echo "-m uvicorn quant.webui.live_dashboard:app --host 127.0.0.1 --port 8000 --log-level warning" ;;
    *) echo "" ;;
  esac
}
ALL="engine agent web"

# --- WS 实时环境（可选）---
apply_ws_env() {
  local proxy="${QUANT_WS_PROXY:-http://127.0.0.1:7890}"
  export OKX_BASE_URL="https://www.okx.com"
  if [ "${1:-}" = "direct" ]; then
    export OKX_WS_DIRECT=1                     # 服务器直连，无需代理
    echo "  [WS] 直连模式 (OKX_WS_DIRECT=1)"
  else
    export HTTP_PROXY="$proxy" HTTPS_PROXY="$proxy" WS_PROXY="$proxy"
    echo "  [WS] 经代理 $proxy"
  fi
}

is_running() {  # $1=name
  local pf="$PID_DIR/$1.pid"
  [ -f "$pf" ] || return 1
  local pid; pid="$(cat "$pf")"
  kill -0 "$pid" 2>/dev/null
}

start_one() {  # $1=name
  local name="$1" args; args="$(svc_args "$name")"
  [ -n "$args" ] || { echo "未知服务: $name"; return 1; }
  if is_running "$name"; then echo "  $name 已在运行 (pid $(cat "$PID_DIR/$name.pid"))"; return 0; fi
  # shellcheck disable=SC2086
  PYTHONIOENCODING=utf-8 nohup "$PY" $args >"$LOG_DIR/$name.log" 2>&1 &
  echo $! >"$PID_DIR/$name.pid"
  sleep 1
  if is_running "$name"; then echo "  $name 启动 ✓ (pid $!)"; else echo "  $name 启动失败，看 $LOG_DIR/$name.log"; fi
}

stop_one() {  # $1=name
  local name="$1" pf="$PID_DIR/$1.pid"
  if is_running "$name"; then
    kill "$(cat "$pf")" 2>/dev/null || true
    sleep 1
    is_running "$name" && kill -9 "$(cat "$pf")" 2>/dev/null || true
    echo "  $name 已停"
  else
    echo "  $name 未运行"
  fi
  rm -f "$pf"
}

status() {
  printf "%-8s %-10s %s\n" "服务" "状态" "PID"
  for s in $ALL; do
    if is_running "$s"; then printf "%-8s %-10s %s\n" "$s" "运行中" "$(cat "$PID_DIR/$s.pid")";
    else printf "%-8s %-10s %s\n" "$s" "停止" "-"; fi
  done
  echo "看板: http://127.0.0.1:8000"
}

# --- 参数解析 ---
CMD="${1:-status}"; shift || true
WS_MODE=""; TARGETS=""
for a in "$@"; do
  case "$a" in
    --ws) WS_MODE="proxy" ;;
    --ws-direct) WS_MODE="direct" ;;
    engine|agent|web) TARGETS="$TARGETS $a" ;;
    *) echo "忽略未知参数: $a" ;;
  esac
done
[ -n "$TARGETS" ] || TARGETS="$ALL"

case "$CMD" in
  start)
    [ -n "$WS_MODE" ] && { echo "行情: WS 实时模式"; apply_ws_env "$([ "$WS_MODE" = direct ] && echo direct)"; } || echo "行情: REST 轮询（默认，读 .env）"
    for s in $TARGETS; do start_one "$s"; done ;;
  stop)
    for s in $TARGETS; do stop_one "$s"; done ;;
  restart)
    for s in $TARGETS; do stop_one "$s"; done
    sleep 1
    [ -n "$WS_MODE" ] && apply_ws_env "$([ "$WS_MODE" = direct ] && echo direct)" || true
    for s in $TARGETS; do start_one "$s"; done ;;
  status) status ;;
  logs)
    t="${TARGETS# }"; t="${t%% *}"
    [ -f "$LOG_DIR/$t.log" ] && tail -f "$LOG_DIR/$t.log" || echo "无日志: $t（engine|agent|web）" ;;
  *) echo "用法: $0 {start|stop|restart|status|logs} [--ws|--ws-direct] [engine|agent|web]" ;;
esac
