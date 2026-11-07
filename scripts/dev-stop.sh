#!/usr/bin/env bash
# Stop the dev preview (backend + frontend) and the disposable services.
set -uo pipefail

ROOT="${VOIDSWITCH_DEV_ROOT:-/tmp/voidswitch-dev}"
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG="$ROOT/preview"

for name in frontend backend; do
  pidfile="$LOG/$name.pid"
  if [ -f "$pidfile" ]; then
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "stopped $name (pid $pid)"
    fi
    rm -f "$pidfile"
  fi
done

"$REPO/scripts/dev-services.sh" stop || true
