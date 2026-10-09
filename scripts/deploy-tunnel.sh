#!/usr/bin/env bash
# Expose Operator UI via Cloudflare quick tunnel (trycloudflare.com).
# Portal stays on loopback for Playwright. Requires Operator UI Basic Auth.
# Usage: make deploy-up && make deploy-tunnel
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f deploy.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./deploy.env
  set +a
fi

OPERATOR_PORT="${OPERATOR_PORT:-8877}"
DEPLOY_RUN_DIR="${DEPLOY_RUN_DIR:-.deploy}"
mkdir -p "$DEPLOY_RUN_DIR"

if [[ -z "${OPERATOR_UI_BASIC_AUTH_USER:-}" || -z "${OPERATOR_UI_BASIC_AUTH_PASS:-}" ]]; then
  echo "ERROR: Refusing public tunnel without OPERATOR_UI_BASIC_AUTH_USER and OPERATOR_UI_BASIC_AUTH_PASS."
  echo "Set both in deploy.env, restart with make deploy-down && make deploy-up, then retry."
  exit 1
fi

if ! curl -fsS "http://127.0.0.1:${OPERATOR_PORT}/health" >/dev/null; then
  echo "ERROR: Operator UI not healthy on 127.0.0.1:${OPERATOR_PORT}. Run make deploy-up first."
  exit 1
fi

if ! command -v cloudflared >/dev/null 2>&1; then
  echo "ERROR: cloudflared not installed. Install: https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation/"
  exit 1
fi

if [[ -f "$DEPLOY_RUN_DIR/tunnel.pid" ]] && kill -0 "$(cat "$DEPLOY_RUN_DIR/tunnel.pid")" 2>/dev/null; then
  echo "Tunnel already running (pid $(cat "$DEPLOY_RUN_DIR/tunnel.pid")). See $DEPLOY_RUN_DIR/tunnel.log"
  exit 0
fi

echo "Starting Cloudflare quick tunnel → http://127.0.0.1:${OPERATOR_PORT}"
nohup cloudflared tunnel --url "http://127.0.0.1:${OPERATOR_PORT}" \
  --no-autoupdate \
  >"$DEPLOY_RUN_DIR/tunnel.log" 2>&1 &
echo $! >"$DEPLOY_RUN_DIR/tunnel.pid"

url=""
for i in $(seq 1 60); do
  url="$(rg -o 'https://[a-zA-Z0-9-]+\.trycloudflare\.com' "$DEPLOY_RUN_DIR/tunnel.log" 2>/dev/null | head -1 || true)"
  if [[ -n "$url" ]]; then
    echo "$url" >"$DEPLOY_RUN_DIR/public-url.txt"
    echo "Public Operator UI (Basic Auth required): $url"
    echo "URL also written to $DEPLOY_RUN_DIR/public-url.txt"
    echo "Portal remains private on loopback (Playwright)."
    exit 0
  fi
  sleep 0.5
done

echo "ERROR: timed out waiting for trycloudflare URL. See $DEPLOY_RUN_DIR/tunnel.log"
exit 1
