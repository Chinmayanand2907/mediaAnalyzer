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

class RedditDiscussionItem(BaseModel):
    """Detailed Reddit comment or post referencing a YouTube video."""
    discussion_id: str
    post_id: Optional[str] = None
    subreddit: str = ""
    author: str = "[deleted]"
    body: str = ""
    score: int = 0
    published_at: Optional[str] = None
    permalink: Optional[str] = None
    sentiment_label: Optional[str] = "neutral"
    sentiment_score: Optional[float] = None


class PlatformSentimentBreakdown(BaseModel):
    """Normalized sentiment distribution for a platform's audience."""
    positive: float = Field(0.0, ge=0, le=1)
    neutral:  float = Field(0.0, ge=0, le=1)
    negative: float = Field(0.0, ge=0, le=1)
    dominant_label: str = "neutral"
    sample_size: int = 0


class SharedVideoItem(BaseModel):
    youtube_video_id: str
    youtube_url: str
    reddit_post_ids: List[str] = Field(default_factory=list)
    reddit_subreddits: List[str] = Field(default_factory=list)
    total_reddit_shares: int = 0
    youtube_views: Optional[int] = None
    youtube_likes: Optional[int] = None
    youtube_comment_count: Optional[int] = None
    youtube_title: Optional[str] = None
    youtube_thumbnail_url: Optional[str] = None
    youtube_channel_title: Optional[str] = None
    youtube_published_at: Optional[str] = None
    youtube_tags: List[str] = Field(default_factory=list)
    youtube_sentiment: Optional[PlatformSentimentBreakdown] = None
    reddit_total_upvotes: Optional[int] = None
    reddit_total_comments: Optional[int] = None
    reddit_first_shared_at: Optional[str] = None
    reddit_latest_shared_at: Optional[str] = None
    propagation_delay_hours: Optional[float] = None
    propagation_speed: Optional[str] = None  # Rapid (<6h), Moderate (6-24h), Delayed (>24h), Same-Day
    reddit_sentiment: Optional[PlatformSentimentBreakdown] = None
    sentiment_disparity_note: Optional[str] = None
    reddit_discussions: List[RedditDiscussionItem] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)


class PlatformEngagementComparison(BaseModel):
    """Side-by-side engagement normalised to a 0–100 scale."""
    platform: str
    raw_engagement: Dict[str, Any]
    normalised_score: float = Field(..., ge=0, le=100, description="Normalised 0–100 engagement index")


class CrossPlatformTopicCorrelation(BaseModel):
    """Correlated topics and themes across YouTube and Reddit."""
    shared_topics: List[str] = Field(default_factory=list)
    youtube_topics: List[str] = Field(default_factory=list)
    reddit_topics: List[str] = Field(default_factory=list)
    top_correlations: List[Dict[str, Any]] = Field(default_factory=list)


class CrossPlatformSentimentComparison(BaseModel):
    """Audience response sentiment comparison between YouTube and Reddit."""
    youtube_sentiment: PlatformSentimentBreakdown
    reddit_sentiment: PlatformSentimentBreakdown
    sentiment_gap: float = Field(..., description="Positive sentiment disparity (YT positive - Reddit positive)")
    audience_response_summary: str


class CrossPlatformCorrelationResponse(BaseModel):
    shared_videos: List[SharedVideoItem]
    platform_comparison: List[PlatformEngagementComparison]
    sentiment_comparison: Optional[CrossPlatformSentimentComparison] = None
    topic_correlation: Optional[CrossPlatformTopicCorrelation] = None
    correlation_summary: Dict[str, Any]


class VideoCrossPlatformEngagementResponse(BaseModel):
    """Cross-platform engagement metrics for a specific YouTube video across Reddit."""
    youtube_video_id: str
    youtube_url: str
    youtube_title: Optional[str] = None
    youtube_channel_title: Optional[str] = None
    youtube_thumbnail_url: Optional[str] = None
    youtube_views: Optional[int] = None
    youtube_likes: Optional[int] = None
    youtube_comment_count: Optional[int] = None
    youtube_published_at: Optional[str] = None
    youtube_tags: List[str] = Field(default_factory=list)
    subreddits_count: int = Field(0, description="Count of distinct subreddits discussing this video")
    subreddits_list: List[str] = Field(default_factory=list, description="List of distinct subreddits where video was shared")
    total_reddit_discussions: int = Field(0, description="Total Reddit comments/posts citing this video")
    reddit_total_upvotes: int = Field(0, description="Total upvotes across Reddit discussions")
    reddit_total_comments: int = Field(0, description="Estimated total comments in threads")
    reddit_first_shared_at: Optional[str] = None
    reddit_latest_shared_at: Optional[str] = None
    propagation_delay_hours: Optional[float] = None
    propagation_speed: Optional[str] = None
    youtube_sentiment: Optional[PlatformSentimentBreakdown] = None
    reddit_sentiment: Optional[PlatformSentimentBreakdown] = None
    sentiment_disparity_note: Optional[str] = None
    discussions: List[RedditDiscussionItem] = Field(default_factory=list)
    topics: List[str] = Field(default_factory=list)

