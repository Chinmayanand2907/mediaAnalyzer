"""
Social Media Engagement Analyzer — Configuration

Uses Pydantic v2 BaseSettings to load and validate all environment
variables. Settings are loaded once at import time and re-used via
the cached ``get_settings()`` helper.

Usage:
    from app.core.config import get_settings
    settings = get_settings()
"""

from functools import lru_cache
from typing import Literal, List, Optional

from pydantic import Field, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration — every field maps to an env variable."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────
    APP_NAME: str = "Social Media Engagement Analyzer"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = False  # Never default to True — SQL echo leaks queries in production

    # ── CORS ────────────────────────────────────────────────
    ALLOWED_ORIGINS: List[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173", "http://127.0.0.1:3000", "http://127.0.0.1:5173"],
        description=(
            "CORS allowed origins. Set via ALLOWED_ORIGINS env var as a JSON array. "
            "In production include your Vercel domain, e.g. "
            '[\"https://your-app.vercel.app\"]'
        ),
    )

    # ── PostgreSQL ───────────────────────────────────────────
    # For hosted providers (Neon.tech, Supabase, etc.) you can supply the
    # full connection string as DATABASE_URL and it will take precedence over
    # the individual host/user/password components below.
    # Expected format (asyncpg):
    #   postgresql+asyncpg://user:pass@host/db?ssl=require
    # Neon's default URL uses the plain postgres:// scheme — the computed
    # property normalises it automatically.
    DATABASE_URL: Optional[str] = Field(
        default=None,
        description=(
            "Full async DSN (postgresql+asyncpg://...). "
            "Takes precedence over POSTGRES_USER/PASSWORD/HOST/PORT/DB when set."
        ),
    )

    POSTGRES_USER: str = "analyzer"
    POSTGRES_PASSWORD: str = "changeme"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "engagement_analyzer"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def POSTGRES_DSN(self) -> str:
        """Build the async PostgreSQL connection string.

        If DATABASE_URL is set (e.g. from Neon.tech), normalise it to the
        asyncpg dialect and return it directly.  Otherwise construct the DSN
        from the individual POSTGRES_* fields.
        """
        if self.DATABASE_URL:
            dsn = self.DATABASE_URL
            # Neon provides postgres:// or postgresql:// — upgrade to asyncpg dialect.
            if dsn.startswith("postgres://"):
                dsn = dsn.replace("postgres://", "postgresql+asyncpg://", 1)
            elif dsn.startswith("postgresql://"):
                dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
            # asyncpg accepts ssl= in query params, not sslmode=
            dsn = dsn.replace("sslmode=", "ssl=")
            if "ssl=" not in dsn:
                separator = "&" if "?" in dsn else "?"
                dsn = f"{dsn}{separator}ssl=require"
            return dsn
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def POSTGRES_DSN_SYNC(self) -> str:
        """Synchronous DSN for Alembic migrations and ad-hoc scripts."""
        if self.DATABASE_URL:
            dsn = self.DATABASE_URL
            if dsn.startswith("postgres://"):
                dsn = dsn.replace("postgres://", "postgresql+psycopg://", 1)
            elif dsn.startswith("postgresql://"):
                dsn = dsn.replace("postgresql://", "postgresql+psycopg://", 1)
            elif dsn.startswith("postgresql+asyncpg://"):
                dsn = dsn.replace("postgresql+asyncpg://", "postgresql+psycopg://", 1)
            # psycopg expects sslmode=, not ssl=
            if "ssl=" in dsn and "sslmode=" not in dsn:
                dsn = dsn.replace("ssl=", "sslmode=")
            if "sslmode=" not in dsn:
                separator = "&" if "?" in dsn else "?"
                dsn = f"{dsn}{separator}sslmode=require"
            return dsn
        return (
            f"postgresql+psycopg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    # ── MongoDB ──────────────────────────────────────────────
    MONGO_URI: str = "mongodb://localhost:27017"
    MONGO_DB: str = "engagement_raw"

    # ── Redis / Celery ───────────────────────────────────────
    REDIS_URL: str = "redis://localhost:6379/0"
    CELERY_BROKER_URL: str = "redis://localhost:6379/1"
    CELERY_RESULT_BACKEND: str = "redis://localhost:6379/2"

    # ── YouTube Data API v3 ──────────────────────────────────
    YOUTUBE_API_KEY: str = Field(
        default="",
        description="Google Cloud API key with YouTube Data API v3 enabled",
    )
    YOUTUBE_CACHE_TTL: int = Field(
        default=3600,
        description="TTL in seconds for cached YouTube API responses (1 hour).",
    )
    YOUTUBE_DAILY_QUOTA_LIMIT: int = Field(
        default=10_000,
        description="YouTube Data API v3 daily quota limit in units.",
    )
    YOUTUBE_QUOTA_SAFETY_BUFFER: int = Field(
        default=500,
        description=(
            "Units reserved as a safety buffer. Proactive gating kicks in when "
            "consumed >= YOUTUBE_DAILY_QUOTA_LIMIT - YOUTUBE_QUOTA_SAFETY_BUFFER."
        ),
    )

    # ── Reddit API (PRAW) ────────────────────────────────────────────────────
    REDDIT_CLIENT_ID: str = Field(default="", description="Reddit OAuth2 client ID")
    REDDIT_CLIENT_SECRET: str = Field(default="", description="Reddit OAuth2 secret")
    REDDIT_USER_AGENT: str = "EngagementAnalyzer/1.0"
    REDDIT_RATE_LIMIT_CALLS_PER_MIN: int = Field(
        default=60,
        description="Reddit API max requests per minute (token-bucket capacity).",
    )

    # ── River.ai LLM (Chatbot) ───────────────────────────────────────────────
    RIVER_API_KEY: str = Field(
        default="",
        description="River.ai API key — get one at https://river.ai",
    )
    RIVER_MODEL: str = Field(
        default="deepseek-ai/DeepSeek-V4.1-Flash",
        description=(
            "River.ai model name used by the chatbot endpoint. "
            "Override in .env — e.g. RIVER_MODEL=deepseek-ai/DeepSeek-V4.1-Flash"
        ),
    )


    # ── Semantic Matching (Sentence-BERT) ────────────────────────────────────
    SEMANTIC_SIMILARITY_THRESHOLD: float = Field(
        default=0.55,
        description="Cosine similarity threshold (0.0-1.0) for semantic cross-platform matching.",
    )
    SEMANTIC_EMBEDDING_MODEL: str = Field(
        default="all-MiniLM-L6-v2",
        description="SentenceTransformer model name used for semantic cross-platform linking.",
    )



@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton.

    Call ``get_settings.cache_clear()`` in tests to inject overrides.
    """
    return Settings()
