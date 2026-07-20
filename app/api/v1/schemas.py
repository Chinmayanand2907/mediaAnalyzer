"""
Shared Pydantic response schemas used across all v1 routers.

All schemas are intentionally lean — they carry only the fields a
React dashboard actually needs, stripping internal Mongo/Postgres
internals (ObjectIds, raw blobs, etc.).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Generic envelope ─────────────────────────────────────────────────────────

class TaskEnqueuedResponse(BaseModel):
    """Returned whenever a Celery task is dispatched asynchronously."""
    task_id: str = Field(..., description="Celery task UUID — poll /tasks/{task_id} for status")
    message: str


# ── Sentiment ────────────────────────────────────────────────────────────────

class SentimentDistribution(BaseModel):
    positive: float = Field(..., ge=0, le=1)
    neutral:  float = Field(..., ge=0, le=1)
    negative: float = Field(..., ge=0, le=1)
    dominant_label: str
    total_comments_analysed: int


class CommentSentimentItem(BaseModel):
    comment_id: str
    author: str
    body: str
    published_at: Optional[str]
    sentiment_label: str
    sentiment_score: float
    engine: str


# ── YouTube ──────────────────────────────────────────────────────────────────

class YouTubeChannelMetrics(BaseModel):
    channel_id: str
    display_name: str
    description: Optional[str]
    subscriber_count: Optional[int]
    profile_image_url: Optional[str]
    # Latest snapshot from MongoDB video_payloads
    total_views: Optional[int]
    total_likes: Optional[int]
    total_videos: Optional[int]
    last_ingested_at: Optional[str]


class YouTubeChannelListItem(BaseModel):
    channel_id: str
    display_name: str
    subscriber_count: Optional[int]
    last_ingested_at: Optional[str]


# ── Reddit ───────────────────────────────────────────────────────────────────

class RedditSubredditMetrics(BaseModel):
    subreddit_name: str
    display_name: str
    description: Optional[str]
    member_count: Optional[int]
    last_ingested_at: Optional[str]


class KeywordItem(BaseModel):
    keyword: str
    frequency: int
    avg_score: Optional[float] = None   # upvote/engagement score


class RedditSubredditListItem(BaseModel):
    subreddit_name: str
    display_name: str
    member_count: Optional[int]
    last_ingested_at: Optional[str]


# ── Cross-platform ───────────────────────────────────────────────────────────

class SharedVideoItem(BaseModel):
    youtube_video_id: str
    youtube_url: str
    reddit_post_ids: List[str]
    reddit_subreddits: List[str]
    total_reddit_shares: int
    youtube_views: Optional[int]
    youtube_likes: Optional[int]
    reddit_total_upvotes: Optional[int]
    reddit_total_comments: Optional[int]


class PlatformEngagementComparison(BaseModel):
    """Side-by-side engagement normalised to a 0–100 scale."""
    platform: str
    raw_engagement: Dict[str, Any]
    normalised_score: float = Field(..., ge=0, le=100, description="Normalised 0–100 engagement index")


class CrossPlatformCorrelationResponse(BaseModel):
    shared_videos: List[SharedVideoItem]
    platform_comparison: List[PlatformEngagementComparison]
    correlation_summary: Dict[str, Any]
