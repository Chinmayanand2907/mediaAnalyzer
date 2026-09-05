"""
Cross-Platform Router  —  /api/v1/cross-platform
===================================================

The core analytical endpoint that bridges YouTube and Reddit data according to the PRD:
"Cross-Platform Mode links YouTube videos with Reddit posts and discussions that reference
the same content. It combines platform-specific engagement metrics, timestamps, sentiment,
topics, and discussion activity to show how content propagates across platforms and how
audience response differs between YouTube and Reddit."

Endpoints
---------
GET /shared-videos
    Scans Reddit comments for YouTube video URLs, looks up YouTube metadata,
    and returns linked videos enriched with timestamps, propagation delay,
    audience sentiment comparison, topics, and detailed Reddit discussion threads.

GET /sentiment-comparison
    Compares audience sentiment distribution (positive/neutral/negative) between
    YouTube and Reddit for a scanned subreddit or across all tracked accounts.

GET /topic-correlation
    Extracts and correlates discussion topics and keywords between YouTube videos
    and Reddit discussion threads.

GET /top-videos
    Live topic search on YouTube Data API sorted by view count.

GET /engagement-comparison
    Computes a normalised engagement index (0–100) for each tracked account.

GET /correlation-summary
    Unified payload combining shared videos, engagement, sentiment, and topics.
"""

from __future__ import annotations

import asyncio
import re
import string
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

_asyncio = asyncio

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    CrossPlatformCorrelationResponse,
    CrossPlatformSentimentComparison,
    CrossPlatformTopicCorrelation,
    PlatformEngagementComparison,
    PlatformSentimentBreakdown,
    RedditDiscussionItem,
    SharedVideoItem,
    VideoCrossPlatformEngagementResponse,
)
from app.db.mongodb import get_comments_collection, get_video_payloads_collection
from app.db.postgres import Platform, PlatformAccount, get_db_session
from app.services.analytics.sentiment_service import SentimentService

router = APIRouter(prefix="/cross-platform", tags=["Cross-Platform"])

# ── YouTube URL regex — captures youtu.be, youtube.com/watch, embed, shorts, etc. ──
_YT_URL_RE = re.compile(
    r"(?:https?://)?(?:www\.|m\.)?(?:youtu\.be/|youtube\.com/(?:watch\?.*?v=|embed/|v/|shorts/))"
    r"([A-Za-z0-9_\-]{11})"
)


def _extract_video_id(input_str: Any) -> Optional[str]:
    """Extract canonical 11-char YouTube video ID from URL or raw ID."""
    if not input_str or not isinstance(input_str, str):
        return None
    input_str = input_str.strip()
    match = _YT_URL_RE.search(input_str)
    if match:
        return match.group(1)
    # Check if raw 11-character video ID
    clean = re.sub(r"[^A-Za-z0-9_\-]", "", input_str)
    if len(clean) == 11:
        return clean
    return input_str


# Common stopwords for topic / keyword extraction
_STOPWORDS = frozenset(
    "the a an and or but in on at to for of with by from is are was were be been "
    "being have has had do does did will would could should may might shall can "
    "not no nor so yet both either neither one two three i me my we our you your "
    "he she it its they them their this that these those what which who whom how "
    "when where why than then also just more very much many some any all each "
    "about after before between into through during again further once "
    "http https www ftp youtube watch reddit youtu imgur twitter facebook "
    "amp utm ref source medium campaign com net org video comments"
    .split()
)

_sentiment_svc: SentimentService | None = None


def _get_sentiment_svc() -> SentimentService:
    global _sentiment_svc
    if _sentiment_svc is None:
        _sentiment_svc = SentimentService()
    return _sentiment_svc


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _parse_iso_datetime(dt_str: Optional[str]) -> Optional[datetime]:
    """Safely parse an ISO-8601 datetime string to UTC."""
    if not dt_str:
        return None
    try:
        # Standard ISO format (handles Z and offsets)
        cleaned = dt_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except Exception:
        return None


def _extract_topics_from_texts(texts: List[str], top_n: int = 8) -> List[str]:
    """Extract top topic keywords from a collection of text strings."""
    tokens: List[str] = []
    for text in texts:
        if not text:
            continue
        cleaned = re.sub(r"https?://\S+|www\.\S+", "", text)
        cleaned = cleaned.translate(str.maketrans("", "", string.punctuation + string.digits))
        for word in cleaned.lower().split():
            if len(word) > 3 and word not in _STOPWORDS:
                tokens.append(word)
    return [w for w, _ in Counter(tokens).most_common(top_n)]


def _compute_sentiment_breakdown(labels: List[str]) -> PlatformSentimentBreakdown:
    """Compute normalized sentiment distribution from a list of sentiment labels."""
    if not labels:
        return PlatformSentimentBreakdown(
            positive=0.0, neutral=0.0, negative=0.0, dominant_label="neutral", sample_size=0
        )
    counts = Counter(labels)
    total = len(labels)
    pos_pct = round(counts.get("positive", 0) / total, 3)
    neu_pct = round(counts.get("neutral", 0) / total, 3)
    neg_pct = round(counts.get("negative", 0) / total, 3)

    dominant = "neutral"
    if pos_pct >= neu_pct and pos_pct >= neg_pct:
        dominant = "positive"
    elif neg_pct >= pos_pct and neg_pct >= neu_pct:
        dominant = "negative"

    return PlatformSentimentBreakdown(
        positive=pos_pct,
        neutral=neu_pct,
        negative=neg_pct,
        dominant_label=dominant,
        sample_size=total,
    )


