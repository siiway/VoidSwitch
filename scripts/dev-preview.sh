#!/usr/bin/env bash
# Start the login-bypassed VoidSwitch dev preview (Go backend + Vite frontend).
#
#   scripts/dev-preview.sh          # start services, backend, frontend
#
# Backend:  http://127.0.0.1:8080  (dev auth bypass — synthetic owner identity)
# Frontend: http://127.0.0.1:5173  <- OPEN THIS
#
# The frontend dev server proxies /api, /v1, /provider-api, /healthz to the
# backend. Stop everything with scripts/dev-stop.sh.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ROOT="${VOIDSWITCH_DEV_ROOT:-/tmp/voidswitch-dev}"
LOG="$ROOT/preview"
mkdir -p "$LOG"

PG_PORT="${VOIDSWITCH_PG_PORT:-55432}"
REDIS_PORT="${VOIDSWITCH_REDIS_PORT:-56379}"
DB_NAME="${VOIDSWITCH_DB_NAME:-voidswitch_dev}"
DB_USER="${VOIDSWITCH_DB_USER:-voidswitch}"
BACKEND_PORT="${VOIDSWITCH_BACKEND_PORT:-8080}"
FRONTEND_PORT="${VOIDSWITCH_FRONTEND_PORT:-5175}"

# Make sure Go 1.25.1 (from the toolchain install) is on PATH if present.
if [ -x "$HOME/go-toolchains/1.25.1/bin/go" ]; then
  export PATH="$HOME/go-toolchains/1.25.1/bin:$PATH"
fi

echo "==> starting disposable services"
"$REPO/scripts/dev-services.sh" start

export VOIDSWITCH_ENV=development
export VOIDSWITCH_DEV_SKIP_AUTH=true
export DATABASE_URL="postgres://$DB_USER@127.0.0.1:$PG_PORT/$DB_NAME?sslmode=disable"
export REDIS_URL="redis://127.0.0.1:$REDIS_PORT/0"
export VOIDSWITCH_DATABASE__URL="$DATABASE_URL"
export VOIDSWITCH_REDIS__URL="$REDIS_URL"
export VOIDSWITCH_SERVER__HOST=127.0.0.1
export VOIDSWITCH_SERVER__PORT="$BACKEND_PORT"
export VOIDSWITCH_SERVER__BASE_URL="http://127.0.0.1:$BACKEND_PORT"
export VOIDSWITCH_SERVER__CORS_ORIGINS="http://127.0.0.1:$FRONTEND_PORT,http://localhost:$FRONTEND_PORT"
export VOIDSWITCH_SERVER__FRONTEND_URL="http://127.0.0.1:$FRONTEND_PORT"
export VOIDSWITCH_SERVER__LOG_CONSOLE=true
export VOIDSWITCH_SERVER__SECRET_KEY="${VOIDSWITCH_SERVER__SECRET_KEY:-dev-preview-secret-key-not-for-production}"

echo "==> building backend"
(cd "$REPO/backend" && go build -o "$LOG/voidswitch" ./cmd/voidswitch)

echo "==> starting backend on 127.0.0.1:$BACKEND_PORT (dev auth bypass ON)"
nohup "$LOG/voidswitch" >"$LOG/backend.log" 2>&1 &
echo $! > "$LOG/backend.pid"

# Wait for health.
for i in $(seq 1 60); do
  if curl -sf "http://127.0.0.1:$BACKEND_PORT/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 0.5
done
if ! curl -sf "http://127.0.0.1:$BACKEND_PORT/healthz" >/dev/null 2>&1; then
  echo "error: backend failed to start; see $LOG/backend.log" >&2
  tail -n 30 "$LOG/backend.log" >&2 || true
  exit 1
fi

echo "==> starting frontend on 127.0.0.1:$FRONTEND_PORT"
cd "$REPO/frontend"
if command -v bun >/dev/null 2>&1; then
  VITE_PORT="$FRONTEND_PORT" VITE_API_PROXY="http://127.0.0.1:$BACKEND_PORT" \
    nohup bun run dev --host 127.0.0.1 --port "$FRONTEND_PORT" >"$LOG/frontend.log" 2>&1 &
else
  VITE_PORT="$FRONTEND_PORT" VITE_API_PROXY="http://127.0.0.1:$BACKEND_PORT" \
    nohup npx vite --host 127.0.0.1 --port "$FRONTEND_PORT" >"$LOG/frontend.log" 2>&1 &
fi
echo $! > "$LOG/frontend.pid"

echo
echo "=============================================="
echo "  VoidSwitch dev preview is starting"
echo "  Open:  http://127.0.0.1:$FRONTEND_PORT"
echo "  API :  http://127.0.0.1:$BACKEND_PORT/healthz"
echo "  Login bypass: ENABLED (development only)"
echo "  Logs:  $LOG/{backend,frontend}.log"
echo "  Stop:  scripts/dev-stop.sh"
echo "=============================================="
