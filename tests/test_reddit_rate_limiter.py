"""
Tests for Reddit token-bucket rate limiter and batched comment extraction.
"""

import asyncio
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

pytestmark = pytest.mark.asyncio


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  TokenBucketRateLimiter Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def test_rate_limiter_in_memory_allows_burst():
    """In-memory bucket allows up to capacity tokens immediately."""
    from app.core.rate_limiter import TokenBucketRateLimiter

    limiter = TokenBucketRateLimiter(
        key="test:burst",
        capacity=5,
        refill_rate=1.0,
        max_wait=5.0,
    )
    # Patch Redis so it's unreachable; _redis_acquire will catch this and fall back
    with patch.object(limiter, "_get_redis", side_effect=ConnectionError("Redis down")):
        start = time.monotonic()
        for _ in range(5):
            await limiter.acquire()
        elapsed = time.monotonic() - start
    # All 5 tokens should be consumed instantly from the in-memory bucket
    assert elapsed < 0.5


async def test_rate_limiter_in_memory_throttles_after_capacity():
    """In-memory bucket blocks after capacity is exhausted."""
    from app.core.rate_limiter import TokenBucketRateLimiter

    limiter = TokenBucketRateLimiter(
        key="test:throttle",
        capacity=2,
        refill_rate=10.0,   # fast refill so test doesn't hang
        max_wait=5.0,
    )
    with patch.object(limiter, "_get_redis", side_effect=ConnectionError("Redis down")):
        # Drain the bucket
        await limiter.acquire()
        await limiter.acquire()
        # Third acquire should need to wait for refill
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start

    # Should have waited at least some time for a token to refill
    assert elapsed >= 0.05


async def test_rate_limiter_timeout_raises():
    """Rate limiter raises TimeoutError when max_wait is exceeded."""
    from app.core.rate_limiter import TokenBucketRateLimiter

    limiter = TokenBucketRateLimiter(
        key="test:timeout",
        capacity=1,
        refill_rate=0.001,  # extremely slow refill
        max_wait=0.1,       # very short timeout
    )
    with patch.object(limiter, "_get_redis", side_effect=ConnectionError("Redis down")):
        # Drain the bucket
        limiter._mem_tokens = 0

        with pytest.raises(asyncio.TimeoutError):
            await limiter.acquire()


async def test_rate_limiter_redis_success():
    """Rate limiter uses Redis Lua script result correctly."""
    from app.core.rate_limiter import TokenBucketRateLimiter

    limiter = TokenBucketRateLimiter(capacity=60, refill_rate=1.0)

    # Redis grants the token
    with patch.object(limiter, "_redis_acquire", AsyncMock(return_value=True)):
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start

    assert elapsed < 0.1  # should be near-instant


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Reddit Batched Comment Extraction Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def test_fetch_top_comments_batched_returns_all_posts(mocker):
    """fetch_top_comments_batched returns a result for each requested post."""
    from app.services.external.reddit_client import (
        RedditClient, TopCommentsResponse, RedditComment,
    )

    mock_comment = RedditComment(
        comment_id="c1", author="user1", body="Hello", score=10, created_utc=0.0,
        permalink="https://reddit.com/r/test/c1",
    )
    mock_response = TopCommentsResponse(post_id="post1", count=1, comments=[mock_comment])

    with patch("app.services.external.reddit_client.praw.Reddit"):
        client = RedditClient(client_id="mock", client_secret="mock", user_agent="mock")

        with patch.object(
            client, "fetch_top_comments", AsyncMock(return_value=mock_response)
        ):
            post_ids = ["post1", "post2", "post3"]
            results = await client.fetch_top_comments_batched(post_ids, limit=10, concurrency=3)

    assert set(results.keys()) == {"post1", "post2", "post3"}
    assert results["post1"].count == 1


async def test_fetch_top_comments_batched_handles_errors(mocker):
    """fetch_top_comments_batched skips failing posts gracefully."""
    from app.services.external.reddit_client import (
        RedditClient, TopCommentsResponse, RedditComment, RedditClientError,
    )

    mock_ok = TopCommentsResponse(post_id="ok_post", count=0, comments=[])

    async def _side_effect(post_id, **kwargs):
        if post_id == "bad_post":
            raise RedditClientError("Network error")
        return mock_ok

    with patch("app.services.external.reddit_client.praw.Reddit"):
        client = RedditClient(client_id="mock", client_secret="mock", user_agent="mock")

        with patch.object(client, "fetch_top_comments", AsyncMock(side_effect=_side_effect)):
            results = await client.fetch_top_comments_batched(
                ["ok_post", "bad_post"], concurrency=2
            )

    # ok_post should succeed; bad_post should be absent (silently skipped)
    assert "ok_post" in results
    assert "bad_post" not in results


async def test_fetch_top_comments_uses_replace_more(mocker):
    """fetch_top_comments calls replace_more(limit=0) to prevent HTTP storms."""
    from app.services.external.reddit_client import RedditClient

    mock_submission = MagicMock()
    mock_submission.comment_sort = "top"
    mock_comments = MagicMock()
    mock_comments.__getitem__ = MagicMock(return_value=[])
    mock_comments.__iter__ = MagicMock(return_value=iter([]))
    mock_submission.comments = mock_comments

    with patch("app.services.external.reddit_client.praw.Reddit") as mock_praw:
        mock_praw.return_value.submission.return_value = mock_submission

        client = RedditClient(client_id="mock", client_secret="mock", user_agent="mock")

        # Patch rate limiter to allow through instantly
        with patch.object(client._rate_limiter, "acquire", AsyncMock()):
            await client.fetch_top_comments("test_post_id", limit=5)

    # Verify replace_more was called with limit=0
    mock_submission.comments.replace_more.assert_called_once_with(limit=0)


async def test_rate_limiter_called_on_reddit_fetch(mocker):
    """Every PRAW call acquires a rate-limiter token."""
    from app.services.external.reddit_client import RedditClient

    mock_submission = MagicMock()
    mock_submission.comment_sort = "top"
    mock_comments = MagicMock()
    mock_comments.__iter__ = MagicMock(return_value=iter([]))
    mock_comments.replace_more = MagicMock()
    mock_submission.comments = mock_comments

    with patch("app.services.external.reddit_client.praw.Reddit") as mock_praw:
        mock_praw.return_value.submission.return_value = mock_submission

        client = RedditClient(client_id="mock", client_secret="mock", user_agent="mock")
        acquire_mock = AsyncMock()
        with patch.object(client._rate_limiter, "acquire", acquire_mock):
            await client.fetch_top_comments("post_id", limit=5)

    # The rate limiter must have been called at least once
    acquire_mock.assert_called()
