"""
app/core/cache.py
=================
Async Redis cache wrapper.

Usage
-----
    from app.core.cache import get_cache

    cache = get_cache()
    await cache.set("my:key", {"data": 1}, ttl=3600)
    value = await cache.get("my:key")   # dict or None
    await cache.delete("my:key")

Design
------
* All values are JSON-serialised, so any JSON-safe Python object can be stored.
* If the Redis connection is unavailable the helpers log a warning and return
  None / no-op so that the caller degrades gracefully to a cache-miss rather
  than crashing the ingestion pipeline.
* A singleton ``_redis`` client is created lazily on first use and reused
  across async tasks running in the same process.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Module-level lazy singleton
# ---------------------------------------------------------------------------
_redis: aioredis.Redis | None = None


def _get_redis_client() -> aioredis.Redis:
    """Return (and lazily create) the process-level Redis async client."""
    global _redis
    if _redis is None:
        settings = get_settings()
        _redis = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
    return _redis


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class RedisCache:
    """Thin async Redis cache helper.

    Parameters
    ----------
    prefix:
        Namespace prefix automatically prepended to every key
        (e.g. ``"yt:"``).  Helps avoid cross-feature key collisions.
    """

    def __init__(self, prefix: str = "") -> None:
        self._prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self._prefix}{key}"

    async def get(self, key: str) -> Any | None:
        """Return the cached value for *key*, or ``None`` on miss / error."""
        try:
            client = _get_redis_client()
            raw = await client.get(self._key(key))
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.warning("Cache GET error for '%s': %s", key, exc)
            return None

    async def set(self, key: str, value: Any, *, ttl: int = 3600) -> bool:
        """Store *value* under *key* with the given TTL (seconds).

        Returns
        -------
        bool
            ``True`` if the value was stored, ``False`` on error.
        """
        try:
            client = _get_redis_client()
            serialised = json.dumps(value, default=str)
            await client.setex(self._key(key), ttl, serialised)
            return True
        except Exception as exc:
            logger.warning("Cache SET error for '%s': %s", key, exc)
            return False

    async def delete(self, *keys: str) -> None:
        """Delete one or more keys (errors are silently swallowed)."""
        try:
            client = _get_redis_client()
            full_keys = [self._key(k) for k in keys]
            await client.delete(*full_keys)
        except Exception as exc:
            logger.warning("Cache DELETE error: %s", exc)

    async def exists(self, key: str) -> bool:
        """Return ``True`` if *key* currently exists in the cache."""
        try:
            client = _get_redis_client()
            return bool(await client.exists(self._key(key)))
        except Exception as exc:
            logger.warning("Cache EXISTS error for '%s': %s", key, exc)
            return False

    async def incr(self, key: str, amount: int = 1, *, ttl: int | None = None) -> int:
        """Atomically increment a counter and optionally set a TTL on first creation.

        Returns the new value, or 0 on error.
        """
        try:
            client = _get_redis_client()
            full_key = self._key(key)
            pipe = client.pipeline()
            pipe.incrby(full_key, amount)
            if ttl is not None:
                # Only set TTL if the key doesn't already have one (new key).
                pipe.expire(full_key, ttl, nx=True)
            results = await pipe.execute()
            return int(results[0])
        except Exception as exc:
            logger.warning("Cache INCR error for '%s': %s", key, exc)
            return 0

    async def get_int(self, key: str) -> int:
        """Return cached integer value, or 0 on miss / error."""
        try:
            client = _get_redis_client()
            raw = await client.get(self._key(key))
            return int(raw) if raw is not None else 0
        except Exception as exc:
            logger.warning("Cache GET_INT error for '%s': %s", key, exc)
            return 0

    async def ttl(self, key: str) -> int:
        """Return the remaining TTL (seconds) for *key*, or -2 if not found."""
        try:
            client = _get_redis_client()
            return await client.ttl(self._key(key))
        except Exception as exc:
            logger.warning("Cache TTL error for '%s': %s", key, exc)
            return -2


# ---------------------------------------------------------------------------
# Convenience factory
# ---------------------------------------------------------------------------

def get_cache(prefix: str = "") -> RedisCache:
    """Return a ``RedisCache`` instance with the given namespace prefix."""
    return RedisCache(prefix=prefix)
