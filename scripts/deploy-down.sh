#!/usr/bin/env bash
# Stop processes started by deploy-up.sh / deploy-tunnel.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DEPLOY_RUN_DIR="${DEPLOY_RUN_DIR:-.deploy}"
if [[ -f deploy.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./deploy.env
  set +a
fi
DEPLOY_RUN_DIR="${DEPLOY_RUN_DIR:-.deploy}"

stop_pidfile() {
  local f="$1"
  local name="$2"
  if [[ -f "$f" ]]; then
    local pid
    pid="$(cat "$f" || true)"
    if [[ -n "${pid:-}" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      # Give uvicorn/portal a moment; then force
      for _ in $(seq 1 20); do
        kill -0 "$pid" 2>/dev/null || break
        sleep 0.1
      done
      kill -9 "$pid" 2>/dev/null || true
      echo "Stopped $name (pid $pid)"
    else
      echo "No live process for $name"
    fi
    rm -f "$f"
  fi
}

stop_pidfile "$DEPLOY_RUN_DIR/tunnel.pid" "cloudflared tunnel"
stop_pidfile "$DEPLOY_RUN_DIR/ui.pid" "Operator UI"
stop_pidfile "$DEPLOY_RUN_DIR/portal.pid" "Portal"
echo "Deploy stopped."
