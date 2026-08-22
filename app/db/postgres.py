"""
PostgreSQL connection layer (async) — SQLAlchemy 2.0 + SQLModel.

Provides:
    - ``async_engine``   — async engine bound to the ``POSTGRES_DSN``
    - ``AsyncSessionLocal`` — session factory for request-scoped usage
    - ``get_db_session``    — FastAPI dependency that yields a session
    - ``init_postgres``     — creates all SQLModel tables at startup
    - ``PlatformAccount``   — sample table for cross-platform account metadata

Usage in a FastAPI route::

    from app.db.postgres import get_db_session, PlatformAccount

    @router.get("/accounts")
    async def list_accounts(session: AsyncSession = Depends(get_db_session)):
        result = await session.exec(select(PlatformAccount))
        return result.all()
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import ConfigDict
from sqlalchemy import Column, JSON
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy import UniqueConstraint
from sqlmodel import Field, SQLModel

from app.core.config import get_settings

# ─── Settings ────────────────────────────────────────────────────
settings = get_settings()

# ─── Async Engine ────────────────────────────────────────────────
async_engine = create_async_engine(
    settings.POSTGRES_DSN,          # postgresql+asyncpg://…
    echo=settings.DEBUG,            # log SQL in dev mode
    future=True,
    pool_size=10,                   # default connection pool size
    max_overflow=20,                # burst connections above pool_size
    pool_pre_ping=True,             # verify connections before checkout
)

# ─── Session Factory ─────────────────────────────────────────────
AsyncSessionLocal = sessionmaker(
    bind=async_engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ─── FastAPI Dependency ──────────────────────────────────────────
async def get_db_session() -> AsyncGenerator[AsyncSession, None]:
    """Yield an async session per request; auto-closes on exit.

    Inject into any route with ``Depends(get_db_session)``.
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


# ─── Startup Initializer ────────────────────────────────────────
async def init_postgres() -> None:
    """Create all SQLModel-registered tables.

    Call once during application startup (e.g. inside the FastAPI
    lifespan handler).  Safe to call repeatedly — existing tables
    are silently skipped.
    """
    async with async_engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Sample Table — Cross-Platform Account Metadata
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class Platform(str, Enum):
    """Supported social-media platforms."""
    YOUTUBE = "youtube"
    REDDIT = "reddit"


def _utcnow() -> datetime:
    """Return timezone-naive UTC timestamp."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class PlatformAccount(SQLModel, table=True):
    """Unified cross-platform account metadata.

    Stores one row per tracked creator / channel / subreddit,
    regardless of the originating platform.

    Columns
    -------
    id              : Internal UUID primary key.
    platform        : 'youtube' | 'reddit'.
    platform_id     : Native ID on the platform (channel ID, subreddit name).
    display_name    : Human-readable name.
    description     : Channel/subreddit description, if available.
    subscriber_count: Latest known subscriber / member count.
    profile_image_url: Avatar / icon URL.
    extra_metadata  : Arbitrary JSON blob for platform-specific fields.
    created_at      : Row creation timestamp (UTC).
    updated_at      : Last update timestamp (UTC).
    """

    __tablename__ = "platform_accounts"
    __table_args__ = (
        # Composite uniqueness: one record per (platform, native_id) pair.
        # Guards against duplicate rows from concurrent ingestion tasks.
        UniqueConstraint("platform", "platform_id", name="uq_platform_account"),
    )

    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        primary_key=True,
        description="Internal UUID primary key",
    )

    platform: Platform = Field(
        index=True,
        description="Source platform (youtube | reddit)",
    )

    platform_id: str = Field(
        index=True,
        max_length=255,
        description="Native ID on the platform (e.g. YouTube channel ID)",
    )

    display_name: str = Field(
        max_length=255,
        description="Human-readable channel / subreddit name",
    )

    description: Optional[str] = Field(
        default=None,
        description="Channel or subreddit description",
    )

    subscriber_count: Optional[int] = Field(
        default=None,
        ge=0,
        description="Latest known subscriber / member count",
    )

    profile_image_url: Optional[str] = Field(
        default=None,
        max_length=2048,
        description="Avatar or icon URL",
    )

    extra_metadata: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON),
        description="Arbitrary JSON blob for platform-specific fields",
    )

    created_at: datetime = Field(
        default_factory=_utcnow,
        description="Row creation timestamp (UTC)",
    )

    updated_at: datetime = Field(
        default_factory=_utcnow,
        description="Last update timestamp (UTC)",
    )
