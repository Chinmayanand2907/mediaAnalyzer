"""Database connection factories.

Provides:
- ``get_postgres_session`` — async SQLModel session for request-scoped DI
- ``get_mongo_db``         — Motor async database handle
"""

from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlmodel import SQLModel

from app.core.config import get_settings

settings = get_settings()

# ── PostgreSQL (async via asyncpg) ───────────────────────────
async_engine = create_async_engine(
    settings.POSTGRES_DSN,
    echo=settings.DEBUG,
    future=True,
)

AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_postgres() -> None:
    """Create all SQLModel tables (call once at startup)."""
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def get_postgres_session() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency — yields an async session per request."""
    async with AsyncSessionLocal() as session:
        yield session


# ── MongoDB (async via Motor) ────────────────────────────────
_mongo_client: AsyncIOMotorClient | None = None


def get_mongo_client() -> AsyncIOMotorClient:
    """Lazily initialize and return the Motor client singleton."""
    global _mongo_client
    if _mongo_client is None:
        _mongo_client = AsyncIOMotorClient(settings.MONGO_URI)
    return _mongo_client


def get_mongo_db() -> AsyncIOMotorDatabase:
    """Return the configured MongoDB database handle."""
    return get_mongo_client()[settings.MONGO_DB]
