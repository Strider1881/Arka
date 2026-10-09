#!/usr/bin/env bash
# Start Portal + Operator UI for a private/local deploy (loopback by default).
# Usage: from repo root — make deploy-up   or   ./scripts/deploy-up.sh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ -f deploy.env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./deploy.env
  set +a
elif [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source ./.env
  set +a
fi

export PATH="${HOME}/.local/bin:${PATH}"

PORTAL_PORT="${PORTAL_PORT:-8765}"
OPERATOR_PORT="${OPERATOR_PORT:-8877}"
DEPLOY_BIND_HOST="${DEPLOY_BIND_HOST:-127.0.0.1}"
PORTAL_HOST="${PORTAL_HOST:-$DEPLOY_BIND_HOST}"
OPERATOR_HOST="${OPERATOR_HOST:-$DEPLOY_BIND_HOST}"
PORTAL_BASE_URL="${PORTAL_BASE_URL:-http://127.0.0.1:${PORTAL_PORT}}"
DEPLOY_RUN_DIR="${DEPLOY_RUN_DIR:-.deploy}"

mkdir -p "$DEPLOY_RUN_DIR" data
export PORTAL_HOST PORTAL_PORT PORTAL_BASE_URL
export OPERATOR_HOST OPERATOR_PORT
export PORTAL_OPERATOR_PASSWORD="${PORTAL_OPERATOR_PASSWORD:-change-me}"
export PORTAL_MANAGER_PASSWORD="${PORTAL_MANAGER_PASSWORD:-priya-approve}"
export PORTAL_SESSION_SECRET="${PORTAL_SESSION_SECRET:-acme-dev-secret-change-me}"
export PORTAL_ADMIN_TOKEN="${PORTAL_ADMIN_TOKEN:-demo-admin-token}"
export OPERATOR_DB_PATH="${OPERATOR_DB_PATH:-data/operator.db}"
export OPERATOR_DATA_DIR="${OPERATOR_DATA_DIR:-data}"
export OPERATOR_HEADLESS="${OPERATOR_HEADLESS:-true}"

# Refuse public bind of Operator UI without Basic Auth.
if [[ "$OPERATOR_HOST" != "127.0.0.1" && "$OPERATOR_HOST" != "localhost" ]]; then
  if [[ -z "${OPERATOR_UI_BASIC_AUTH_USER:-}" || -z "${OPERATOR_UI_BASIC_AUTH_PASS:-}" ]]; then
    echo "ERROR: OPERATOR_HOST=$OPERATOR_HOST is not loopback but OPERATOR_UI_BASIC_AUTH_USER/PASS unset."
    echo "Set Basic Auth credentials in deploy.env before exposing the Operator UI."
    exit 1
  fi
fi

if [[ -f "$DEPLOY_RUN_DIR/portal.pid" ]] || [[ -f "$DEPLOY_RUN_DIR/ui.pid" ]]; then
  echo "Deploy already appears running (pid files in $DEPLOY_RUN_DIR). Run make deploy-down first."
  exit 1
fi

# Hermetic inbox PDFs
uv run python -m company_world.scripts.make_invoices >/dev/null

echo "Starting portal on ${PORTAL_HOST}:${PORTAL_PORT} (PORTAL_BASE_URL=${PORTAL_BASE_URL})"
nohup uv run python -m company_world.portal \
  >"$DEPLOY_RUN_DIR/portal.log" 2>&1 &
echo $! >"$DEPLOY_RUN_DIR/portal.pid"

echo "Starting Operator UI on ${OPERATOR_HOST}:${OPERATOR_PORT}"
nohup env PORTAL_BASE_URL="$PORTAL_BASE_URL" \
  uv run uvicorn ark_operator.api.app:app --host "$OPERATOR_HOST" --port "$OPERATOR_PORT" \
  >"$DEPLOY_RUN_DIR/ui.log" 2>&1 &
echo $! >"$DEPLOY_RUN_DIR/ui.pid"

# Health wait
for i in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:${PORTAL_PORT}/health" >/dev/null \
    && curl -fsS "http://127.0.0.1:${OPERATOR_PORT}/health" >/dev/null; then
    echo "OK — portal http://127.0.0.1:${PORTAL_PORT}  ui http://127.0.0.1:${OPERATOR_PORT}"
    if [[ -n "${OPERATOR_UI_BASIC_AUTH_USER:-}" ]]; then
      echo "Operator UI Basic Auth is ENABLED (user set; password not printed)."
    else
      echo "Operator UI Basic Auth is OFF — keep UI on loopback / private network only."
    fi
    exit 0
  fi
  sleep 0.5
done

echo "ERROR: health check timed out. See $DEPLOY_RUN_DIR/*.log"
exit 1
