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
from typing import Literal

from pydantic import Field, MongoDsn, computed_field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Central configuration — every field maps to an env variable."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Application ──────────────────────────────────────────
    APP_NAME: str = "Social Media Engagement Analyzer"
    APP_ENV: Literal["development", "staging", "production"] = "development"
    DEBUG: bool = True

    # ── PostgreSQL ───────────────────────────────────────────
    POSTGRES_USER: str = "analyzer"
    POSTGRES_PASSWORD: str = "changeme"
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_DB: str = "engagement_analyzer"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def POSTGRES_DSN(self) -> str:
        """Build the async PostgreSQL connection string."""
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DB}"
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def POSTGRES_DSN_SYNC(self) -> str:
        """Synchronous DSN for Alembic migrations and ad-hoc scripts."""
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

    # ── Reddit API (PRAW) ────────────────────────────────────────────────────
    REDDIT_CLIENT_ID: str = Field(default="", description="Reddit OAuth2 client ID")
    REDDIT_CLIENT_SECRET: str = Field(default="", description="Reddit OAuth2 secret")
    REDDIT_USER_AGENT: str = "EngagementAnalyzer/1.0"

    # ── Groq Cloud LLM ───────────────────────────────────────────────────────────────
    GROQ_API_KEY: str = Field(
        default="",
        description="Groq Cloud API key — get one at console.groq.com",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings singleton.

    Call ``get_settings.cache_clear()`` in tests to inject overrides.
    """
    return Settings()
