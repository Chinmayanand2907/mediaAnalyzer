#!/bin/bash
# =============================================================================
#  EngageIQ — Production & Container Entrypoint
#  Starts Redis, Celery worker, and Uvicorn.
#
#  Cloud deployment (Hugging Face Spaces):
#    Runs Redis + Celery Worker + Uvicorn together in one container.
#    Default PORT=7860 (required by Hugging Face Spaces).
#
#  Local development (Docker Compose):
#    Respects PORT=8000, external REDIS_URL, and START_CELERY_WORKER=false.
# =============================================================================

set -e

PORT="${PORT:-7860}"

echo "🚀 EngageIQ starting on port ${PORT}…"

# ── 1. Embedded Redis server (if local Redis requested or default) ───────────
if [[ -z "$REDIS_URL" ]] || [[ "$REDIS_URL" == *"127.0.0.1"* ]] || [[ "$REDIS_URL" == *"localhost"* ]]; then
  echo "▶ Starting embedded Redis server (127.0.0.1:6379)…"
  redis-server \
    --daemonize yes \
    --appendonly yes \
    --maxmemory 256mb \
    --maxmemory-policy allkeys-lru \
    --logfile /tmp/redis.log

  # Wait for Redis to be ready
  until redis-cli ping 2>/dev/null | grep -q PONG; do
    echo "  Waiting for Redis…"
    sleep 0.5
  done
  echo "  ✅ Embedded Redis is up."
else
  echo "▶ Using external Redis from REDIS_URL (${REDIS_URL})"
fi

# ── 2. Celery worker ─────────────────────────────────────────────────────────
if [ "${START_CELERY_WORKER:-true}" = "true" ]; then
  echo "▶ Starting Celery worker (concurrency=2)…"
  celery -A app.core.celery_app worker \
    --loglevel=info \
    --concurrency=2 \
    -Q celery,youtube,reddit \
    --logfile=/tmp/celery_worker.log \
    --detach

  echo "  ✅ Celery worker started in background."
else
  echo "▶ Celery worker startup skipped (START_CELERY_WORKER=false)."
fi

# ── 3. Start Uvicorn (foreground — keeps container alive) ────────────────────
echo "▶ Starting Uvicorn on 0.0.0.0:${PORT}…"
exec uvicorn app.main:app \
  --host 0.0.0.0 \
  --port "${PORT}" \
  --workers 2
