#!/usr/bin/env bash
# Disposable local PostgreSQL + Redis for VoidSwitch development.
#
#   scripts/dev-services.sh start    # init (if needed) + start both
#   scripts/dev-services.sh stop     # stop both (data preserved)
#   scripts/dev-services.sh status   # show readiness
#   scripts/dev-services.sh logs     # tail both logs
#   scripts/dev-services.sh reset    # stop + delete the PostgreSQL data dir
#
# Everything lives under ${VOIDSWITCH_DEV_ROOT:-/tmp/voidswitch-dev} and binds to
# 127.0.0.1 only. The system PostgreSQL cluster and system Redis (:6379) are
# NEVER touched.
set -euo pipefail

ROOT="${VOIDSWITCH_DEV_ROOT:-/tmp/voidswitch-dev}"
PGDATA="$ROOT/pgdata"
PGSOCK="$ROOT/pgsock"
PGPORT="${VOIDSWITCH_PG_PORT:-55432}"
REDIS_PORT="${VOIDSWITCH_REDIS_PORT:-56379}"
DB_NAME="${VOIDSWITCH_DB_NAME:-voidswitch_dev}"
DB_USER="${VOIDSWITCH_DB_USER:-voidswitch}"

# Locate versioned PostgreSQL binaries (initdb/pg_ctl are not always on PATH).
find_pg_bin() {
  if command -v initdb >/dev/null 2>&1; then
    dirname "$(command -v initdb)"
    return
  fi
  local v
  for v in $(ls -1 /usr/lib/postgresql 2>/dev/null | sort -rV); do
    if [ -x "/usr/lib/postgresql/$v/bin/initdb" ]; then
      echo "/usr/lib/postgresql/$v/bin"
      return
    fi
  done
  echo ""
}

PG_BIN="$(find_pg_bin)"
if [ -z "$PG_BIN" ]; then
  echo "error: PostgreSQL server binaries (initdb) not found." >&2
  exit 1
fi

start_pg() {
  mkdir -p "$ROOT" "$PGSOCK"
  if [ ! -f "$PGDATA/PG_VERSION" ]; then
    echo "initdb -> $PGDATA"
    "$PG_BIN/initdb" -D "$PGDATA" -U "$DB_USER" --auth=trust --encoding=UTF8 --locale=C.UTF-8 >"$ROOT/initdb.log" 2>&1
  fi
  if "$PG_BIN/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
    echo "postgres already running"
  else
    "$PG_BIN/pg_ctl" -D "$PGDATA" -l "$ROOT/postgres.log" \
      -o "-p $PGPORT -k $PGSOCK -h 127.0.0.1" start -w >/dev/null
    echo "postgres started on 127.0.0.1:$PGPORT"
  fi
  "$PG_BIN/pg_isready" -h 127.0.0.1 -p "$PGPORT" >/dev/null
  if ! "$PG_BIN/psql" -h 127.0.0.1 -p "$PGPORT" -U "$DB_USER" -d postgres -tAc \
      "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
    "$PG_BIN/psql" -h 127.0.0.1 -p "$PGPORT" -U "$DB_USER" -d postgres -c "CREATE DATABASE $DB_NAME" >/dev/null
    echo "created database $DB_NAME"
  fi
}

stop_pg() {
  if [ -f "$PGDATA/PG_VERSION" ] && "$PG_BIN/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
    "$PG_BIN/pg_ctl" -D "$PGDATA" stop -m fast >/dev/null
    echo "postgres stopped"
  else
    echo "postgres not running"
  fi
}

start_redis() {
  mkdir -p "$ROOT"
  if redis-cli -p "$REDIS_PORT" ping >/dev/null 2>&1; then
    echo "redis already running on :$REDIS_PORT"
    return
  fi
  redis-server --port "$REDIS_PORT" --bind 127.0.0.1 \
    --save "" --appendonly no \
    --dir "$ROOT" --pidfile "$ROOT/redis.pid" --logfile "$ROOT/redis.log" --daemonize yes
  sleep 0.3
  redis-cli -p "$REDIS_PORT" ping >/dev/null
  echo "redis started on 127.0.0.1:$REDIS_PORT"
}

stop_redis() {
  if redis-cli -p "$REDIS_PORT" ping >/dev/null 2>&1; then
    redis-cli -p "$REDIS_PORT" shutdown nosave >/dev/null 2>&1 || true
    echo "redis stopped"
  else
    echo "redis not running"
  fi
}

status() {
  if "$PG_BIN/pg_ctl" -D "$PGDATA" status >/dev/null 2>&1; then
    echo "postgres: running (127.0.0.1:$PGPORT db=$DB_NAME)"
  else
    echo "postgres: stopped"
  fi
  if redis-cli -p "$REDIS_PORT" ping >/dev/null 2>&1; then
    echo "redis:    running (127.0.0.1:$REDIS_PORT)"
  else
    echo "redis:    stopped"
  fi
}

case "${1:-}" in
  start) start_pg; start_redis ;;
  stop) stop_redis; stop_pg ;;
  status) status ;;
  logs) tail -n 40 "$ROOT/postgres.log" "$ROOT/redis.log" 2>/dev/null || true ;;
  reset) stop_redis; stop_pg; rm -rf "$PGDATA"; echo "postgres data dir removed" ;;
  *) echo "usage: $0 {start|stop|status|logs|reset}" >&2; exit 2 ;;
esac
