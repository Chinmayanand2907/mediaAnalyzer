# =============================================================================
#  EngageIQ — Backend Dockerfile
#
#  Deployment targets:
#    • Hugging Face Spaces (free, 16 GB RAM, 2 vCPU) — PORT=7860 (default)
#    • Render, Railway, Fly.io                        — PORT=8000 (set via env)
#
#  This image bundles Redis so a single container hosts:
#    1. redis-server  (embedded broker — no Upstash quota limits)
#    2. celery worker (background tasks: ingestion + NLP sentiment)
#    3. uvicorn       (FastAPI HTTP server)
#
#  External managed services (set in environment variables):
#    • PostgreSQL → Neon.tech   (DATABASE_URL)
#    • MongoDB    → Atlas M0    (MONGO_URI)
# =============================================================================

# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — Builder: install Python deps into a prefix
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /build

# System libs required by some ML packages
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
  && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip && \
    pip install --prefix=/install --no-cache-dir -r requirements.txt

# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — Runtime: lean image with Redis + installed packages
# ─────────────────────────────────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Runtime system libs:
#   curl      — healthcheck (curl -f /health)
#   libgomp1  — torch / xgboost / scikit-learn (OpenMP)
#   libpq5    — asyncpg / psycopg
#   redis     — embedded Redis broker (avoids Upstash quota limits)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    libgomp1 \
    libpq5 \
    redis-server \
  && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY app/ ./app/

# Copy startup script and make it executable
COPY start.sh ./start.sh
RUN chmod +x ./start.sh

# Hugging Face Spaces requires port 7860.
# Override PORT env var for other platforms (e.g. PORT=8000 on Render).
ENV PORT=7860
EXPOSE 7860

# Disable HuggingFace tokenizer parallelism warnings in forked Celery processes
ENV TOKENIZERS_PARALLELISM=false
ENV OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES

CMD ["./start.sh"]