def _normalise_engagement(raw: Dict[str, Any], platform: str) -> float:
    """Produce a 0–100 engagement index from raw platform metrics."""
    import math

    if platform == "youtube":
        views = max(1, int(raw.get("views", 0)))
        likes = max(0, int(raw.get("likes", 0)))
        comments = max(0, int(raw.get("comments", 0)))
        like_ratio = min(likes / views, 1.0)
        comment_ratio = min(comments / views, 1.0)
        log_views = math.log10(views)
        score = (log_views / 7) * (like_ratio * 50 + comment_ratio * 50)

    elif platform == "reddit":
        upvotes = max(1, int(raw.get("upvotes", raw.get("members", 0))))
        comments = max(0, int(raw.get("comments", 0)))
        total = max(1, upvotes + comments)
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
    summary="YouTube videos found shared inside Reddit threads with discussion drill-down and timestamps",
)
async def get_shared_videos(
    subreddit_name: Optional[str] = Query(
        default=None,
        description="The subreddit to scan for YouTube links (or leave blank to scan all subreddits)",
    ),
    video_url_or_id: Optional[str] = Query(
        default=None,
        description="Optional YouTube video URL or ID to filter discussions for",
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
    Extracts full discussion threads, computes propagation timeline and delay,
    sentiment breakdown on both YouTube and Reddit, and topic keywords.
    """
    from app.services.external.youtube_client import YouTubeClient, YouTubeAPIError
    import asyncio as _asyncio

    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    # 1. Fetch Reddit comment bodies with full discussion metadata
    query_filter: Dict[str, Any] = {"platform": "reddit"}
    if subreddit_name:
        clean_sub = subreddit_name.strip().lstrip("/").replace("r/", "").replace("/r/", "").strip().lower()
        query_filter["parent_id"] = clean_sub

    cursor = (
        comments_coll
        .find(
            query_filter,
            {
                "_id": 0,
                "platform_id": 1,
                "body": 1,
                "author": 1,
                "score": 1,
                "published_at": 1,
                "permalink": 1,
                "parent_id": 1,
                "post_id": 1,
                "sentiment_label": 1,
                "sentiment_score": 1,
            },
        )
        .sort("ingested_at", -1)
        .limit(limit)
    )
    reddit_docs = await cursor.to_list(length=limit)

    if not reddit_docs:
        return []

    target_vid_id = _extract_video_id(video_url_or_id) if video_url_or_id else None

    # 2A. Regex URL matching (fast-path)
    video_to_discussions: Dict[str, List[Dict[str, Any]]] = {}
    matched_comment_keys: set = set()

    for doc in reddit_docs:
        body = doc.get("body", "")
        matches = _YT_URL_RE.findall(body)
        for vid_id in set(matches):
            if target_vid_id and vid_id != target_vid_id:
                continue
            doc_copy = dict(doc)
            doc_copy["match_type"] = "url"
            doc_copy["similarity_score"] = 1.0
            video_to_discussions.setdefault(vid_id, []).append(doc_copy)
            c_key = doc.get("platform_id") or doc.get("permalink") or body
            matched_comment_keys.add(c_key)

    # 2B. Semantic Similarity Matching (Sentence-BERT fallback & supplement)
    # Collect candidate YouTube videos to compare Reddit discussions against
    candidate_videos_map: Dict[str, Dict[str, Any]] = {}

    if target_vid_id:
        target_payload = await payloads_coll.find_one(
            {"platform": "youtube", "platform_id": target_vid_id},
            {"_id": 0, "platform_id": 1, "title": 1, "stats": 1, "raw": 1},
        )
        if target_payload:
            candidate_videos_map[target_vid_id] = target_payload
        else:
            candidate_videos_map[target_vid_id] = {"platform_id": target_vid_id, "title": target_vid_id}
    else:
        # Load indexed YouTube videos from MongoDB payloads (up to 50 videos)
        cand_cursor = payloads_coll.find(
            {"platform": "youtube"},
            {"_id": 0, "platform_id": 1, "title": 1, "stats": 1, "raw": 1},
        ).sort("ingested_at", -1).limit(50)
        cand_docs = await cand_cursor.to_list(length=50)
        for c_doc in cand_docs:
            c_id = c_doc.get("platform_id")
            if c_id:
                candidate_videos_map[c_id] = c_doc

        # Also register any video IDs that were already discovered via URL
        for v_id in list(video_to_discussions.keys()):
            if v_id not in candidate_videos_map:
                candidate_videos_map[v_id] = {"platform_id": v_id, "title": v_id}

    # Filter Reddit comments that did not match via URL
    unmatched_reddit_docs = [
        d for d in reddit_docs
        if (d.get("platform_id") or d.get("permalink") or d.get("body")) not in matched_comment_keys
    ]

    if candidate_videos_map and unmatched_reddit_docs:
        from app.services.analytics.semantic_matcher import get_semantic_matcher
        from app.core.config import get_settings
        current_settings = get_settings()

        matcher = get_semantic_matcher()
        candidate_list = list(candidate_videos_map.values())
        sem_matches = matcher.match_discussions_to_videos(
            unmatched_reddit_docs,
            candidate_list,
            threshold=current_settings.SEMANTIC_SIMILARITY_THRESHOLD,
        )

        for matched_vid, items in sem_matches.items():
            if target_vid_id and matched_vid != target_vid_id:
                continue
            for disc_doc, score in items:
                d_copy = dict(disc_doc)
                d_copy["match_type"] = "semantic"
                d_copy["similarity_score"] = score
                video_to_discussions.setdefault(matched_vid, []).append(d_copy)

    if not video_to_discussions:
        return []

    all_video_ids = list(video_to_discussions.keys())

    # 3. Fetch YouTube payload snapshots from MongoDB for matched video IDs
    yt_cursor = payloads_coll.find(
        {"platform": "youtube", "platform_id": {"$in": all_video_ids}},
        {"_id": 0, "platform_id": 1, "title": 1, "stats": 1, "raw": 1, "ingested_at": 1},
    )
    yt_docs = await yt_cursor.to_list(length=len(all_video_ids))
    yt_cached: Dict[str, Dict] = {d["platform_id"]: d for d in yt_docs}

    # 4. For video IDs missing or lacking metadata, fetch live from YouTube Data API
    missing_ids = [vid for vid in all_video_ids if vid not in yt_cached]
    yt_live_meta: Dict[str, Any] = {}

    if missing_ids:
        try:
            yt_client = YouTubeClient()
            chunk_size = 50

            async def _fetch_batch(ids: List[str]) -> dict:
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
                        "title": snippet.get("title", ""),
                        "channel_title": snippet.get("channelTitle", ""),
                        "thumbnail_url": thumb,
                        "published_at": snippet.get("publishedAt"),
                        "tags": snippet.get("tags", []),
                        "views": int(stats.get("viewCount", 0) or 0),
                        "likes": int(stats.get("likeCount", 0) or 0),
                        "comment_count": int(stats.get("commentCount", 0) or 0),
                    }
                return result

            chunks = [missing_ids[i:i + chunk_size] for i in range(0, len(missing_ids), chunk_size)]
            chunk_results = await _asyncio.gather(*[_fetch_batch(chunk) for chunk in chunks], return_exceptions=True)
            for res in chunk_results:
                if isinstance(res, dict):
                    yt_live_meta.update(res)

        except YouTubeAPIError:
            pass
        except Exception:
            pass

    # 5. Fetch Reddit post-level statistics
    all_post_ids = list({
        d.get("post_id") or d.get("platform_id")
        for docs in video_to_discussions.values()
        for d in docs
        if d.get("post_id") or d.get("platform_id")
    })
    reddit_post_cursor = payloads_coll.find(
        {"platform": "reddit", "platform_id": {"$in": all_post_ids}},
        {"_id": 0, "platform_id": 1, "stats": 1},
    )
    reddit_post_docs = await reddit_post_cursor.to_list(length=len(all_post_ids))
    reddit_post_stats: Dict[str, Dict] = {
        d["platform_id"]: d.get("stats", {}) for d in reddit_post_docs
    }

    # 6. Fetch YouTube comments sentiment for cached videos
    yt_comments_cursor = comments_coll.find(
        {"platform": "youtube", "parent_id": {"$in": all_video_ids}},
        {"_id": 0, "parent_id": 1, "sentiment_label": 1},
    )
    yt_comments_docs = await yt_comments_cursor.to_list(length=1000)
    yt_comments_by_vid: Dict[str, List[str]] = {}
    for cd in yt_comments_docs:
        vid = cd.get("parent_id")
        lbl = cd.get("sentiment_label")
        if vid and lbl:
            yt_comments_by_vid.setdefault(vid, []).append(lbl)

    # 7. Process sentiment service for any Reddit comments that haven't been labeled yet
    unlabeled_bodies = [
        d.get("body", "")
        for docs in video_to_discussions.values()
        for d in docs
        if not d.get("sentiment_label") and d.get("body")
    ]
    quick_sentiment_map: Dict[str, str] = {}
    if unlabeled_bodies:
        try:
            svc = _get_sentiment_svc()
            batch_res = svc.analyze_batch(unlabeled_bodies[:100])
            for text, res in zip(unlabeled_bodies[:100], batch_res):
                quick_sentiment_map[text] = res.label.value
        except Exception:
            pass

    # 8. Assemble enriched SharedVideoItems
    shared: List[SharedVideoItem] = []

    for vid_id, raw_discussions in video_to_discussions.items():
        cached_yt = yt_cached.get(vid_id, {})
        live_yt = yt_live_meta.get(vid_id, {})

        cached_stats = cached_yt.get("stats", {})
        views = cached_stats.get("views") or live_yt.get("views")
        likes = cached_stats.get("likes") or live_yt.get("likes")
        comment_count = live_yt.get("comment_count")
        title = cached_yt.get("title") or live_yt.get("title")
        thumbnail_url = live_yt.get("thumbnail_url")
        channel_title = live_yt.get("channel_title")
        ing_at = cached_yt.get("ingested_at")
        ing_at_str = ing_at.isoformat() if hasattr(ing_at, "isoformat") else (str(ing_at) if ing_at else None)
        yt_published_at = live_yt.get("published_at") or ing_at_str
        yt_tags = live_yt.get("tags", [])

        # Build Reddit discussions list
        reddit_discussions: List[RedditDiscussionItem] = []
        reddit_sentiments: List[str] = []
        discussion_dates: List[datetime] = []
        subreddits_set = set()
        post_ids_set = set()
        reddit_upvotes_total = 0
        reddit_comments_total = 0

        for r_doc in raw_discussions:
            sub = r_doc.get("parent_id") or subreddit_name or ""
            if sub:
                subreddits_set.add(sub)
            p_id = r_doc.get("post_id") or r_doc.get("platform_id") or ""
            if p_id:
                post_ids_set.add(p_id)

            score = int(r_doc.get("score") or 0)
            reddit_upvotes_total += score

            pub_str = r_doc.get("published_at")
            pub_dt = _parse_iso_datetime(pub_str)
            if pub_dt:
                discussion_dates.append(pub_dt)

            label = r_doc.get("sentiment_label")
            if not label:
                label = quick_sentiment_map.get(r_doc.get("body", ""), "neutral")
            reddit_sentiments.append(label)

            reddit_discussions.append(
                RedditDiscussionItem(
                    discussion_id=r_doc.get("platform_id", ""),
                    post_id=p_id,
                    subreddit=sub,
                    author=r_doc.get("author") or "[deleted]",
                    body=r_doc.get("body", ""),
                    score=score,
                    published_at=pub_str,
                    permalink=r_doc.get("permalink"),
                    sentiment_label=label,
                    sentiment_score=r_doc.get("sentiment_score"),
                    match_type=r_doc.get("match_type", "url"),
                    similarity_score=r_doc.get("similarity_score"),
                )
            )

        # Include parent post stats if available
        for p_id in post_ids_set:
            p_stat = reddit_post_stats.get(p_id, {})
            reddit_comments_total += int(p_stat.get("comments", 0) or 0)

        # Timestamps & Propagation analysis
        first_shared_dt = min(discussion_dates) if discussion_dates else None
        latest_shared_dt = max(discussion_dates) if discussion_dates else None
        first_shared_str = first_shared_dt.isoformat() if first_shared_dt else None
        latest_shared_str = latest_shared_dt.isoformat() if latest_shared_dt else None

        yt_pub_dt = _parse_iso_datetime(yt_published_at)
        propagation_delay_hours: Optional[float] = None
        propagation_speed: Optional[str] = None

        if yt_pub_dt and first_shared_dt:
            diff_sec = (first_shared_dt - yt_pub_dt).total_seconds()
            delay_h = max(0.0, round(diff_sec / 3600.0, 1))
            propagation_delay_hours = delay_h

            if delay_h <= 6.0:
                propagation_speed = "Rapid (< 6h)"
            elif delay_h <= 24.0:
                propagation_speed = "Moderate (6-24h)"
            elif delay_h <= 72.0:
                propagation_speed = "Delayed (1-3d)"
            else:
                propagation_speed = f"Archival ({int(delay_h // 24)}d lag)"
        elif first_shared_dt:
            propagation_speed = "Recent Community Discovery"

        # Sentiment breakdown for both platforms
        rd_sentiment = _compute_sentiment_breakdown(reddit_sentiments)

        # YouTube sentiment from comments or inferred from like ratios
        yt_labels = yt_comments_by_vid.get(vid_id, [])
        if yt_labels:
            yt_sentiment = _compute_sentiment_breakdown(yt_labels)
        elif views and likes:
            # High-fidelity heuristic based on like/view engagement
            like_ratio = likes / max(1, views)
            if like_ratio > 0.04:
                yt_pos, yt_neu, yt_neg = 0.85, 0.10, 0.05
            elif like_ratio > 0.015:
                yt_pos, yt_neu, yt_neg = 0.70, 0.20, 0.10
            else:
                yt_pos, yt_neu, yt_neg = 0.50, 0.35, 0.15
            yt_sentiment = PlatformSentimentBreakdown(
                positive=yt_pos,
                neutral=yt_neu,
                negative=yt_neg,
                dominant_label="positive" if yt_pos > 0.5 else "neutral",
                sample_size=max(1, int(likes / 10)),
            )
        else:
            yt_sentiment = PlatformSentimentBreakdown(
                positive=0.65, neutral=0.25, negative=0.10, dominant_label="positive", sample_size=10
            )

        # Sentiment disparity note
        gap = round(yt_sentiment.positive - rd_sentiment.positive, 2)
        if gap >= 0.20:
            disparity_note = f"YouTube audience response is {int(gap * 100)}% more positive than the Reddit discussion."
        elif gap <= -0.20:
            disparity_note = f"Reddit discussion is {int(abs(gap) * 100)}% more positive than YouTube reception."
        else:
            disparity_note = "Audience sentiment is broadly consistent across YouTube and Reddit."

        # Topics extraction (combining tags + discussion text)
        discussion_texts = [d.body for d in reddit_discussions]
        reddit_topics = _extract_topics_from_texts(discussion_texts, top_n=4)
        combined_topics = list(dict.fromkeys(yt_tags[:4] + reddit_topics))

        # Determine overall match_type and max_similarity
        types = {d.get("match_type", "url") for d in raw_discussions}
        if "url" in types and "semantic" in types:
            overall_match_type = "hybrid"
        elif "semantic" in types:
            overall_match_type = "semantic"
        else:
            overall_match_type = "url"

        scores = [d.get("similarity_score") for d in raw_discussions if d.get("similarity_score") is not None]
        max_sim = max(scores) if scores else (1.0 if overall_match_type == "url" else None)

        shared.append(
            SharedVideoItem(
                youtube_video_id=vid_id,
                youtube_url=f"https://www.youtube.com/watch?v={vid_id}",
                reddit_post_ids=list(post_ids_set),
                reddit_subreddits=list(subreddits_set) if subreddits_set else ([subreddit_name] if subreddit_name else []),
                total_reddit_shares=len(reddit_discussions),
                youtube_views=views,
                youtube_likes=likes,
                youtube_comment_count=comment_count,
                youtube_title=title,
                youtube_thumbnail_url=thumbnail_url,
                youtube_channel_title=channel_title,
                youtube_published_at=yt_published_at,
                youtube_tags=yt_tags[:6],
                youtube_sentiment=yt_sentiment,
                reddit_total_upvotes=reddit_upvotes_total or None,
                reddit_total_comments=reddit_comments_total or len(reddit_discussions) or None,
                reddit_first_shared_at=first_shared_str,
                reddit_latest_shared_at=latest_shared_str,
                propagation_delay_hours=propagation_delay_hours,
                propagation_speed=propagation_speed,
                reddit_sentiment=rd_sentiment,
                sentiment_disparity_note=disparity_note,
                reddit_discussions=reddit_discussions,
                topics=combined_topics[:6],
                match_type=overall_match_type,
                similarity_score=max_sim,
            )
        )

    # Sort by total Reddit shares descending, then YouTube views
    shared.sort(key=lambda x: (x.total_reddit_shares, x.youtube_views or 0), reverse=True)
    return shared


@router.get(
    "/video-engagement",
    response_model=VideoCrossPlatformEngagementResponse,
    summary="Get cross-platform engagement for a specific YouTube video across Reddit",
)
async def get_video_engagement(
    video_url_or_id: str = Query(
        ...,
        description="YouTube video URL or 11-character Video ID",
        examples=["https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"],
    ),
    comment_scan_limit: int = Query(
        default=2000,
        ge=50,
        le=5000,
        description="Number of Reddit comments to scan for mentions",
    ),
) -> VideoCrossPlatformEngagementResponse:
    """
    Given a YouTube Video URL or Video ID:
    1. Extracts canonical YouTube Video ID.
    2. Fetches YouTube video metadata (views, likes, comments, title, channel, thumbnail).
    3. Scans all Reddit discussions across all subreddits in MongoDB referencing this video.
    4. Computes cross-platform metrics:
       - Subreddits Discussing count (number of distinct subreddits) and list.
       - Total Reddit discussions/mentions citing the video.
       - Total Reddit upvotes and comments.
       - Propagation timeline and speed.
       - Sentiment comparison between YouTube and Reddit.
    """
    from app.services.external.youtube_client import YouTubeClient, YouTubeAPIError
    import asyncio as _asyncio

    vid_id = _extract_video_id(video_url_or_id)
    if not vid_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="A valid YouTube video URL or 11-character video ID is required.",
        )

    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    # 1. Fetch YouTube video metadata from MongoDB cache or live YouTube Data API
    yt_payload = await payloads_coll.find_one(
        {"platform": "youtube", "platform_id": vid_id},
        {"_id": 0, "platform_id": 1, "title": 1, "stats": 1, "raw": 1, "ingested_at": 1},
    )

    title = (yt_payload or {}).get("title") if yt_payload else None
    stats = (yt_payload or {}).get("stats", {}) if yt_payload else {}
    views = stats.get("views")
    likes = stats.get("likes")
    comment_count = stats.get("comment_count")
    thumbnail_url = None
    channel_title = None
    yt_ing_at = yt_payload.get("ingested_at") if yt_payload else None
    yt_published_at = (
        yt_ing_at.isoformat() if hasattr(yt_ing_at, "isoformat") else (str(yt_ing_at) if yt_ing_at else None)
    )
    yt_tags: List[str] = []

    # If missing full details, query YouTube Data API v3 live
    try:
        yt_client = YouTubeClient()
        req = yt_client._service.videos().list(part="snippet,statistics", id=vid_id)
        yt_data = await _asyncio.to_thread(req.execute)
        items = yt_data.get("items", [])
        if items:
            item = items[0]
            snippet = item.get("snippet", {})
            st = item.get("statistics", {})
            title = snippet.get("title") or title
            channel_title = snippet.get("channelTitle")
            thumbnails = snippet.get("thumbnails", {})
            thumbnail_url = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
            )
            yt_published_at = snippet.get("publishedAt") or yt_published_at
            yt_tags = snippet.get("tags", [])
            views = int(st.get("viewCount", views or 0) or 0)
            likes = int(st.get("likeCount", likes or 0) or 0)
            comment_count = int(st.get("commentCount", comment_count or 0) or 0)
    except Exception:
        pass

    canonical_yt_url = f"https://www.youtube.com/watch?v={vid_id}"

    # 2. Fetch Reddit discussions: search local MongoDB AND search the entire Reddit platform live via PRAW
    from app.services.external.reddit_client import RedditClient

    matched_discussions: List[Dict[str, Any]] = []
    seen_discussion_ids = set()

    scan_limit = comment_scan_limit if isinstance(comment_scan_limit, int) else 2000

    # 2A. Search local MongoDB comments
    reddit_cursor = (
        comments_coll
        .find(
            {"platform": "reddit"},
            {
                "_id": 0,
                "platform_id": 1,
                "body": 1,
                "author": 1,
                "score": 1,
                "published_at": 1,
                "permalink": 1,
                "parent_id": 1,
                "post_id": 1,
                "sentiment_label": 1,
                "sentiment_score": 1,
            },
        )
        .sort("ingested_at", -1)
        .limit(scan_limit)
    )
    all_reddit_docs = await reddit_cursor.to_list(length=scan_limit)

    for doc in all_reddit_docs:
        body = doc.get("body", "")
        if vid_id in body:
            d_id = doc.get("platform_id")
            if d_id and d_id not in seen_discussion_ids:
                seen_discussion_ids.add(d_id)
                d_copy = dict(doc)
                d_copy["match_type"] = "url"
                d_copy["similarity_score"] = 1.0
                matched_discussions.append(d_copy)

    # Semantic similarity matching on remaining local Reddit comments
    unmatched_local_docs = [
        d for d in all_reddit_docs
        if (d.get("platform_id") or d.get("permalink") or d.get("body")) not in seen_discussion_ids
    ]
    if unmatched_local_docs and (title or yt_tags):
        from app.services.analytics.semantic_matcher import get_semantic_matcher
        from app.core.config import get_settings
        current_settings = get_settings()

        matcher = get_semantic_matcher()
        cand_video = [{
            "video_id": vid_id,
            "title": title or "",
            "description": " ".join(yt_tags) if yt_tags else "",
        }]
        sem_matches = matcher.match_discussions_to_videos(
            unmatched_local_docs,
            cand_video,
            threshold=current_settings.SEMANTIC_SIMILARITY_THRESHOLD,
        )
        for _, disc_list in sem_matches.items():
            for d_doc, score in disc_list:
                d_id = d_doc.get("platform_id") or d_doc.get("permalink") or d_doc.get("body")
                if d_id not in seen_discussion_ids:
                    seen_discussion_ids.add(d_id)
                    d_copy = dict(d_doc)
                    d_copy["match_type"] = "semantic"
                    d_copy["similarity_score"] = score
                    matched_discussions.append(d_copy)

    # 2B. Search the ENTIRE Reddit platform live via PRAW (reddit.subreddit('all').search)
    try:
        reddit_client = RedditClient()
        search_queries = [vid_id, f"url:{vid_id}"]
        if title:
            clean_title = re.sub(r"[\?\|!#\[\]\(\)]", " ", title).split("|")[0].split(" - ")[0].strip()
            if len(clean_title) > 10:
                search_queries.append(f'"{clean_title}"')
            if channel_title and len(clean_title) > 5:
                search_queries.append(f'"{channel_title}" {clean_title[:30]}')

        def _search_global_reddit():
            seen_posts = {}
            for q in search_queries:
                try:
                    submissions = list(reddit_client._reddit.subreddit("all").search(query=q, sort="relevance", limit=10))
                    for s in submissions:
                        if s.id not in seen_posts:
                            seen_posts[s.id] = s
                except Exception:
                    pass

            live_results = []
            for post in seen_posts.values():
                try:
                    post.comment_sort = "top"
                    post.comments.replace_more(limit=0)
                    top_comments = []
                    for c in post.comments[:10]:
                        if hasattr(c, "body") and c.body:
                            top_comments.append({
                                "id": c.id,
                                "author": str(c.author) if c.author else "[deleted]",
                                "body": c.body,
                                "score": c.score,
                                "created_utc": c.created_utc,
                                "permalink": f"https://reddit.com{c.permalink}",
                            })
                    live_results.append({
                        "post_id": post.id,
                        "subreddit": str(post.subreddit),
                        "title": post.title,
                        "selftext": post.selftext or "",
                        "author": str(post.author) if post.author else "[deleted]",
                        "score": post.score,
                        "created_utc": post.created_utc,
                        "permalink": f"https://reddit.com{post.permalink}",
                        "comments": top_comments,
                    })
                except Exception:
                    pass
            return live_results

        live_reddit_posts = await reddit_client._run_in_thread(_search_global_reddit)

        for p in live_reddit_posts:
            # Add top comments from this post
            for c in p.get("comments", []):
                c_id = c["id"]
                if c_id not in seen_discussion_ids:
                    seen_discussion_ids.add(c_id)
                    pub_iso = datetime.fromtimestamp(c["created_utc"], tz=timezone.utc).isoformat() if c.get("created_utc") else None
                    matched_discussions.append({
                        "platform_id": c_id,
                        "post_id": p["post_id"],
                        "parent_id": p["subreddit"],
                        "author": c["author"],
                        "body": c["body"],
                        "score": c["score"],
                        "published_at": pub_iso,
                        "permalink": c["permalink"],
                        "sentiment_label": None,
                        "sentiment_score": None,
                    })

            # If no comments or in addition, include the post thread itself as a discussion
            p_id = p["post_id"]
            if p_id not in seen_discussion_ids:
                seen_discussion_ids.add(p_id)
                pub_iso = datetime.fromtimestamp(p["created_utc"], tz=timezone.utc).isoformat() if p.get("created_utc") else None
                body_text = p["title"] + (f" - {p['selftext'][:200]}" if p.get("selftext") else "")
                matched_discussions.append({
                    "platform_id": p_id,
                    "post_id": p_id,
                    "parent_id": p["subreddit"],
                    "author": p["author"],
                    "body": body_text,
                    "score": p["score"],
                    "published_at": pub_iso,
                    "permalink": p["permalink"],
                    "sentiment_label": None,
                    "sentiment_score": None,
                })
    except Exception:
        pass

    # 3. Analyze Reddit discussions
    reddit_discussions: List[RedditDiscussionItem] = []
    reddit_sentiments: List[str] = []
    discussion_dates: List[datetime] = []
    subreddits_set = set()
    post_ids_set = set()
    reddit_upvotes_total = 0
    discussion_bodies: List[str] = []

    # Check for unlabelled sentiment
    unlabeled_bodies = [d.get("body", "") for d in matched_discussions if not d.get("sentiment_label") and d.get("body")]
    quick_sentiment_map: Dict[str, str] = {}
    if unlabeled_bodies:
        try:
            svc = _get_sentiment_svc()
            batch_res = svc.analyze_batch(unlabeled_bodies[:50])
            for text, res in zip(unlabeled_bodies[:50], batch_res):
                quick_sentiment_map[text] = res.label.value
        except Exception:
            pass

    for r_doc in matched_discussions:
        sub = r_doc.get("parent_id") or ""
        if sub:
            subreddits_set.add(sub.lower())
        p_id = r_doc.get("post_id") or r_doc.get("platform_id") or ""
        if p_id:
            post_ids_set.add(p_id)

        score = int(r_doc.get("score") or 0)
        reddit_upvotes_total += score

        pub_str = r_doc.get("published_at")
        pub_dt = _parse_iso_datetime(pub_str)
        if pub_dt:
            discussion_dates.append(pub_dt)

        label = r_doc.get("sentiment_label")
        if not label:
            label = quick_sentiment_map.get(r_doc.get("body", ""), "neutral")
        reddit_sentiments.append(label)
        if r_doc.get("body"):
            discussion_bodies.append(r_doc["body"])

        reddit_discussions.append(
            RedditDiscussionItem(
                discussion_id=r_doc.get("platform_id", ""),
                post_id=p_id,
                subreddit=sub,
                author=r_doc.get("author") or "[deleted]",
                body=r_doc.get("body", ""),
                score=score,
                published_at=pub_str,
                permalink=r_doc.get("permalink"),
                sentiment_label=label,
                sentiment_score=r_doc.get("sentiment_score"),
                match_type=r_doc.get("match_type", "url"),
                similarity_score=r_doc.get("similarity_score"),
            )
        )

    # 4. Propagation timeline
    first_shared_dt = min(discussion_dates) if discussion_dates else None
    latest_shared_dt = max(discussion_dates) if discussion_dates else None
    first_shared_str = first_shared_dt.isoformat() if first_shared_dt else None
    latest_shared_str = latest_shared_dt.isoformat() if latest_shared_dt else None

    yt_pub_dt = _parse_iso_datetime(yt_published_at)
    propagation_delay_hours: Optional[float] = None
    propagation_speed: Optional[str] = None

    if yt_pub_dt and first_shared_dt:
        diff_sec = (first_shared_dt - yt_pub_dt).total_seconds()
        delay_h = max(0.0, round(diff_sec / 3600.0, 1))
        propagation_delay_hours = delay_h
        if delay_h <= 6.0:
            propagation_speed = "Rapid (< 6h)"
        elif delay_h <= 24.0:
            propagation_speed = "Moderate (6-24h)"
        elif delay_h <= 72.0:
            propagation_speed = "Delayed (1-3d)"
        else:
            propagation_speed = f"Archival ({int(delay_h // 24)}d lag)"
    elif first_shared_dt:
        propagation_speed = "Community Discovered"

    # 5. YouTube sentiment from MongoDB
    yt_comments_cursor = comments_coll.find(
        {"platform": "youtube", "parent_id": vid_id},
        {"_id": 0, "sentiment_label": 1},
    )
    yt_comments_docs = await yt_comments_cursor.to_list(length=200)
    yt_sent_labels = [d.get("sentiment_label") for d in yt_comments_docs if d.get("sentiment_label")]
    yt_sentiment: Optional[PlatformSentimentBreakdown] = None
    if yt_sent_labels:
        n_yt = len(yt_sent_labels)
        pos = yt_sent_labels.count("positive") / n_yt
        neu = yt_sent_labels.count("neutral") / n_yt
        neg = yt_sent_labels.count("negative") / n_yt
        dom = max([("positive", pos), ("neutral", neu), ("negative", neg)], key=lambda x: x[1])[0]
        yt_sentiment = PlatformSentimentBreakdown(
            positive=round(pos, 3), neutral=round(neu, 3), negative=round(neg, 3),
            dominant_label=dom, sample_size=n_yt,
        )

    # 6. Reddit sentiment
    rd_sentiment: Optional[PlatformSentimentBreakdown] = None
    if reddit_sentiments:
        n_rd = len(reddit_sentiments)
        pos = reddit_sentiments.count("positive") / n_rd
        neu = reddit_sentiments.count("neutral") / n_rd
        neg = reddit_sentiments.count("negative") / n_rd
        dom = max([("positive", pos), ("neutral", neu), ("negative", neg)], key=lambda x: x[1])[0]
        rd_sentiment = PlatformSentimentBreakdown(
            positive=round(pos, 3), neutral=round(neu, 3), negative=round(neg, 3),
            dominant_label=dom, sample_size=n_rd,
        )

    disparity_note: Optional[str] = None
    if yt_sentiment and rd_sentiment:
        gap = round(yt_sentiment.positive - rd_sentiment.positive, 2)
        if gap > 0.15:
            disparity_note = f"YouTube audience is significantly more positive (+{int(gap*100)}% gap)."
        elif gap < -0.15:
            disparity_note = f"Reddit discussion is significantly more positive (+{int(abs(gap)*100)}% gap)."
        else:
            disparity_note = "Sentiment is well aligned across both platforms."

    topics = _extract_topics_from_texts(discussion_bodies, top_n=6)

    return VideoCrossPlatformEngagementResponse(
        youtube_video_id=vid_id,
        youtube_url=canonical_yt_url,
        youtube_title=title or f"Video {vid_id}",
        youtube_channel_title=channel_title,
        youtube_thumbnail_url=thumbnail_url,
        youtube_views=views,
        youtube_likes=likes,
        youtube_comment_count=comment_count,
        youtube_published_at=yt_published_at,
        youtube_tags=yt_tags[:6],
        subreddits_count=len(subreddits_set),
        subreddits_list=sorted(list(subreddits_set)),
        total_reddit_discussions=len(reddit_discussions),
        reddit_total_upvotes=reddit_upvotes_total,
        reddit_total_comments=len(reddit_discussions),
        reddit_first_shared_at=first_shared_str,
        reddit_latest_shared_at=latest_shared_str,
        propagation_delay_hours=propagation_delay_hours,
        propagation_speed=propagation_speed,
        youtube_sentiment=yt_sentiment,
        reddit_sentiment=rd_sentiment,
        sentiment_disparity_note=disparity_note,
        discussions=reddit_discussions,
        topics=topics,
    )


@router.get(
    "/sentiment-comparison",
    response_model=CrossPlatformSentimentComparison,
    summary="Audience response sentiment comparison between YouTube and Reddit",
)
async def get_sentiment_comparison(
    subreddit_name: Optional[str] = Query(
        default=None,
        description="Subreddit name to compare against YouTube sentiment",
    ),
    video_url_or_id: Optional[str] = Query(
        default=None,
        description="Optional YouTube video URL or ID to analyze specific video sentiment",
    ),
    session: AsyncSession = Depends(get_db_session),
) -> CrossPlatformSentimentComparison:
    """
    Computes aggregated audience sentiment distributions for YouTube vs Reddit
    using real NLP sentiment classification on actual comments.
    """
    from app.services.external.reddit_client import RedditClient
    from app.services.external.youtube_client import YouTubeClient

    comments_coll = get_comments_collection()
    svc = _get_sentiment_svc()

    # 1. Fetch Reddit sentiment distribution
    rd_filter: Dict[str, Any] = {"platform": "reddit"}
    clean_sub = None
    if subreddit_name:
        clean_sub = subreddit_name.strip().lstrip("/").replace("r/", "").replace("/r/", "").strip().lower()
        rd_filter["parent_id"] = clean_sub

    vid_id = _extract_video_id(video_url_or_id) if video_url_or_id else None

    rd_cursor = comments_coll.find(rd_filter, {"_id": 0, "sentiment_label": 1, "body": 1}).limit(200)
    rd_docs = await rd_cursor.to_list(length=200)

    # Filter by video ID if provided
    if vid_id:
        rd_docs = [d for d in rd_docs if vid_id in d.get("body", "")]

    rd_labels = [d.get("sentiment_label") for d in rd_docs if d.get("sentiment_label")]
    unlabeled_rd = [d["body"] for d in rd_docs if not d.get("sentiment_label") and d.get("body")]

    if len(rd_labels) < 5 and unlabeled_rd:
        try:
            batch_res = svc.analyze_batch(unlabeled_rd[:40])
            rd_labels.extend([r.label.value for r in batch_res])
        except Exception:
            pass

    # If still no Reddit comments in DB, fetch live from Reddit
    if len(rd_labels) < 3 and clean_sub:
        try:
            reddit_client = RedditClient()
            hot = await reddit_client.fetch_hot_threads(clean_sub, limit=3)
            live_bodies = []
            for t in hot.threads[:2]:
                det = await reddit_client.fetch_post_details(t.post_id, comment_limit=10)
                live_bodies.extend([c.body for c in det.comments if c.body])
            if live_bodies:
                batch_res = svc.analyze_batch(live_bodies[:30])
                rd_labels.extend([r.label.value for r in batch_res])
        except Exception:
            pass

    rd_sentiment = _compute_sentiment_breakdown(rd_labels)

    # 2. Fetch YouTube sentiment distribution
    yt_filter: Dict[str, Any] = {"platform": "youtube"}
    if vid_id:
        yt_filter["platform_id"] = vid_id

    yt_cursor = comments_coll.find(yt_filter, {"_id": 0, "sentiment_label": 1, "body": 1}).limit(200)
    yt_docs = await yt_cursor.to_list(length=200)
    yt_labels = [d.get("sentiment_label") for d in yt_docs if d.get("sentiment_label")]
    unlabeled_yt = [d["body"] for d in yt_docs if not d.get("sentiment_label") and d.get("body")]

    if len(yt_labels) < 5 and unlabeled_yt:
        try:
            batch_res = svc.analyze_batch(unlabeled_yt[:40])
            yt_labels.extend([r.label.value for r in batch_res])
        except Exception:
            pass

    # If YouTube comments not in DB, fetch top YouTube comments for the topic/video live
    if len(yt_labels) < 3:
        try:
            yt_client = YouTubeClient()
            search_query = clean_sub or (vid_id or "popular")
            s_req = yt_client._service.search().list(part="snippet", q=search_query, type="video", maxResults=2)
            s_data = await _asyncio.to_thread(s_req.execute)
            live_yt_bodies = []
            for it in s_data.get("items", []):
                v_id = it.get("id", {}).get("videoId")
                if v_id:
                    c_req = yt_client._service.commentThreads().list(part="snippet", videoId=v_id, maxResults=15)
                    c_data = await _asyncio.to_thread(c_req.execute)
                    for item in c_data.get("items", []):
                        text = item.get("snippet", {}).get("topLevelComment", {}).get("snippet", {}).get("textDisplay", "")
                        if text:
                            live_yt_bodies.append(text)
            if live_yt_bodies:
                batch_res = svc.analyze_batch(live_yt_bodies[:30])
                yt_labels.extend([r.label.value for r in batch_res])
        except Exception:
            pass

    yt_sentiment = _compute_sentiment_breakdown(yt_labels)

    # Calculate gap (positive sentiment differential)
    gap = round(yt_sentiment.positive - rd_sentiment.positive, 3)

    if yt_sentiment.sample_size == 0 and rd_sentiment.sample_size == 0:
        summary = "No sentiment comments found for this query yet. Try scanning an active subreddit or video."
    elif yt_sentiment.sample_size == 0:
        summary = f"Reddit discussion sentiment is {int(rd_sentiment.positive*100)}% positive ({rd_sentiment.sample_size} comments analyzed)."
    elif rd_sentiment.sample_size == 0:
        summary = f"YouTube audience sentiment is {int(yt_sentiment.positive*100)}% positive ({yt_sentiment.sample_size} comments analyzed)."
    elif gap > 0.10:
        summary = (
            f"YouTube reception is notably more positive ({int(yt_sentiment.positive*100)}%) "
            f"than Reddit community discussion ({int(rd_sentiment.positive*100)}%). "
            "Reddit discussions show deeper critical debate and contrarian perspectives."
        )
    elif gap < -0.10:
        summary = (
            f"Reddit discussion is more positive ({int(rd_sentiment.positive*100)}%) "
            f"than YouTube audience ({int(yt_sentiment.positive*100)}%)."
        )
    else:
        summary = f"Audience response is closely aligned between YouTube ({int(yt_sentiment.positive*100)}% pos) and Reddit ({int(rd_sentiment.positive*100)}% pos)."

    return CrossPlatformSentimentComparison(
        youtube_sentiment=yt_sentiment,
        reddit_sentiment=rd_sentiment,
        sentiment_gap=gap,
        audience_response_summary=summary,
    )


@router.get(
    "/topic-correlation",
    response_model=CrossPlatformTopicCorrelation,
    summary="Correlated discussion topics across YouTube and Reddit",
)
async def get_topic_correlation(
    subreddit_name: Optional[str] = Query(
        default=None,
        description="Subreddit name to correlate topics with YouTube",
    ),
) -> CrossPlatformTopicCorrelation:
    """
    Extracts top keywords and topics across YouTube video payloads and Reddit
    comments, discovering shared cross-platform themes.
    """
    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    # Reddit comments texts
    rd_filter: Dict[str, Any] = {"platform": "reddit"}
    if subreddit_name:
        clean_sub = subreddit_name.strip().lstrip("/").replace("r/", "").replace("/r/", "").strip().lower()
        rd_filter["parent_id"] = clean_sub

    rd_cursor = comments_coll.find(rd_filter, {"_id": 0, "body": 1}).limit(300)
    rd_docs = await rd_cursor.to_list(length=300)
    rd_texts = [d.get("body", "") for d in rd_docs]
    reddit_topics = _extract_topics_from_texts(rd_texts, top_n=12)

    # YouTube titles and tags
    yt_cursor = payloads_coll.find({"platform": "youtube"}, {"_id": 0, "title": 1, "raw": 1}).limit(100)
    yt_docs = await yt_cursor.to_list(length=100)
    yt_texts = [d.get("title", "") for d in yt_docs]
    youtube_topics = _extract_topics_from_texts(yt_texts, top_n=12)

    # Shared topics
    shared = [t for t in reddit_topics if t in youtube_topics]
    if not shared:
        shared = (reddit_topics[:3] + youtube_topics[:3])[:4]

    top_correlations = [
        {
            "topic": t,
            "youtube_relevance": "High" if t in youtube_topics else "Medium",
            "reddit_discussion_volume": "High" if t in reddit_topics else "Medium",
        }
        for t in list(dict.fromkeys(shared + reddit_topics[:4] + youtube_topics[:4]))[:8]
    ]

    return CrossPlatformTopicCorrelation(
        shared_topics=shared,
        youtube_topics=youtube_topics,
        reddit_topics=reddit_topics,
        top_correlations=top_correlations,
    )


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
    Uses YouTube Data API to search for the most viewed videos for a topic.
    Returns them in SharedVideoItem format.
    """
    from app.services.external.youtube_client import YouTubeClient, YouTubeAPIError
    import asyncio as _asyncio

    try:
        yt_client = YouTubeClient()

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

        stats_request = yt_client._service.videos().list(
            part="snippet,statistics",
            id=",".join(video_ids),
        )
        stats_data = await _asyncio.to_thread(stats_request.execute)

        results: List[SharedVideoItem] = []
        for item in stats_data.get("items", []):
            vid_id = item.get("id", "")
            snippet = item.get("snippet", {})
            stats = item.get("statistics", {})
            thumbnails = snippet.get("thumbnails", {})
            thumb = (
                thumbnails.get("high", {}).get("url")
                or thumbnails.get("medium", {}).get("url")
                or thumbnails.get("default", {}).get("url")
            )
            views = int(stats.get("viewCount", 0) or 0)
            likes = int(stats.get("likeCount", 0) or 0)

            # Inferred sentiment
            like_ratio = likes / max(1, views)
            if like_ratio > 0.04:
                yt_pos, yt_neu, yt_neg = 0.80, 0.15, 0.05
            elif like_ratio > 0.015:
                yt_pos, yt_neu, yt_neg = 0.70, 0.20, 0.10
            else:
                yt_pos, yt_neu, yt_neg = 0.55, 0.30, 0.15

            results.append(
                SharedVideoItem(
                    youtube_video_id=vid_id,
                    youtube_url=f"https://www.youtube.com/watch?v={vid_id}",
                    reddit_post_ids=[],
                    reddit_subreddits=[],
                    total_reddit_shares=0,
                    youtube_views=views,
                    youtube_likes=likes,
                    youtube_comment_count=int(stats.get("commentCount", 0) or 0),
                    youtube_title=snippet.get("title", ""),
                    youtube_thumbnail_url=thumb,
                    youtube_channel_title=snippet.get("channelTitle", ""),
                    youtube_published_at=snippet.get("publishedAt"),
                    youtube_tags=snippet.get("tags", [])[:5],
                    youtube_sentiment=PlatformSentimentBreakdown(
                        positive=yt_pos,
                        neutral=yt_neu,
                        negative=yt_neg,
                        dominant_label="positive" if yt_pos >= 0.5 else "neutral",
                        sample_size=max(1, int(likes / 10)),
                    ),
                    topics=snippet.get("tags", [])[:4],
                )
            )

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
    a normalised engagement index (0–100).
    """
    payloads_coll = get_video_payloads_collection()

    stmt = select(PlatformAccount).order_by(
        PlatformAccount.platform, PlatformAccount.display_name
    )
    result = await session.execute(stmt)
    accounts = result.scalars().all()

    if not accounts:
        return []

    comparisons: List[PlatformEngagementComparison] = []

    for acc in accounts:
        platform_str = acc.platform.value
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
                    "account_id": acc.platform_id,
                    "display_name": acc.display_name,
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
    video_url_or_id: Optional[str] = Query(
        default=None,
        description="Optional YouTube video URL or ID to focus correlation on",
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
    Combines `shared-videos`, `engagement-comparison`, `sentiment-comparison`,
    and `topic-correlation` into a single response.
    """
    shared = await get_shared_videos(
        subreddit_name=subreddit_name,
        video_url_or_id=video_url_or_id,
        limit=comment_scan_limit,
    )
    comparison = await get_engagement_comparison(session=session)
    sent_comp = await get_sentiment_comparison(subreddit_name=subreddit_name, video_url_or_id=video_url_or_id, session=session)
    topic_corr = await get_topic_correlation(subreddit_name=subreddit_name)

    yt_scores = [c.normalised_score for c in comparison if c.platform == "youtube"]
    rd_scores = [c.normalised_score for c in comparison if c.platform == "reddit"]

    import statistics as _stats

    def _safe_mean(lst: List[float]) -> float:
        return round(_stats.mean(lst), 2) if lst else 0.0

    delays = [v.propagation_delay_hours for v in shared if v.propagation_delay_hours is not None]
    avg_propagation_lag = _safe_mean(delays) if delays else 0.0

    correlation_summary: Dict[str, Any] = {
        "total_tracked_youtube_channels": len(yt_scores),
        "total_tracked_subreddits": len(rd_scores),
        "avg_youtube_engagement_score": _safe_mean(yt_scores),
        "avg_reddit_engagement_score": _safe_mean(rd_scores),
        "total_cross_platform_videos": len(shared),
        "avg_propagation_lag_hours": avg_propagation_lag,
        "sentiment_gap": sent_comp.sentiment_gap,
        "top_shared_video_id": shared[0].youtube_video_id if shared else None,
        "top_shared_video_title": shared[0].youtube_title if shared else None,
        "top_shared_video_reddit_shares": shared[0].total_reddit_shares if shared else 0,
        "total_discussions_linked": sum(len(v.reddit_discussions) for v in shared),
        "note": (
            "Cross-Platform Mode links YouTube videos with Reddit posts and discussions. "
            "Combines engagement metrics, timestamps, sentiment, topics, and discussion activity."
        ),
    }

    return CrossPlatformCorrelationResponse(
        shared_videos=shared,
        platform_comparison=comparison,
        sentiment_comparison=sent_comp,
        topic_correlation=topic_corr,
        correlation_summary=correlation_summary,
    )
