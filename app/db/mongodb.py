"""
MongoDB connection layer (async) — Motor + AsyncIOMotorClient.

Provides:
    - ``connect_mongo``  — initializes the Motor client (call at startup)
    - ``close_mongo``    — gracefully closes the connection (call at shutdown)
    - ``get_mongo_db``   — returns the configured database handle
    - Collection helpers for raw document storage:
        • ``get_comments_collection``
        • ``get_video_payloads_collection``

Usage in a FastAPI route::

    from app.db.mongodb import get_mongo_db

    @router.get("/raw/comments")
    async def list_comments():
        db = get_mongo_db()
        docs = await db["comments"].find().to_list(length=50)
        return docs
"""

from __future__ import annotations
import logging

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)

from app.core.config import get_settings

import certifi

logger = logging.getLogger(__name__)

# ─── Settings ────────────────────────────────────────────────────
settings = get_settings()

# ─── Shared Motor client kwargs ───────────────────────────────────
# Single source of truth — used by both connect_mongo() and get_mongo_db()
# so the lazy-init path (e.g. Celery tasks, tests) always has full TLS config.
_MONGO_CLIENT_KWARGS: dict = dict(
    maxPoolSize=50,
    minPoolSize=1,
    serverSelectionTimeoutMS=5000,
    connectTimeoutMS=5000,
    tlsCAFile=certifi.where(),       # trusted root certs — crucial for Atlas / macOS
)

# ─── Module-level singleton ──────────────────────────────────────
_client: AsyncIOMotorClient | None = None


# ─── Lifecycle Functions ─────────────────────────────────────────

async def connect_mongo() -> None:
    """Initialize the Motor client and verify connectivity."""
    global _client
    if _client is not None:
        try:
            await _client.admin.command("ping")
            return
        except Exception:
            try:
                _client.close()
            except Exception:
                pass
            _client = None

    _client = AsyncIOMotorClient(settings.MONGO_URI, **_MONGO_CLIENT_KWARGS)

    try:
        # Force a connection check
        await _client.admin.command("ping")
        logger.info(f"✅  MongoDB connected → {settings.MONGO_URI}/{settings.MONGO_DB}")
    except Exception as e:
        logger.warning(f"⚠️  MongoDB connection warning (will retry lazily on query): {e}")


async def close_mongo() -> None:
    """Gracefully close the Motor client."""
    global _client
    if _client is not None:
        _client.close()
        _client = None
        logger.info("🛑  MongoDB connection closed.")


def get_mongo_db() -> AsyncIOMotorDatabase:
    """Return the configured MongoDB database handle.

    Uses the same shared _MONGO_CLIENT_KWARGS as connect_mongo() so
    lazy initialization (called before lifespan, in tests or Celery tasks)
    always uses the correct TLS certifi configuration.
    """
    global _client
    if _client is None:
        _client = AsyncIOMotorClient(settings.MONGO_URI, **_MONGO_CLIENT_KWARGS)
    return _client[settings.MONGO_DB]


def get_comments_collection() -> AsyncIOMotorCollection:
    """Return the ``comments`` collection.

    Stores raw comment payloads from YouTube and Reddit as-is,
    preserving the original JSON structure for flexible querying.

    Suggested document structure::

        {
            "platform": "youtube" | "reddit",
            "platform_id": "<native comment id>",
            "parent_id": "<video id / post id>",
            "author": "...",
            "body": "...",
            "published_at": "...",
            "raw": { <full API response> },
            "ingested_at": <ISODate>,
        }
    """
    return get_mongo_db()["comments"]


def get_video_payloads_collection() -> AsyncIOMotorCollection:
    """Return the ``video_payloads`` collection.

    Stores full video / post metadata snapshots from platform APIs.

    Suggested document structure::

        {
            "platform": "youtube" | "reddit",
            "platform_id": "<video id / post id>",
            "title": "...",
            "stats": { "views": ..., "likes": ..., ... },
            "raw": { <full API response> },
            "ingested_at": <ISODate>,
        }
    """
    return get_mongo_db()["video_payloads"]


async def ensure_indexes() -> None:
    """Create indexes on commonly queried fields.

    Call during startup after ``connect_mongo()`` to guarantee
    fast lookups without manual intervention.
    """
    db = get_mongo_db()

    # ── Comments collection ──────────────────────────────────
    comments = db["comments"]
    await comments.create_index("platform")
    await comments.create_index("platform_id", unique=True)
    await comments.create_index("parent_id")
    await comments.create_index("ingested_at")

    # ── Video payloads collection ────────────────────────────
    payloads = db["video_payloads"]
    await payloads.create_index("platform")
    await payloads.create_index("platform_id", unique=True)
    await payloads.create_index("ingested_at")

    logger.info("📇  MongoDB indexes ensured.")
