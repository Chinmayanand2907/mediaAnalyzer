#!/bin/bash
set -euo pipefail
# Local dev helper. Override via env: PG_CTL, PGDATA. Only stops the
# redis-server we started (pkill -f with dir match), never `kill <any pid on 6379>`.

PG_CTL="${PG_CTL:-/Users/Shared/DBngin/postgresql/17.0/bin/pg_ctl}"
PGDATA="${PGDATA:-/Users/chinmay/Documents/postgresql_data}"
REDIS_CLI="${REDIS_CLI:-/Users/Shared/DBngin/redis/7.0.0/bin/redis-cli}"
REDIS_PIDFILE="${REDIS_PIDFILE:-/tmp/engageiq-redis.pid}"

echo "Stopping PostgreSQL..."
"$PG_CTL" -D "$PGDATA" stop -m fast || true

echo "Stopping Redis..."
if [ -f "$REDIS_PIDFILE" ]; then
  redis_pid=$(cat "$REDIS_PIDFILE" 2>/dev/null || true)
  if [ -n "$redis_pid" ] && kill -0 "$redis_pid" 2>/dev/null; then
    if [ -x "$REDIS_CLI" ]; then
      "$REDIS_CLI" -p 6379 shutdown nosave >/dev/null 2>&1 || kill "$redis_pid" 2>/dev/null || true
    else
      kill "$redis_pid" 2>/dev/null || true
    fi
    echo "Redis stopped (PID $redis_pid)."
  else
    echo "Redis process in $REDIS_PIDFILE is not running."
  fi
  rm -f "$REDIS_PIDFILE"
else
  # Fallback if started without pidfile: check if port 6379 is occupied by redis-server
  redis_pid=$(lsof -ti:6379 -sTCP:LISTEN 2>/dev/null || true)
  if [ -n "$redis_pid" ]; then
    cmd=$(ps -p "$redis_pid" -o comm= 2>/dev/null || true)
    if [[ "$cmd" =~ redis-server ]]; then
      if [ -x "$REDIS_CLI" ]; then
        "$REDIS_CLI" -p 6379 shutdown nosave >/dev/null 2>&1 || kill "$redis_pid" 2>/dev/null || true
      else
        kill "$redis_pid" 2>/dev/null || true
      fi
      echo "Redis stopped (PID $redis_pid)."
    else
      echo "Port 6379 is occupied by non-redis process ($cmd); leaving it alone."
    fi
  else
    echo "Redis is not running."
  fi
fi

echo "All databases stopped!"
