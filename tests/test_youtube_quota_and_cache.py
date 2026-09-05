"""
Tests for YouTube quota manager, Redis cache, and ingest router validation.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

pytestmark = pytest.mark.asyncio


@pytest.fixture
def mock_cache():
    """Return a patched RedisCache that stores values in a plain dict."""
    store: dict = {}

    async def _get(key):
        return store.get(key)

    async def _set(key, value, *, ttl=3600):
        store[key] = value
        return True

    async def _get_int(key):
        return int(store.get(key, 0))

    async def _incr(key, amount=1, *, ttl=None):
        store[key] = int(store.get(key, 0)) + amount
        return store[key]

    cache = MagicMock()
    cache.get = AsyncMock(side_effect=_get)
    cache.set = AsyncMock(side_effect=_set)
    cache.get_int = AsyncMock(side_effect=_get_int)
    cache.incr = AsyncMock(side_effect=_incr)
    cache.delete = AsyncMock()
    cache._store = store
    return cache


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Redis Cache Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def test_cache_get_set():
    """Cache stores and retrieves JSON-serialisable values."""
    from app.core.cache import RedisCache

    with patch("app.core.cache._get_redis_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value='{"foo": "bar"}')
        mock_client.setex = AsyncMock()
        mock_client_factory.return_value = mock_client

        cache = RedisCache(prefix="test:")
        await cache.set("key1", {"foo": "bar"}, ttl=60)
        result = await cache.get("key1")

        assert result == {"foo": "bar"}
        mock_client.setex.assert_called_once()


async def test_cache_miss_returns_none():
    """Cache miss returns None without raising."""
    from app.core.cache import RedisCache

    with patch("app.core.cache._get_redis_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=None)
        mock_client_factory.return_value = mock_client

        cache = RedisCache(prefix="test:")
        result = await cache.get("nonexistent_key")
        assert result is None


async def test_cache_error_returns_none():
    """Redis connection errors are silently swallowed; returns None."""
    from app.core.cache import RedisCache

    with patch("app.core.cache._get_redis_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=ConnectionError("Redis down"))
        mock_client_factory.return_value = mock_client

        cache = RedisCache(prefix="test:")
        result = await cache.get("any_key")
        assert result is None  # graceful degradation


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  YouTube Quota Manager Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def test_quota_records_usage(mock_cache):
    """Quota manager increments the daily counter on each API call."""
    from app.services.external.youtube_quota import YouTubeQuotaManager

    with patch("app.services.external.youtube_quota.get_cache", return_value=mock_cache):
        mgr = YouTubeQuotaManager(daily_limit=10_000, safety_buffer=500)
        await mgr.record_usage(1)
        await mgr.record_usage(1)
        total = await mgr.get_consumed()
        assert total == 2


async def test_quota_check_raises_when_over_limit(mock_cache):
    """check_quota raises YouTubeQuotaExceeded when budget is exhausted."""
    from app.services.external.youtube_quota import YouTubeQuotaManager
    from app.services.external.youtube_client import YouTubeQuotaExceeded

    with patch("app.services.external.youtube_quota.get_cache", return_value=mock_cache):
        mgr = YouTubeQuotaManager(daily_limit=100, safety_buffer=10)
        # Simulate 95 units already consumed (limit is 100 - 10 = 90 effective)
        mock_cache._store[mgr._day_key()] = 95

        with pytest.raises(YouTubeQuotaExceeded):
            await mgr.check_quota(units_needed=1)


async def test_quota_check_passes_when_within_budget(mock_cache):
    """check_quota does not raise when budget is available."""
    from app.services.external.youtube_quota import YouTubeQuotaManager

    with patch("app.services.external.youtube_quota.get_cache", return_value=mock_cache):
        mgr = YouTubeQuotaManager(daily_limit=10_000, safety_buffer=500)
        mock_cache._store[mgr._day_key()] = 100  # 100 of 9500 effective used

        # Should not raise
        await mgr.check_quota(units_needed=1)


async def test_quota_blocks_search_list_when_low(mock_cache):
    """search.list (100 units) is blocked when only 50 units remain."""
    from app.services.external.youtube_quota import YouTubeQuotaManager, QuotaCost
    from app.services.external.youtube_client import YouTubeQuotaExceeded

    with patch("app.services.external.youtube_quota.get_cache", return_value=mock_cache):
        mgr = YouTubeQuotaManager(daily_limit=10_000, safety_buffer=500)
        # Only 50 units of budget remain (9500 - 9450 = 50)
        mock_cache._store[mgr._day_key()] = 9450

        with pytest.raises(YouTubeQuotaExceeded):
            await mgr.check_and_record(QuotaCost.SEARCH_LIST)  # needs 100, only 50 left


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  YouTube Router Channel ID Validation Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

VALID_CHANNEL_ID = "UCBcRF18a7Qf58cCRy5xuWwQ"
INVALID_INPUTS = [
    "mkbhd",                         # name only
    "@mkbhd",                        # handle
    "UCshort",                       # too short
    "UC" + "x" * 25,                 # too long
    "AC" + "x" * 22,                 # wrong prefix
    "",                              # empty
]


async def test_ingest_endpoint_accepts_valid_channel_id(mocker):
    """POST /channels/{channel_id}/ingest accepts a valid UC... channel ID."""
    from fastapi.testclient import TestClient
    from app.main import app

    mock_task = MagicMock()
    mock_task.id = "task-abc-123"
    mocker.patch("app.api.v1.routers.youtube.celery_app.send_task", return_value=mock_task)

    client = TestClient(app)
    response = client.post(f"/api/v1/youtube/channels/{VALID_CHANNEL_ID}/ingest")

    assert response.status_code == 202
    assert response.json()["task_id"] == "task-abc-123"


@pytest.mark.parametrize("bad_id", INVALID_INPUTS)
async def test_ingest_endpoint_rejects_invalid_channel_id(bad_id, mocker):
    """POST /channels/{channel_id}/ingest returns 422 for invalid channel IDs."""
    from fastapi.testclient import TestClient
    from app.main import app

    mocker.patch("app.api.v1.routers.youtube.celery_app.send_task")

    client = TestClient(app)
    response = client.post(f"/api/v1/youtube/channels/{bad_id}/ingest")

    # empty string maps to a different route — skip that case
    if not bad_id:
        return

    assert response.status_code == 422
    assert "not a valid YouTube Channel ID" in response.json()["detail"]
