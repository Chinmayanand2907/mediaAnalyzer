#!/bin/bash
set -euo pipefail
# Local dev helper (macOS + DBngin default paths). Override via env:
#   PG_CTL=/path/to/pg_ctl PGDATA=/path/to/data REDIS_SERVER=/path/to/redis-server ./start_dbs.sh
# Do NOT run at the same time as `docker compose up` (both bind 5432/6379).

PG_CTL="${PG_CTL:-/Users/Shared/DBngin/postgresql/17.0/bin/pg_ctl}"
PGDATA="${PGDATA:-/Users/chinmay/Documents/postgresql_data}"
REDIS_SERVER="${REDIS_SERVER:-/Users/Shared/DBngin/redis/7.0.0/bin/redis-server}"
REDIS_CLI="${REDIS_CLI:-/Users/Shared/DBngin/redis/7.0.0/bin/redis-cli}"
REDIS_DIR="${REDIS_DIR:-/tmp}"
REDIS_PIDFILE="${REDIS_PIDFILE:-/tmp/engageiq-redis.pid}"

echo "Starting PostgreSQL..."
"$PG_CTL" -D "$PGDATA" -l /tmp/pg.log start
until "$PG_CTL" -D "$PGDATA" status >/dev/null 2>&1; do sleep 1; done

echo "Starting Redis (RDB in $REDIS_DIR, port 6379)..."
"$REDIS_SERVER" --daemonize yes --dir "$REDIS_DIR" --dbfilename engageiq-local.rdb --pidfile "$REDIS_PIDFILE" --port 6379
if [ -x "$REDIS_CLI" ]; then
  until "$REDIS_CLI" -p 6379 ping >/dev/null 2>&1; do sleep 0.5; done
else
  until lsof -ti:6379 -sTCP:LISTEN >/dev/null 2>&1; do sleep 0.5; done
fi

echo "All databases started!"
