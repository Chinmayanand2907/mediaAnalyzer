"""
app/core/rate_limiter.py
========================
Token-bucket rate limiter for Reddit API calls.

Design
------
* Each "token" corresponds to one Reddit API request.
* Tokens refill at a constant rate (default: 60 tokens per minute = 1/sec).
* A distributed Redis Lua script guarantees atomic token consumption across
  multiple Celery workers sharing the same Redis instance.
* If Redis is unavailable, falls back to a simple asyncio-based in-memory
  limiter so ingestion continues (at reduced throughput) rather than crashing.

Usage
-----
    from app.core.rate_limiter import get_reddit_rate_limiter

    limiter = get_reddit_rate_limiter()
    await limiter.acquire()       # wait for a token before making a PRAW call
    ...                            # make the PRAW call
"""

from __future__ import annotations

import asyncio
import logging
import time

import redis.asyncio as aioredis

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lua script for atomic token-bucket consume in Redis
# ---------------------------------------------------------------------------
_LUA_TOKEN_BUCKET = """
local key        = KEYS[1]
local capacity   = tonumber(ARGV[1])
local refill_rate = tonumber(ARGV[2])   -- tokens per second
local requested  = tonumber(ARGV[3])
local now        = tonumber(ARGV[4])    -- unix epoch as float

-- Read existing state
local data = redis.call('HMGET', key, 'tokens', 'last_refill')
local tokens     = tonumber(data[1])
local last_refill = tonumber(data[2])

if tokens == nil then
    tokens      = capacity
    last_refill = now
end

-- Refill tokens based on elapsed time
local elapsed = math.max(0, now - last_refill)
tokens = math.min(capacity, tokens + elapsed * refill_rate)

if tokens >= requested then
    tokens = tokens - requested
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 120)
    return 1    -- granted
else
    redis.call('HMSET', key, 'tokens', tokens, 'last_refill', now)
    redis.call('EXPIRE', key, 120)
    return 0    -- denied
end
"""


class TokenBucketRateLimiter:
    """Distributed token-bucket rate limiter backed by Redis.

    Parameters
    ----------
    key:
        Redis key for this limiter (should be unique per API / resource).
    capacity:
        Maximum number of tokens the bucket can hold.
    refill_rate:
        Tokens added per second (e.g. 1.0 for 60 req/min).
    max_wait:
        Maximum time (seconds) to wait for a token before raising
        ``asyncio.TimeoutError``.
    """

    def __init__(
        self,
        key: str = "rate_limiter:reddit",
        capacity: int = 60,
        refill_rate: float = 1.0,
        max_wait: float = 60.0,
    ) -> None:
        self._key = key
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._max_wait = max_wait
        self._script: aioredis.client.Script | None = None

        # In-memory fallback state
        self._mem_tokens: float = float(capacity)
        self._mem_last_refill: float = time.monotonic()
        self._mem_lock = asyncio.Lock()

    def _get_redis(self) -> aioredis.Redis:
        settings = get_settings()
        return aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            socket_connect_timeout=2,
            socket_timeout=2,
        )

    async def _redis_acquire(self) -> bool:
        """Try to consume one token from Redis. Returns True if granted."""
        try:
            client = self._get_redis()
            if self._script is None:
                self._script = client.register_script(_LUA_TOKEN_BUCKET)
            result = await self._script(
                keys=[self._key],
                args=[self._capacity, self._refill_rate, 1, time.time()],
            )
            return bool(result)
        except Exception as exc:
            logger.warning("Rate limiter Redis error — falling back to in-memory: %s", exc)
            return await self._mem_acquire()

    async def _mem_acquire(self) -> bool:
        """Attempt to consume a token from the in-memory bucket (fallback)."""
        async with self._mem_lock:
            now = time.monotonic()
            elapsed = now - self._mem_last_refill
            self._mem_tokens = min(
                self._capacity,
                self._mem_tokens + elapsed * self._refill_rate,
            )
            self._mem_last_refill = now

            if self._mem_tokens >= 1:
                self._mem_tokens -= 1
                return True
            return False

    async def acquire(self, tokens: int = 1) -> None:
        """Block until *tokens* token(s) are available, then consume them.

        Raises
        ------
        asyncio.TimeoutError
            If the wait exceeds ``max_wait`` seconds.
        """
        deadline = time.monotonic() + self._max_wait
        sleep_interval = 0.05  # 50 ms initial poll interval

        while True:
            granted = await self._redis_acquire()
            if granted:
                return

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise asyncio.TimeoutError(
                    f"Rate limiter '{self._key}' timed out after {self._max_wait}s"
                )

            # Exponential backoff capped at 1 second
            await asyncio.sleep(min(sleep_interval, remaining, 1.0))
            sleep_interval = min(sleep_interval * 2, 1.0)


# ---------------------------------------------------------------------------
# Singleton factory
# ---------------------------------------------------------------------------
_reddit_limiter: TokenBucketRateLimiter | None = None


def get_reddit_rate_limiter() -> TokenBucketRateLimiter:
    """Return the process-level Reddit rate limiter (lazy singleton)."""
    global _reddit_limiter
    if _reddit_limiter is None:
        settings = get_settings()
        calls_per_min: int = getattr(settings, "REDDIT_RATE_LIMIT_CALLS_PER_MIN", 60)
        _reddit_limiter = TokenBucketRateLimiter(
            key="rate_limiter:reddit",
            capacity=calls_per_min,
            refill_rate=calls_per_min / 60.0,
            max_wait=60.0,
        )
    return _reddit_limiter
