"""FastAPI application factory.

Run with:
    uvicorn app.main:app --reload
"""

import os
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.db.postgres import init_postgres
from app.db.mongodb import close_mongo, connect_mongo, ensure_indexes

# ── v1 routers ────────────────────────────────────────────────────────────────
from app.api.v1.routers.youtube import router as youtube_router
from app.api.v1.routers.reddit import router as reddit_router
from app.api.v1.routers.cross_platform import router as cross_platform_router
from app.api.v1.routers.chatbot import router as chatbot_router

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hook."""
    # ── Startup ──────────────────────────────────────────────
    settings = get_settings()
    logger.info("🚀  Starting %s [%s]", settings.APP_NAME, settings.APP_ENV)
    await init_postgres()
    try:
        await connect_mongo()
        await ensure_indexes()
    except Exception as e:
        logger.warning("⚠️  Mongo initialization warning: %s", e)
    yield
    # ── Shutdown ─────────────────────────────────────────────
    await close_mongo()
    logger.info("👋  Shutting down…")


settings = get_settings()

app = FastAPI(
    title=settings.APP_NAME,
    version="1.0.0",
    description=(
        "Social Media Engagement Analyzer — REST API powering the React dashboard. "
        "Ingests YouTube & Reddit data asynchronously via Celery/Redis, "
        "stores raw payloads in MongoDB, structured metrics in PostgreSQL, "
        "and serves sentiment analysis + predictive engagement forecasts."
    ),
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# ── Global exception handler ─────────────────────────────────────────────────
# Catches any unhandled exception and returns a clean 500 instead of a stack trace.

@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error(
        "Unhandled exception on %s %s: %s",
        request.method, request.url, exc,
        exc_info=True,
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error"},
    )


# ── CORS ─────────────────────────────────────────────────────────────────────
# Origins are loaded from settings.ALLOWED_ORIGINS (env var) so production
# deployments never need to edit source code.

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "Accept"],
)

# ── Register routers ─────────────────────────────────────────────────────────
API_V1_PREFIX = "/api/v1"

app.include_router(youtube_router,        prefix=API_V1_PREFIX)
app.include_router(reddit_router,         prefix=API_V1_PREFIX)
app.include_router(cross_platform_router, prefix=API_V1_PREFIX)
app.include_router(chatbot_router,        prefix=API_V1_PREFIX)


# ── Utility endpoints ────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"], summary="Liveness probe")
async def health_check():
    """Returns 200 OK when the server is up.  Use for load-balancer checks."""
    return {"status": "ok", "env": settings.APP_ENV, "version": "1.0.0"}


@app.get("/api/v1/routes", tags=["ops"], include_in_schema=False)
async def list_routes():
    """Development helper — returns every registered path + method.
    Only available when DEBUG=True in settings.
    """
    if not settings.DEBUG:
        raise HTTPException(status_code=404)
    return [
        {"path": route.path, "methods": list(route.methods), "name": route.name}
        for route in app.routes
        if hasattr(route, "methods")
    ]
