"""
Cross-Platform Router  —  /api/v1/cross-platform
===================================================

The core analytical endpoint that bridges YouTube and Reddit data.

Endpoints
---------
GET /shared-videos
    Scans Reddit comment bodies for YouTube video URLs (youtu.be / youtube.com),
    then looks up the corresponding YouTube metadata from MongoDB.
    Returns a list of videos that were shared across Reddit, enriched with
    engagement numbers from both platforms.

GET /engagement-comparison
    Computes a normalised engagement index for each tracked account on both
    platforms and returns a side-by-side comparison suitable for bar/radar charts.

GET /correlation-summary
    Returns both of the above merged into a single payload for dashboard
    initial load (reduces round-trips).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    CrossPlatformCorrelationResponse,
    PlatformEngagementComparison,
    SharedVideoItem,
)
from app.db.mongodb import get_comments_collection, get_video_payloads_collection
from app.db.postgres import Platform, PlatformAccount, get_db_session

router = APIRouter(prefix="/cross-platform", tags=["Cross-Platform"])

# ── YouTube URL regex — matches both youtu.be and youtube.com/watch?v= ────────
_YT_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:youtu\.be/|youtube\.com/watch\?v=)"
    r"([A-Za-z0-9_\-]{11})"
)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _normalise_engagement(raw: Dict[str, Any], platform: str) -> float:
    """
    Produce a 0–100 engagement index from raw platform metrics.

    Formula is intentionally simple and transparent so the dashboard can
    explain it:
        YouTube : log_scale(views) * (likes_ratio * 50 + comment_ratio * 50)
        Reddit  : log_scale(upvotes) * (comment_ratio * 100)

    Returns a value in [0, 100].
    """
    import math

    if platform == "youtube":
        views    = max(1, int(raw.get("views",    0)))
        likes    = max(0, int(raw.get("likes",    0)))
        comments = max(0, int(raw.get("comments", 0)))
        like_ratio    = min(likes    / views, 1.0)
        comment_ratio = min(comments / views, 1.0)
        log_views = math.log10(views)           # ~3 for 1K views, ~6 for 1M
        score = (log_views / 7) * (like_ratio * 50 + comment_ratio * 50)

    elif platform == "reddit":
        upvotes  = max(1, int(raw.get("upvotes",  raw.get("members", 0))))
        comments = max(0, int(raw.get("comments", 0)))
        total    = max(1, upvotes + comments)
        comment_ratio = min(comments / total, 1.0)
        log_ups = math.log10(upvotes)
        score = (log_ups / 6) * (comment_ratio * 100)

    else:
        score = 0.0

    return round(min(max(score, 0.0), 100.0), 2)


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get(
    "/shared-videos",
    response_model=List[SharedVideoItem],
    summary="YouTube videos found shared inside Reddit threads",
)
async def get_shared_videos(
    subreddit_name: str = Query(
        ...,
        description="The subreddit to scan for YouTube links (e.g. 'learnprogramming')",
    ),
    limit: int = Query(
        default=500,
        ge=50,
        le=2000,
        description="Number of Reddit comments to scan",
    ),
) -> List[SharedVideoItem]:
    """
    Scans up to *limit* Reddit comments in *subreddit_name* for YouTube video
    URLs.  For each unique video ID found, looks up its stored metrics in
    MongoDB.

    This powers the "Videos shared on Reddit" cross-platform widget.
    """
    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    # 1. Fetch Reddit comment bodies for the target subreddit
    cursor = (
        comments_coll
        .find(
            {"platform": "reddit", "parent_id": subreddit_name},
            {"_id": 0, "platform_id": 1, "body": 1},
        )
        .sort("ingested_at", -1)
        .limit(limit)
    )
    reddit_docs = await cursor.to_list(length=limit)

    if not reddit_docs:
        return []

    # 2. Extract all YouTube video IDs and track which Reddit posts contain them
    video_to_posts: Dict[str, List[str]] = {}
    for doc in reddit_docs:
        body = doc.get("body", "")
        matches = _YT_URL_RE.findall(body)
        for vid_id in set(matches):
            video_to_posts.setdefault(vid_id, [])
            post_id = doc.get("platform_id", "")
            if post_id and post_id not in video_to_posts[vid_id]:
                video_to_posts[vid_id].append(post_id)

    if not video_to_posts:
        return []

    # 3. Fetch YouTube payload snapshots from MongoDB for matched video IDs
    yt_cursor = payloads_coll.find(
        {"platform": "youtube", "platform_id": {"$in": list(video_to_posts.keys())}},
        {"_id": 0, "platform_id": 1, "stats": 1},
    )
    yt_docs = await yt_cursor.to_list(length=len(video_to_posts))
    yt_stats: Dict[str, Dict] = {d["platform_id"]: d.get("stats", {}) for d in yt_docs}

    # 4. Fetch Reddit post-level upvote/comment totals for the discovered posts
    all_post_ids = [pid for pids in video_to_posts.values() for pid in pids]
    reddit_post_cursor = payloads_coll.find(
        {"platform": "reddit", "platform_id": {"$in": all_post_ids}},
        {"_id": 0, "platform_id": 1, "stats": 1},
    )
    reddit_post_docs = await reddit_post_cursor.to_list(length=len(all_post_ids))
    reddit_post_stats: Dict[str, Dict] = {
        d["platform_id"]: d.get("stats", {}) for d in reddit_post_docs
    }

    # 5. Build response
    shared: List[SharedVideoItem] = []
    for vid_id, post_ids in video_to_posts.items():
        yt = yt_stats.get(vid_id, {})
        reddit_upvotes  = sum(reddit_post_stats.get(pid, {}).get("upvotes",  0) for pid in post_ids)
        reddit_comments = sum(reddit_post_stats.get(pid, {}).get("comments", 0) for pid in post_ids)

        shared.append(
            SharedVideoItem(
                youtube_video_id=vid_id,
                youtube_url=f"https://www.youtube.com/watch?v={vid_id}",
                reddit_post_ids=post_ids,
                reddit_subreddits=[subreddit_name],
                total_reddit_shares=len(post_ids),
                youtube_views=yt.get("views"),
                youtube_likes=yt.get("likes"),
                reddit_total_upvotes=reddit_upvotes or None,
                reddit_total_comments=reddit_comments or None,
            )
        )

    # Sort by number of Reddit shares descending
    shared.sort(key=lambda x: x.total_reddit_shares, reverse=True)
    return shared


@router.get(
    "/engagement-comparison",
    response_model=List[PlatformEngagementComparison],
    summary="Comparative normalised engagement index across both platforms",
)
async def get_engagement_comparison(
    session: AsyncSession = Depends(get_db_session),
) -> List[PlatformEngagementComparison]:
    """
    For every tracked account (YouTube channels + Reddit subreddits), compute
    a normalised engagement index (0–100) and return a list suitable for a
    side-by-side bar chart or radar chart in the React dashboard.
    """
    payloads_coll = get_video_payloads_collection()

    # Fetch all tracked accounts from Postgres
    stmt = select(PlatformAccount).order_by(
        PlatformAccount.platform, PlatformAccount.display_name
    )
    result = await session.execute(stmt)
    accounts = result.scalars().all()

    if not accounts:
        return []

    comparisons: List[PlatformEngagementComparison] = []

    for acc in accounts:
        platform_str = acc.platform.value  # "youtube" | "reddit"
        payload_doc = await payloads_coll.find_one(
            {"platform": platform_str, "platform_id": acc.platform_id},
            {"_id": 0, "stats": 1},
        )
        stats = (payload_doc or {}).get("stats", {})

        norm_score = _normalise_engagement(stats, platform_str)

        comparisons.append(
            PlatformEngagementComparison(
                platform=platform_str,
                raw_engagement={
                    "account_id":    acc.platform_id,
                    "display_name":  acc.display_name,
                    **{k: v for k, v in stats.items() if isinstance(v, (int, float))},
                },
                normalised_score=norm_score,
            )
        )

    return comparisons


@router.get(
    "/correlation-summary",
    response_model=CrossPlatformCorrelationResponse,
    summary="Full cross-platform correlation in a single payload",
)
async def get_correlation_summary(
    subreddit_name: str = Query(
        ...,
        description="Subreddit to scan for YouTube links",
    ),
    comment_scan_limit: int = Query(
        default=300,
        ge=50,
        le=2000,
        description="Reddit comments to scan for YouTube URLs",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> CrossPlatformCorrelationResponse:
    """
    Combines `shared-videos` and `engagement-comparison` into a single
    response.  Call this on dashboard initial load to minimise HTTP round-trips.

    Also computes a lightweight `correlation_summary` dict with aggregate
    stats useful for the insight cards at the top of the dashboard.
    """
    # Run both sub-queries
    shared = await get_shared_videos(
        subreddit_name=subreddit_name,
        limit=comment_scan_limit,
    )
    comparison = await get_engagement_comparison(session=session)

    # Aggregate summary stats
    yt_scores = [c.normalised_score for c in comparison if c.platform == "youtube"]
    rd_scores = [c.normalised_score for c in comparison if c.platform == "reddit"]

    import statistics as _stats

    def _safe_mean(lst: List[float]) -> float:
        return round(_stats.mean(lst), 2) if lst else 0.0

    correlation_summary: Dict[str, Any] = {
        "total_tracked_youtube_channels": len(yt_scores),
        "total_tracked_subreddits":       len(rd_scores),
        "avg_youtube_engagement_score":   _safe_mean(yt_scores),
        "avg_reddit_engagement_score":    _safe_mean(rd_scores),
        "total_cross_platform_videos":    len(shared),
        "top_shared_video_id":            shared[0].youtube_video_id if shared else None,
        "top_shared_video_reddit_shares": shared[0].total_reddit_shares if shared else 0,
        "note": (
            "Engagement scores are normalised to 0–100. "
            "Cross-platform videos were discovered by scanning Reddit comment bodies "
            f"of r/{subreddit_name} for YouTube URLs."
        ),
    }

    return CrossPlatformCorrelationResponse(
        shared_videos=shared,
        platform_comparison=comparison,
        correlation_summary=correlation_summary,
    )
