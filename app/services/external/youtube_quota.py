"""
app/services/external/youtube_quota.py
=======================================
YouTube Data API v3 daily quota tracker.

YouTube grants 10,000 units per day (per project).  Different endpoints cost
different amounts:
    search.list            → 100 units  ← THE expensive one to avoid
    channels.list          →   1 unit
    playlistItems.list     →   1 unit
    videos.list            →   1 unit
    commentThreads.list    →   1 unit

This module tracks consumed units in Redis so all Celery workers share the
same budget view, raises ``YouTubeQuotaExceeded`` proactively when the safety
buffer is about to be breached, and exposes helpers to log each API call's cost.

Usage
-----
    from app.services.external.youtube_quota import YouTubeQuotaManager

    quota = YouTubeQuotaManager()

    # Before an expensive call:
    await quota.check_and_record(QuotaCost.SEARCH_LIST)

    # After any call (record without pre-check):
    await quota.record_usage(QuotaCost.DEFAULT)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import IntEnum

from app.core.cache import get_cache
from app.services.external.youtube_client import YouTubeQuotaExceeded

logger = logging.getLogger(__name__)

# One day in seconds — used to expire the Redis quota counter at midnight.
_DAY_TTL = 86_400


class QuotaCost(IntEnum):
    """API call costs in YouTube quota units."""
    SEARCH_LIST = 100      # search().list()  — avoid unless absolutely necessary
    DEFAULT = 1            # channels/videos/commentThreads/playlistItems .list()


class YouTubeQuotaManager:
    """Track and gate daily YouTube API quota usage.

    Parameters
    ----------
    daily_limit:
        Total daily quota units available (default 10 000).
    safety_buffer:
        Units reserved for unexpected calls / retries.  Proactive gating kicks
        in when ``consumed >= daily_limit - safety_buffer``.
    """

    def __init__(
        self,
        daily_limit: int | None = None,
        safety_buffer: int | None = None,
    ) -> None:
        from app.core.config import get_settings
        settings = get_settings()
        # Use explicit arg when provided; otherwise fall back to settings / hardcoded defaults.
        self._daily_limit = (
            daily_limit if daily_limit is not None
            else int(getattr(settings, "YOUTUBE_DAILY_QUOTA_LIMIT", 10_000))
        )
        self._safety_buffer = (
            safety_buffer if safety_buffer is not None
            else int(getattr(settings, "YOUTUBE_QUOTA_SAFETY_BUFFER", 500))
        )
        self._cache = get_cache(prefix="yt:quota:")

    def _day_key(self) -> str:
        """Redis key scoped to the current UTC date (resets automatically)."""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    @property
    def _effective_limit(self) -> int:
        return self._daily_limit - self._safety_buffer

    async def get_consumed(self) -> int:
        """Return the number of quota units consumed today."""
        return await self._cache.get_int(self._day_key())

    async def get_remaining(self) -> int:
        """Return the remaining usable quota units for today."""
        return max(0, self._effective_limit - await self.get_consumed())

    async def record_usage(self, cost: int = QuotaCost.DEFAULT) -> int:
        """Increment the daily counter by *cost* units.

        Returns the new total consumed today.
        """
        new_total = await self._cache.incr(self._day_key(), cost, ttl=_DAY_TTL)
        logger.debug(
            "[QuotaManager] +%d units recorded — total today: %d / %d",
            cost, new_total, self._daily_limit,
        )
        return new_total

    async def check_quota(self, units_needed: int = QuotaCost.DEFAULT) -> None:
        """Raise ``YouTubeQuotaExceeded`` if *units_needed* exceeds the remaining budget.

        Should be called **before** making an expensive API call.
        """
        consumed = await self.get_consumed()
        if consumed + units_needed > self._effective_limit:
            remaining = max(0, self._effective_limit - consumed)
            raise YouTubeQuotaExceeded(
                f"YouTube API daily quota safety limit reached. "
                f"Consumed: {consumed}/{self._daily_limit} units today. "
                f"Remaining budget: {remaining} units "
                f"(safety buffer: {self._safety_buffer}). "
                "Quota resets at midnight Pacific Time.",
                status_code=429,
            )

    async def check_and_record(self, cost: int = QuotaCost.DEFAULT) -> int:
        """Check quota availability then record usage atomically.

        Parameters
        ----------
        cost:
            Cost of the upcoming API call in quota units.

        Returns
        -------
        int
            New cumulative units consumed today.

        Raises
        ------
        YouTubeQuotaExceeded
            If the call would exceed the effective daily limit.
        """
        await self.check_quota(cost)
        return await self.record_usage(cost)

    async def status(self) -> dict:
        """Return a dict summarising today's quota usage (for logging / monitoring)."""
        consumed = await self.get_consumed()
        return {
            "date": self._day_key(),
            "consumed": consumed,
            "daily_limit": self._daily_limit,
            "safety_buffer": self._safety_buffer,
            "effective_limit": self._effective_limit,
            "remaining": max(0, self._effective_limit - consumed),
            "pct_used": round(consumed / self._daily_limit * 100, 1),
        }
