"""FastAPI application factory.

Run with:
    uvicorn app.main:app --reload
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import get_settings
from app.db.postgres import init_postgres
from app.db.mongodb import close_mongo, connect_mongo, ensure_indexes

# ── v1 routers ────────────────────────────────────────────────────────────────
from app.api.v1.routers.youtube import router as youtube_router
from app.api.v1.routers.reddit import router as reddit_router
from app.api.v1.routers.cross_platform import router as cross_platform_router
from app.api.v1.routers.chatbot import router as chatbot_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup / shutdown lifecycle hook."""
    # ── Startup ──────────────────────────────────────────────
    settings = get_settings()
    print(f"🚀  Starting {settings.APP_NAME} [{settings.APP_ENV}]")
    await init_postgres()
    await connect_mongo()
    await ensure_indexes()
    yield
    # ── Shutdown ─────────────────────────────────────────────
    await close_mongo()
    print("👋  Shutting down…")


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

# ── CORS — allow local React dev server ──────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:3000",   # React dev (CRA / Vite)
        "http://localhost:5173",   # Vite default
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
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


@app.get("/api/v1/routes", tags=["ops"], summary="List all registered routes")
async def list_routes():
    """Development helper — returns every registered path + method."""
    return [
        {"path": route.path, "methods": list(route.methods), "name": route.name}
        for route in app.routes
        if hasattr(route, "methods")
    ]
