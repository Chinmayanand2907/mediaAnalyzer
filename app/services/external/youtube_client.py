"""
YouTube Data API v3 — async service wrapper.

Wraps the synchronous ``google-api-python-client`` with
``asyncio.to_thread`` so every call is non-blocking.

Public interface
────────────────
    client = YouTubeClient()

    video  = await client.fetch_video_metadata("dQw4w9WgXcQ")
    videos = await client.fetch_channel_videos("UC...channelId", max_results=10)
    thread = await client.fetch_comment_threads("dQw4w9WgXcQ", max_results=25)

All methods return **Pydantic v2 models** for type-safe downstream use.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Optional

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from pydantic import BaseModel, Field

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Pydantic Response Schemas
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class VideoStatistics(BaseModel):
    """Numeric engagement counters for a single video."""
    view_count: int = 0
    like_count: int = 0
    comment_count: int = 0
    favorite_count: int = 0


class VideoMetadata(BaseModel):
    """Structured metadata for a single YouTube video."""
    video_id: str
    title: str
    description: str = ""
    channel_id: str = ""
    channel_title: str = ""
    published_at: Optional[str] = None
    tags: list[str] = Field(default_factory=list)
    category_id: Optional[str] = None
    duration: Optional[str] = None
    thumbnail_url: Optional[str] = None
    statistics: VideoStatistics = Field(default_factory=VideoStatistics)
    raw: dict = Field(
        default_factory=dict,
        description="Full unprocessed API response item",
    )


class ChannelVideoItem(BaseModel):
    """Lightweight reference to a video found via channel search."""
    video_id: str
    title: str
    description: str = ""
    published_at: Optional[str] = None
    thumbnail_url: Optional[str] = None


class ChannelVideosResponse(BaseModel):
    """Paginated list of videos returned from a channel query."""
    channel_id: str
    total_results: int = 0
    next_page_token: Optional[str] = None
    videos: list[ChannelVideoItem] = Field(default_factory=list)


class CommentItem(BaseModel):
    """A single comment (top-level or reply)."""
    comment_id: str
    author_name: str = ""
    author_channel_id: Optional[str] = None
    text: str = ""
    like_count: int = 0
    published_at: Optional[str] = None
    updated_at: Optional[str] = None


class CommentThread(BaseModel):
    """A top-level comment and its replies."""
    thread_id: str
    top_comment: CommentItem
    reply_count: int = 0
    replies: list[CommentItem] = Field(default_factory=list)


class CommentThreadsResponse(BaseModel):
    """Paginated batch of comment threads for a video."""
    video_id: str
    next_page_token: Optional[str] = None
    threads: list[CommentThread] = Field(default_factory=list)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Custom Exceptions
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class YouTubeAPIError(Exception):
    """Raised when the YouTube API returns a non-retryable error."""

    def __init__(self, message: str, status_code: int | None = None):
        self.status_code = status_code
        super().__init__(message)


class YouTubeQuotaExceeded(YouTubeAPIError):
    """Raised when the daily API quota has been exhausted."""


class YouTubeNotFound(YouTubeAPIError):
    """Raised when the requested resource does not exist."""


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Client
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# Retry configuration
_MAX_RETRIES = 3
_RETRY_BACKOFF_BASE = 2  # seconds


class YouTubeClient:
    """Async wrapper around the YouTube Data API v3.

    Parameters
    ----------
    api_key : str | None
        Explicit API key.  Falls back to ``Settings.YOUTUBE_API_KEY``
        when not provided.
    """

    def __init__(self, api_key: str | None = None) -> None:
        settings = get_settings()
        self._api_key = api_key or settings.YOUTUBE_API_KEY
        if not self._api_key:
            raise ValueError(
                "YouTube API key is required. Set YOUTUBE_API_KEY in your "
                ".env file or pass it directly to YouTubeClient()."
            )
        # Build the service object (thread-safe for read-only calls)
        self._service = build(
            "youtube", "v3",
            developerKey=self._api_key,
            cache_discovery=False,
        )

    # ── internal helpers ─────────────────────────────────────

    async def _execute_with_retry(self, request) -> dict:
        """Run a google-api request in a thread with retry + backoff.

        Retries on 500/503 (server errors) and 429 (rate-limit).
        Raises immediately on 403 quota errors and 404s.
        """
        last_error: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = await asyncio.to_thread(request.execute)
                return response

            except HttpError as exc:
                status = exc.resp.status
                reason = exc.error_details[0].get("reason", "") if exc.error_details else ""

                # ── Non-retryable errors ─────────────────────
                if status == 403 and reason == "quotaExceeded":
                    logger.error("YouTube API quota exceeded.")
                    raise YouTubeQuotaExceeded(
                        "Daily YouTube API quota has been exceeded.",
                        status_code=403,
                    ) from exc

                if status == 404:
                    raise YouTubeNotFound(
                        f"Resource not found: {exc}",
                        status_code=404,
                    ) from exc

                if status == 403:
                    raise YouTubeAPIError(
                        f"Forbidden: {exc}", status_code=403,
                    ) from exc

                # ── Retryable errors (429, 500, 503) ─────────
                if status in (429, 500, 503):
                    wait = _RETRY_BACKOFF_BASE ** attempt
                    logger.warning(
                        "YouTube API %s (attempt %d/%d) — retrying in %ds",
                        status, attempt, _MAX_RETRIES, wait,
                    )
                    last_error = exc
                    await asyncio.sleep(wait)
                    continue

                # ── Unknown HTTP errors ──────────────────────
                raise YouTubeAPIError(
                    f"YouTube API error: {exc}", status_code=status,
                ) from exc

            except Exception as exc:
                raise YouTubeAPIError(
                    f"Unexpected error calling YouTube API: {exc}"
                ) from exc

        # All retries exhausted
        raise YouTubeAPIError(
            f"YouTube API call failed after {_MAX_RETRIES} retries: {last_error}"
        )

    @staticmethod
    def _safe_int(value) -> int:
        """Convert a value to int, defaulting to 0."""
        try:
            return int(value)
        except (TypeError, ValueError):
            return 0

    # ── public API ───────────────────────────────────────────

    async def fetch_video_metadata(self, video_id: str) -> VideoMetadata:
        """Fetch detailed metadata and statistics for a single video.

        Parameters
        ----------
        video_id : str
            YouTube video ID (e.g. ``"dQw4w9WgXcQ"``).

        Returns
        -------
        VideoMetadata
            Structured metadata including view/like counts.

        Raises
        ------
        YouTubeNotFound
            If the video ID does not exist.
        YouTubeQuotaExceeded
            If the daily API quota is exhausted.
        YouTubeAPIError
            On any other API failure.
        """
        request = self._service.videos().list(
            part="snippet,statistics,contentDetails",
            id=video_id,
        )
        data = await self._execute_with_retry(request)

        items = data.get("items", [])
        if not items:
            raise YouTubeNotFound(
                f"Video '{video_id}' not found.", status_code=404,
            )

        item = items[0]
        snippet = item.get("snippet", {})
        stats = item.get("statistics", {})
        content = item.get("contentDetails", {})
        thumbnails = snippet.get("thumbnails", {})
        thumb_url = (
            thumbnails.get("maxres", {}).get("url")
            or thumbnails.get("high", {}).get("url")
            or thumbnails.get("default", {}).get("url")
        )

        return VideoMetadata(
            video_id=video_id,
            title=snippet.get("title", ""),
            description=snippet.get("description", ""),
            channel_id=snippet.get("channelId", ""),
            channel_title=snippet.get("channelTitle", ""),
            published_at=snippet.get("publishedAt"),
            tags=snippet.get("tags", []),
            category_id=snippet.get("categoryId"),
            duration=content.get("duration"),
            thumbnail_url=thumb_url,
            statistics=VideoStatistics(
                view_count=self._safe_int(stats.get("viewCount")),
                like_count=self._safe_int(stats.get("likeCount")),
                comment_count=self._safe_int(stats.get("commentCount")),
                favorite_count=self._safe_int(stats.get("favoriteCount")),
            ),
            raw=item,
        )

    async def fetch_channel_videos(
        self,
        channel_id: str,
        *,
        max_results: int = 20,
        page_token: str | None = None,
        order: str = "date",
    ) -> ChannelVideosResponse:
        """List recent uploads from a channel.

        Parameters
        ----------
        channel_id : str
            YouTube channel ID (e.g. ``"UC..."``).
        max_results : int
            Number of results per page (1–50, default 20).
        page_token : str | None
            Pagination token from a previous response.
        order : str
            Sort order — ``"date"`` (default), ``"viewCount"``, or ``"relevance"``.

        Returns
        -------
        ChannelVideosResponse
            List of video stubs with a ``next_page_token`` for pagination.
        """
        kwargs: dict = dict(
            part="snippet",
            channelId=channel_id,
            type="video",
            order=order,
            maxResults=min(max_results, 50),
        )
        if page_token:
            kwargs["pageToken"] = page_token
        request = self._service.search().list(**kwargs)
        data = await self._execute_with_retry(request)

        videos: list[ChannelVideoItem] = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            vid = item.get("id", {}).get("videoId", "")
            thumbnails = snippet.get("thumbnails", {})
            thumb_url = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("default", {}).get("url")
            )
            videos.append(ChannelVideoItem(
                video_id=vid,
                title=snippet.get("title", ""),
                description=snippet.get("description", ""),
                published_at=snippet.get("publishedAt"),
                thumbnail_url=thumb_url,
            ))

        page_info = data.get("pageInfo", {})
        return ChannelVideosResponse(
            channel_id=channel_id,
            total_results=self._safe_int(page_info.get("totalResults")),
            next_page_token=data.get("nextPageToken"),
            videos=videos,
        )

    async def fetch_comment_threads(
        self,
        video_id: str,
        *,
        max_results: int = 25,
        page_token: str | None = None,
        order: str = "relevance",
    ) -> CommentThreadsResponse:
        """Fetch top-level comment threads (with replies) for a video.

        Parameters
        ----------
        video_id : str
            YouTube video ID.
        max_results : int
            Results per page (1–100, default 25).
        page_token : str | None
            Pagination token from a previous response.
        order : str
            ``"relevance"`` (default) or ``"time"``.

        Returns
        -------
        CommentThreadsResponse
            Threads with nested replies and a ``next_page_token``.
        """
        kwargs: dict = dict(
            part="snippet,replies",
            videoId=video_id,
            order=order,
            maxResults=min(max_results, 100),
        )
        if page_token:
            kwargs["pageToken"] = page_token
        request = self._service.commentThreads().list(**kwargs)
        data = await self._execute_with_retry(request)

        threads: list[CommentThread] = []
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            top_raw = snippet.get("topLevelComment", {}).get("snippet", {})

            top_comment = CommentItem(
                comment_id=snippet.get("topLevelComment", {}).get("id", ""),
                author_name=top_raw.get("authorDisplayName", ""),
                author_channel_id=(
                    top_raw.get("authorChannelId", {}).get("value")
                ),
                text=top_raw.get("textOriginal", ""),
                like_count=self._safe_int(top_raw.get("likeCount")),
                published_at=top_raw.get("publishedAt"),
                updated_at=top_raw.get("updatedAt"),
            )

            # Parse replies (if present)
            replies: list[CommentItem] = []
            for reply_item in (
                item.get("replies", {}).get("comments", [])
            ):
                r = reply_item.get("snippet", {})
                replies.append(CommentItem(
                    comment_id=reply_item.get("id", ""),
                    author_name=r.get("authorDisplayName", ""),
                    author_channel_id=(
                        r.get("authorChannelId", {}).get("value")
                    ),
                    text=r.get("textOriginal", ""),
                    like_count=self._safe_int(r.get("likeCount")),
                    published_at=r.get("publishedAt"),
                    updated_at=r.get("updatedAt"),
                ))

            threads.append(CommentThread(
                thread_id=item.get("id", ""),
                top_comment=top_comment,
                reply_count=self._safe_int(snippet.get("totalReplyCount")),
                replies=replies,
            ))

        return CommentThreadsResponse(
            video_id=video_id,
            next_page_token=data.get("nextPageToken"),
            threads=threads,
        )
