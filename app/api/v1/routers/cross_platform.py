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
from typing import Any, Dict, List, Optional

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
    subreddit_name: Optional[str] = Query(
        default=None,
        description="The subreddit to scan for YouTube links (or leave blank to scan all subreddits)",
    ),
    limit: int = Query(
        default=500,
        ge=50,
        le=2000,
        description="Number of Reddit comments to scan",
    ),
) -> List[SharedVideoItem]:
    """
    Scans up to *limit* Reddit comments for YouTube video URLs.
    For each unique video ID found, looks up its stored metrics in MongoDB
    and falls back to live YouTube Data API for any videos not yet cached.
    """
    from app.services.external.youtube_client import YouTubeClient, YouTubeAPIError

    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    # 1. Fetch Reddit comment bodies
    query_filter: Dict[str, Any] = {"platform": "reddit"}
    if subreddit_name:
        query_filter["parent_id"] = subreddit_name

    cursor = (
        comments_coll
        .find(
            query_filter,
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

    all_video_ids = list(video_to_posts.keys())

    # 3. Fetch YouTube payload snapshots from MongoDB for matched video IDs
    yt_cursor = payloads_coll.find(
        {"platform": "youtube", "platform_id": {"$in": all_video_ids}},
        {"_id": 0, "platform_id": 1, "stats": 1},
    )
    yt_docs = await yt_cursor.to_list(length=len(video_to_posts))
    yt_stats: Dict[str, Dict] = {d["platform_id"]: d.get("stats", {}) for d in yt_docs}

    # 4. For video IDs missing from MongoDB, batch-fetch from the YouTube API
    missing_ids = [vid for vid in all_video_ids if vid not in yt_stats]
    yt_live_meta: Dict[str, Any] = {}  # vid_id -> full metadata dict

    if missing_ids:
        try:
            yt_client = YouTubeClient()
            # YouTube API supports up to 50 IDs per request — batch in chunks
            chunk_size = 50
            import asyncio as _asyncio
            from googleapiclient.discovery import build as _build

            async def _fetch_batch(ids: List[str]) -> dict:
                """Fetch snippet+statistics for up to 50 video IDs in one call."""
                request = yt_client._service.videos().list(
                    part="snippet,statistics",
                    id=",".join(ids),
                )
                data = await _asyncio.to_thread(request.execute)
                result = {}
                for item in data.get("items", []):
                    vid = item.get("id", "")
                    snippet = item.get("snippet", {})
                    stats = item.get("statistics", {})
                    thumbnails = snippet.get("thumbnails", {})
                    thumb = (
                        thumbnails.get("high", {}).get("url")
                        or thumbnails.get("medium", {}).get("url")
                        or thumbnails.get("default", {}).get("url")
                    )
                    result[vid] = {
                        "title":          snippet.get("title", ""),
                        "channel_title":  snippet.get("channelTitle", ""),
                        "thumbnail_url":  thumb,
                        "views":          int(stats.get("viewCount", 0) or 0),
                        "likes":          int(stats.get("likeCount", 0) or 0),
                        "comment_count":  int(stats.get("commentCount", 0) or 0),
                    }
                return result

            # Gather all chunks concurrently
            chunks = [missing_ids[i:i + chunk_size] for i in range(0, len(missing_ids), chunk_size)]
            chunk_results = await _asyncio.gather(*[_fetch_batch(chunk) for chunk in chunks], return_exceptions=True)
            for res in chunk_results:
                if isinstance(res, dict):
                    yt_live_meta.update(res)

        except YouTubeAPIError as exc:
            logger.warning("YouTube API unavailable for live metadata fetch: %s", exc)
        except Exception as exc:
            logger.warning("Unexpected error fetching live YouTube metadata: %s", exc)

    # 5. Fetch Reddit post-level upvote/comment totals for the discovered posts
    all_post_ids = [pid for pids in video_to_posts.values() for pid in pids]
    reddit_post_cursor = payloads_coll.find(
        {"platform": "reddit", "platform_id": {"$in": all_post_ids}},
        {"_id": 0, "platform_id": 1, "stats": 1},
    )
    reddit_post_docs = await reddit_post_cursor.to_list(length=len(all_post_ids))
    reddit_post_stats: Dict[str, Dict] = {
        d["platform_id"]: d.get("stats", {}) for d in reddit_post_docs
    }

    # 6. Build response — prefer MongoDB cache, fall back to live API data
    shared: List[SharedVideoItem] = []
    for vid_id, post_ids in video_to_posts.items():
        mongo_yt = yt_stats.get(vid_id, {})
        live_yt  = yt_live_meta.get(vid_id, {})

        # Prefer cached MongoDB data, fall back to live API
        views          = mongo_yt.get("views")  or (live_yt.get("views") if live_yt else None)
        likes          = mongo_yt.get("likes")  or (live_yt.get("likes") if live_yt else None)
        comment_count  = live_yt.get("comment_count") if live_yt else None
        title          = live_yt.get("title") if live_yt else None
        thumbnail_url  = live_yt.get("thumbnail_url") if live_yt else None
        channel_title  = live_yt.get("channel_title") if live_yt else None

        reddit_upvotes  = sum(reddit_post_stats.get(pid, {}).get("upvotes",  0) for pid in post_ids)
        reddit_comments = sum(reddit_post_stats.get(pid, {}).get("comments", 0) for pid in post_ids)

        shared.append(
            SharedVideoItem(
                youtube_video_id=vid_id,
                youtube_url=f"https://www.youtube.com/watch?v={vid_id}",
                reddit_post_ids=post_ids,
                reddit_subreddits=[subreddit_name] if subreddit_name else [],
                total_reddit_shares=len(post_ids),
                youtube_views=views,
                youtube_likes=likes,
                youtube_comment_count=comment_count,
                youtube_title=title,
                youtube_thumbnail_url=thumbnail_url,
                youtube_channel_title=channel_title,
                reddit_total_upvotes=reddit_upvotes or None,
                reddit_total_comments=reddit_comments or None,
            )
        )

    # Sort by Reddit shares descending, then by YouTube views descending
    shared.sort(key=lambda x: (x.total_reddit_shares, x.youtube_views or 0), reverse=True)
    return shared


@router.get(
    "/top-videos",
    response_model=List[SharedVideoItem],
    summary="Top YouTube videos for a given topic keyword",
)
async def get_top_videos_for_topic(
    topic: str = Query(
        ...,
        description="Topic / keyword to search for (e.g. 'gaming', 'python tutorial')",
    ),
    max_results: int = Query(
        default=10,
        ge=1,
        le=25,
        description="Number of top videos to return",
    ),
) -> List[SharedVideoItem]:
    """
    Uses the YouTube Data API to search for the most viewed/relevant videos
    for a given topic.  Returns them in SharedVideoItem format so the
    Cross-Platform table can display them alongside Reddit-discovered links.
    """
    from app.services.external.youtube_client import YouTubeClient, YouTubeAPIError
    import asyncio as _asyncio

    try:
        yt_client = YouTubeClient()

        # Step 1 — search for top videos by topic, ordered by view count
        search_request = yt_client._service.search().list(
            part="snippet",
            q=topic,
            type="video",
            order="viewCount",
            maxResults=max_results,
            relevanceLanguage="en",
        )
        search_data = await _asyncio.to_thread(search_request.execute)
        video_ids = [
            item["id"]["videoId"]
            for item in search_data.get("items", [])
            if item.get("id", {}).get("videoId")
        ]

        if not video_ids:
            return []

        # Step 2 — batch-fetch statistics for those video IDs
        stats_request = yt_client._service.videos().list(
            part="snippet,statistics",
            id=",".join(video_ids),
        )
        stats_data = await _asyncio.to_thread(stats_request.execute)

        results: List[SharedVideoItem] = []
        for item in stats_data.get("items", []):
            vid_id  = item.get("id", "")
            snippet = item.get("snippet", {})
            stats   = item.get("statistics", {})
            thumbnails = snippet.get("thumbnails", {})
            thumb = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
            )
            results.append(SharedVideoItem(
                youtube_video_id=vid_id,
                youtube_url=f"https://www.youtube.com/watch?v={vid_id}",
                reddit_post_ids=[],
                reddit_subreddits=[],
                total_reddit_shares=0,
                youtube_views=int(stats.get("viewCount", 0) or 0),
                youtube_likes=int(stats.get("likeCount", 0) or 0),
                youtube_comment_count=int(stats.get("commentCount", 0) or 0),
                youtube_title=snippet.get("title", ""),
                youtube_thumbnail_url=thumb,
                youtube_channel_title=snippet.get("channelTitle", ""),
                reddit_total_upvotes=None,
                reddit_total_comments=None,
            ))

        # Sort by views descending
        results.sort(key=lambda x: x.youtube_views or 0, reverse=True)
        return results

    except YouTubeAPIError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"YouTube API error: {exc}",
        )



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
    subreddit_name: Optional[str] = Query(
        default=None,
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
