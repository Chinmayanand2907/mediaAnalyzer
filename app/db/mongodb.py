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

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorCollection,
    AsyncIOMotorDatabase,
)

from app.core.config import get_settings

import certifi

# ─── Settings ────────────────────────────────────────────────────
settings = get_settings()

# ─── Module-level singleton ──────────────────────────────────────
_client: AsyncIOMotorClient | None = None


# ─── Lifecycle Functions ─────────────────────────────────────────

async def connect_mongo() -> None:
    """Initialize the Motor client and verify connectivity.

    Call once during application startup (e.g. inside the FastAPI
    lifespan handler).  The underlying connection pool is created
    lazily by Motor, but issuing a ``ping`` command here lets us
    fail fast if MongoDB is unreachable.
    """
    global _client
    _client = AsyncIOMotorClient(
        settings.MONGO_URI,
        maxPoolSize=50,              # max connections in the pool
        minPoolSize=5,               # keep at least 5 connections warm
        serverSelectionTimeoutMS=5000,  # fail fast if host is unreachable
        tlsCAFile=certifi.where(),   # load trusted root certs (crucial for macOS/Atlas)
    )

    # Verify the server is reachable (raises on failure)
    await _client.admin.command("ping")
    print(f"✅  MongoDB connected → {settings.MONGO_URI}/{settings.MONGO_DB}")


async def close_mongo() -> None:
    """Gracefully close the Motor client.

    Call during application shutdown to release all pooled
    connections.
    """
    global _client
    if _client is not None:
        _client.close()
        _client = None
        print("🛑  MongoDB connection closed.")


# ─── Database & Collection Accessors ─────────────────────────────

def get_mongo_db() -> AsyncIOMotorDatabase:
    """Return the configured MongoDB database handle.

    Raises ``RuntimeError`` if called before ``connect_mongo()``.
    """
    if _client is None:
        raise RuntimeError(
            "MongoDB client is not initialized. "
            "Call 'connect_mongo()' during application startup first."
        )
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

    print("📇  MongoDB indexes ensured.")
