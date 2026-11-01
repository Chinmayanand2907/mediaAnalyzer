"""
Chatbot Router  —  /api/v1/chatbot
====================================

Endpoints
---------
POST /query   — Accept a user question + active dashboard context, pull
                REAL-TIME metrics from MongoDB + PostgreSQL, inject them
                into a dynamic system prompt, and return an AI answer from
                DeepSeek V4.1 Flash via River.ai.

Context → System Prompt mapping
--------------------------------
  youtube       →  Video Performance Consultant  (real YT channel stats)
  reddit        →  Community Management Specialist  (real subreddit stats)
  cross-platform→  Cross-Channel Strategist (stats from both platforms)

Data flow
---------
  1. Fetch real metrics from MongoDB (video_payloads, comments) + PostgreSQL
  2. Build a context block with actual numbers
  3. Inject into system prompt before the LLM call
  4. LLM answers ONLY based on provided real data
"""

from __future__ import annotations

import asyncio
import re
import string
import time
from collections import Counter
from typing import Literal, Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from openai import AsyncOpenAI, APIConnectionError, AuthenticationError, RateLimitError
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.db.mongodb import get_comments_collection, get_video_payloads_collection, get_mongo_db
from app.db.postgres import Platform, PlatformAccount, AsyncSessionLocal

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

# ── Module-level AsyncOpenAI client singleton ────────────────────────────────
# Re-using one client across requests keeps the underlying HTTP connection pool
# warm, eliminating the TLS handshake overhead on every chat turn.
_llm_client: AsyncOpenAI | None = None

def _get_llm_client() -> AsyncOpenAI:
    global _llm_client
    settings = get_settings()
    if _llm_client is None:
        _llm_client = AsyncOpenAI(
            api_key=settings.RIVER_API_KEY,
            base_url="https://api.river.ai/v1",
        )
    return _llm_client

_sentiment_svc = None


def _get_sentiment_svc():
    global _sentiment_svc
    if _sentiment_svc is None:
        from app.services.analytics.sentiment_service import SentimentService
        _sentiment_svc = SentimentService()
    return _sentiment_svc

# ─── In-Memory TTL Cache for Context Data ──────────────────────────────────────
# Caches fetched database context for 60 seconds to eliminate redundant roundtrips
# on multi-turn conversations while ensuring fresh data.

_CONTEXT_CACHE: dict[str, tuple[float, str]] = {}
_CACHE_TTL_SECONDS = 180.0  # 3 minutes — context data changes slowly; reduces DB roundtrips


def _get_cached_context(key: str) -> Optional[str]:
    entry = _CONTEXT_CACHE.get(key)
    if entry:
        ts, val = entry
        if time.time() - ts < _CACHE_TTL_SECONDS:
            return val
    return None


def _set_cached_context(key: str, val: str) -> None:
    _CONTEXT_CACHE[key] = (time.time(), val)


# ─── Stopwords for keyword extraction ─────────────────────────────────────────

_STOPWORDS = frozenset(
    "the a an and or but in on at to for of with by from is are was were be been "
    "being have has had do does did will would could should may might shall can "
    "not no nor so yet both either neither one two three i me my we our you your "
    "he she it its they them their this that these those what which who whom how "
    "when where why than then also just more very much many some any all each "
    "about after before between into through during again further once".split()
)

# ─── Helpers ──────────────────────────────────────────────────────────────────

def _fmt(n) -> str:
    if n is None:
        return "N/A"
    n = int(n)
    if n >= 1_000_000_000:
        return f"{n/1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n/1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n/1_000:.1f}K"
    return str(n)


def _extract_keywords(texts: list[str], top_n: int = 8) -> list[str]:
    """Extract top keywords from a list of comment bodies."""
    words = []
    for t in texts:
        t = t.lower()
        t = re.sub(r"http\S+", "", t)
        t = t.translate(str.maketrans("", "", string.punctuation))
        for w in t.split():
            if len(w) > 3 and w not in _STOPWORDS:
                words.append(w)
    counts = Counter(words)
    return [w for w, _ in counts.most_common(top_n)]


# ─── Real-time context fetchers (Concurrent + Optimized) ──────────────────────

async def _fetch_single_channel_summary(
    ch: dict,
    payloads_coll,
    comments_coll,
    is_active: bool,
) -> str:
    """Fetch metrics and sentiment for a single YouTube channel.

    Uses a single $facet aggregation to get total + per-sentiment counts in
    ONE MongoDB round-trip instead of four separate count_documents calls.
    """
    chan_id = ch["channel_id"]
    name = ch["name"]

    # Single $facet aggregation replaces 4 separate count_documents calls
    facet_pipeline = [
        {"$match": {"platform": "youtube", "parent_id": chan_id}},
        {"$facet": {
            "total":    [{"$count": "n"}],
            "positive": [{"$match": {"sentiment_label": "positive"}}, {"$count": "n"}],
            "negative": [{"$match": {"sentiment_label": "negative"}}, {"$count": "n"}],
            "neutral":  [{"$match": {"sentiment_label": "neutral"}},  {"$count": "n"}],
            "sample":   [{"$sort": {"ingested_at": -1}}, {"$limit": 30},
                         {"$project": {"_id": 0, "body": 1}}],
        }},
    ]

    payload_task = payloads_coll.find_one(
        {"platform": "youtube", "platform_id": chan_id},
        {"_id": 0, "stats": 1},
    )
    facet_task = comments_coll.aggregate(facet_pipeline).to_list(length=1)

    results = await asyncio.gather(payload_task, facet_task, return_exceptions=True)

    payload   = results[0] if not isinstance(results[0], Exception) else None
    facet_res = (results[1] or [{}])[0] if not isinstance(results[1], Exception) else {}

    total_comments = (facet_res.get("total") or [{}])[0].get("n", 0)
    pos_count      = (facet_res.get("positive") or [{}])[0].get("n", 0)
    neg_count      = (facet_res.get("negative") or [{}])[0].get("n", 0)
    neu_count      = (facet_res.get("neutral")  or [{}])[0].get("n", 0)
    sample_docs    = facet_res.get("sample") or []

    stats = (payload or {}).get("stats", {}) if payload else {}
    bodies = [d.get("body", "") for d in sample_docs if d.get("body")]
    keywords = _extract_keywords(bodies, top_n=5) if bodies else []
    total_labeled = pos_count + neg_count + neu_count

    lines = [
        f"\n  Channel: {name} (ID: {chan_id})",
        f"    Subscribers: {_fmt(stats.get('subscribers') or ch.get('subscribers'))}",
        f"    Total Views: {_fmt(stats.get('views'))}",
        f"    Total Likes: {_fmt(stats.get('likes'))}",
        f"    Total Videos: {_fmt(stats.get('videos') or stats.get('video_count'))}",
        f"    Tracked Comments: {_fmt(total_comments)}",
    ]

    if total_labeled > 0:
        dominant = max(
            [("positive", pos_count), ("neutral", neu_count), ("negative", neg_count)],
            key=lambda x: x[1]
        )[0]
        lines.append(
            f"    Sentiment ({total_labeled} analyzed): "
            f"✅ {pos_count} positive | ⚪ {neu_count} neutral | ❌ {neg_count} negative"
        )
        lines.append(f"    Dominant Sentiment: {dominant}")
    elif bodies and is_active:
        try:
            svc = _get_sentiment_svc()
            model_results = svc.analyze_batch(bodies[:20])
            agg = svc.aggregate_sentiment(model_results)
            p_pct = round(agg["positive"] * 100)
            u_pct = round(agg["neutral"] * 100)
            n_pct = round(agg["negative"] * 100)
            lines.append(
                f"    Sentiment (analyzed {len(model_results)} recent comments): "
                f"✅ {p_pct}% positive | ⚪ {u_pct}% neutral | ❌ {n_pct}% negative"
            )
            lines.append(f"    Dominant Sentiment: {agg['dominant_label']}")
        except Exception:
            lines.append(f"    Sentiment: {total_comments} comments tracked (sentiment classification pending)")
    elif total_comments > 0:
        lines.append(f"    Sentiment: {total_comments} comments tracked (classification queued)")
    else:
        lines.append("    Sentiment: No comments ingested yet")

    if keywords:
        lines.append(f"    Top Keywords in Comments: {', '.join(keywords)}")

    return "\n".join(lines)


async def _fetch_youtube_context(active_channel_id: Optional[str] = None) -> str:
    """Pull real YouTube metrics from PostgreSQL + MongoDB with parallelized I/O and caching."""
    cache_key = f"youtube:{active_channel_id or ''}"
    cached = _get_cached_context(cache_key)
    if cached is not None:
        return cached

    from sqlalchemy import select as sa_select

    try:
        payloads_coll = get_video_payloads_collection()
        comments_coll = get_comments_collection()

        channels_data = []
        async with AsyncSessionLocal() as session:
            stmt = sa_select(PlatformAccount).where(
                PlatformAccount.platform == Platform.YOUTUBE
            )
            result = await session.execute(stmt)
            accounts = result.scalars().all()
            for acc in accounts:
                channels_data.append({
                    "channel_id": acc.platform_id,
                    "name": acc.display_name or acc.platform_id,
                    "subscribers": acc.subscriber_count,
                })

        if not channels_data:
            res = "No YouTube channels are currently being tracked in the database."
            _set_cached_context(cache_key, res)
            return res

        # If user is currently viewing a specific channel, prioritize it first
        if active_channel_id:
            channels_data.sort(
                key=lambda x: (
                    0 if x["channel_id"].lower() == active_channel_id.lower()
                    or active_channel_id.lower() in x["name"].lower()
                    else 1
                )
            )

        header_lines = [f"TRACKED YOUTUBE CHANNELS ({len(channels_data)} total):"]
        if active_channel_id:
            header_lines.append(f"  [User is currently viewing: {active_channel_id}]")

        tasks = [
            _fetch_single_channel_summary(
                ch,
                payloads_coll,
                comments_coll,
                is_active=(idx == 0 and bool(active_channel_id)),
            )
            for idx, ch in enumerate(channels_data[:6])
        ]
        channel_summaries = await asyncio.gather(*tasks)
        res = "\n".join(header_lines) + "\n" + "\n".join(channel_summaries)
        _set_cached_context(cache_key, res)
        return res

    except Exception as exc:
        return f"(Could not fetch YouTube data: {exc})"


async def _fetch_single_subreddit_summary(
    sub: dict,
    payloads_coll,
    comments_coll,
    is_active: bool,
) -> str:
    """Fetch metrics and sentiment for a single subreddit.

    Uses a single $facet aggregation to get total + per-sentiment counts in
    ONE MongoDB round-trip instead of four separate count_documents calls.
    """
    sub_id = sub["subreddit_name"]
    name = sub["name"]

    # Single $facet aggregation replaces 4 separate count_documents calls
    facet_pipeline = [
        {"$match": {"platform": "reddit", "parent_id": sub_id}},
        {"$facet": {
            "total":    [{"$count": "n"}],
            "positive": [{"$match": {"sentiment_label": "positive"}}, {"$count": "n"}],
            "negative": [{"$match": {"sentiment_label": "negative"}}, {"$count": "n"}],
            "neutral":  [{"$match": {"sentiment_label": "neutral"}},  {"$count": "n"}],
            "sample":   [{"$sort": {"ingested_at": -1}}, {"$limit": 40},
                         {"$project": {"_id": 0, "body": 1}}],
        }},
    ]

    payload_task = payloads_coll.find_one(
        {"platform": "reddit", "platform_id": sub_id},
        {"_id": 0, "stats": 1},
    )
    facet_task = comments_coll.aggregate(facet_pipeline).to_list(length=1)

    results = await asyncio.gather(payload_task, facet_task, return_exceptions=True)

    payload   = results[0] if not isinstance(results[0], Exception) else None
    facet_res = (results[1] or [{}])[0] if not isinstance(results[1], Exception) else {}

    total_comments = (facet_res.get("total") or [{}])[0].get("n", 0)
    pos_count      = (facet_res.get("positive") or [{}])[0].get("n", 0)
    neg_count      = (facet_res.get("negative") or [{}])[0].get("n", 0)
    neu_count      = (facet_res.get("neutral")  or [{}])[0].get("n", 0)
    sample_docs    = facet_res.get("sample") or []

    stats = (payload or {}).get("stats", {}) if payload else {}
    bodies = [d.get("body", "") for d in sample_docs if d.get("body")]
    keywords = _extract_keywords(bodies, top_n=8) if bodies else []
    total_labeled = pos_count + neg_count + neu_count

    lines = [
        f"\n  r/{name} (internal ID: {sub_id})",
        f"    Members: {_fmt(stats.get('members', stats.get('subscribers')) or sub.get('members'))}",
        f"    Tracked Comments in DB: {_fmt(total_comments)}",
    ]

    if total_labeled > 0:
        dominant = max(
            [("positive", pos_count), ("neutral", neu_count), ("negative", neg_count)],
            key=lambda x: x[1]
        )[0]
        lines.append(
            f"    Sentiment ({total_labeled} analyzed): "
            f"✅ {pos_count} positive | ⚪ {neu_count} neutral | ❌ {neg_count} negative"
        )
        lines.append(f"    Dominant Sentiment: {dominant}")
    elif bodies and is_active:
        try:
            svc = _get_sentiment_svc()
            model_results = svc.analyze_batch(bodies[:20])
            agg = svc.aggregate_sentiment(model_results)
            p_pct = round(agg["positive"] * 100)
            u_pct = round(agg["neutral"] * 100)
            n_pct = round(agg["negative"] * 100)
            lines.append(
                f"    Sentiment (analyzed {len(model_results)} recent comments): "
                f"✅ {p_pct}% positive | ⚪ {u_pct}% neutral | ❌ {n_pct}% negative"
            )
            lines.append(f"    Dominant Sentiment: {agg['dominant_label']}")
        except Exception:
            lines.append(f"    Sentiment: {total_comments} comments tracked (sentiment classification pending)")
    elif total_comments > 0:
        lines.append(f"    Sentiment: {total_comments} comments tracked (classification queued)")
    else:
        lines.append("    Sentiment: No comments ingested yet")

    if keywords:
        lines.append(f"    Top Trending Keywords: {', '.join(keywords)}")

    return "\n".join(lines)


async def _fetch_reddit_context(active_subreddit: Optional[str] = None) -> str:
    """Pull real Reddit metrics from PostgreSQL + MongoDB with parallelized I/O and caching."""
    clean_active = active_subreddit.lower().replace("r/", "").strip() if active_subreddit else None
    cache_key = f"reddit:{clean_active or ''}"
    cached = _get_cached_context(cache_key)
    if cached is not None:
        return cached

    try:
        payloads_coll = get_video_payloads_collection()
        comments_coll = get_comments_collection()

        from sqlalchemy import select as sa_select
        subreddits_data = []

        async with AsyncSessionLocal() as session:
            stmt = sa_select(PlatformAccount).where(
                PlatformAccount.platform == Platform.REDDIT
            )
            result = await session.execute(stmt)
            accounts = result.scalars().all()
            for acc in accounts:
                subreddits_data.append({
                    "subreddit_name": acc.platform_id,
                    "name": acc.display_name or acc.platform_id,
                    "members": acc.subscriber_count,
                })

        if not subreddits_data:
            res = "No subreddits are currently being tracked in the database."
            _set_cached_context(cache_key, res)
            return res

        # If user is currently viewing a specific subreddit, prioritize it first
        if clean_active:
            subreddits_data.sort(
                key=lambda x: (
                    0 if x["subreddit_name"].lower() == clean_active
                    or clean_active in x["name"].lower()
                    else 1
                )
            )

        header_lines = [f"TRACKED SUBREDDITS ({len(subreddits_data)} total):"]
        if clean_active:
            header_lines.append(f"  [User is currently viewing: r/{clean_active}]")

        tasks = [
            _fetch_single_subreddit_summary(
                sub,
                payloads_coll,
                comments_coll,
                is_active=(idx == 0 and bool(clean_active)),
            )
            for idx, sub in enumerate(subreddits_data[:6])
        ]
        subreddit_summaries = await asyncio.gather(*tasks)
        res = "\n".join(header_lines) + "\n" + "\n".join(subreddit_summaries)
        _set_cached_context(cache_key, res)
        return res

    except Exception as exc:
        return f"(Could not fetch Reddit data: {exc})"


async def _fetch_cross_platform_context(active_video_id: Optional[str] = None) -> str:
    """Pull real Cross-Platform propagation metrics and shared video intelligence with parallelized fetch."""
    clean_vid_id = active_video_id.strip() if active_video_id else None
    cache_key = f"cross-platform:{clean_vid_id or ''}"
    cached = _get_cached_context(cache_key)
    if cached is not None:
        return cached

    try:
        from app.api.v1.routers.cross_platform import get_shared_videos

        shared_task = get_shared_videos(
            subreddit_name=None,
            video_url_or_id=clean_vid_id,
            limit=200,
        )
        yt_task = _fetch_youtube_context()
        rd_task = _fetch_reddit_context()

        active_video_task = None
        if clean_vid_id:
            from app.api.v1.routers.cross_platform import get_video_engagement
            active_video_task = get_video_engagement(
                video_url_or_id=clean_vid_id,
                comment_scan_limit=1000,
            )

        tasks = [shared_task, yt_task, rd_task]
        if active_video_task:
            tasks.append(active_video_task)

        results = await asyncio.gather(*tasks, return_exceptions=True)
        shared = results[0] if not isinstance(results[0], Exception) else []
        yt_summary = results[1] if not isinstance(results[1], Exception) else ""
        rd_summary = results[2] if not isinstance(results[2], Exception) else ""
        video_eng = results[3] if len(results) > 3 and not isinstance(results[3], Exception) else None

        lines = []

        # ── 1. If an active video is being analyzed, prioritize its sentiment & engagement at the top ──
        if video_eng:
            lines.append(f"=== CURRENTLY ANALYZED VIDEO (ACTIVE IN DASHBOARD): {video_eng.youtube_video_id} ===")
            lines.append(f"Title: \"{video_eng.youtube_title or video_eng.youtube_video_id}\" (Channel: {video_eng.youtube_channel_title or 'Unknown'})")
            lines.append(f"YouTube Performance: {_fmt(video_eng.youtube_views)} views | {_fmt(video_eng.youtube_likes)} likes | {_fmt(video_eng.youtube_comment_count)} comments")

            if video_eng.youtube_sentiment or video_eng.reddit_sentiment:
                yt_s = video_eng.youtube_sentiment
                rd_s = video_eng.reddit_sentiment
                lines.append("\nAUDIENCE SENTIMENT COMPARISON (YouTube vs Reddit):")
                if yt_s:
                    lines.append(
                        f"  • YouTube Audience Sentiment: {round(yt_s.positive*100)}% Positive | "
                        f"{round(yt_s.neutral*100)}% Neutral | {round(yt_s.negative*100)}% Negative "
                        f"({_fmt(yt_s.sample_size)} comments analyzed, Dominant: {yt_s.dominant_label})"
                    )
                if rd_s:
                    subs_info = f" across {video_eng.subreddits_count} subreddits" if video_eng.subreddits_count else ""
                    lines.append(
                        f"  • Reddit Community Sentiment: {round(rd_s.positive*100)}% Positive | "
                        f"{round(rd_s.neutral*100)}% Neutral | {round(rd_s.negative*100)}% Negative "
                        f"({_fmt(rd_s.sample_size)} comments analyzed{subs_info}, Dominant: {rd_s.dominant_label})"
                    )
                if video_eng.sentiment_disparity_note:
                    lines.append(f"  • Audience Response Contrast / Sentiment Disparity: {video_eng.sentiment_disparity_note}")

            if video_eng.subreddits_list:
                lines.append(f"Discussed in Subreddits: {', '.join(f'r/{s}' for s in video_eng.subreddits_list)}")
            lines.append(
                f"Reddit Discussion Stats: {video_eng.reddit_posts_count} posts/threads, "
                f"{_fmt(video_eng.reddit_total_upvotes)} total upvotes, {_fmt(video_eng.reddit_total_comments)} comments"
            )
            if video_eng.propagation_speed:
                lines.append(f"Propagation Speed: {video_eng.propagation_speed}")
            if video_eng.topics:
                lines.append(f"Discussion Topics & Keywords: {', '.join(video_eng.topics[:6])}")
            lines.append("=== END OF CURRENTLY ANALYZED VIDEO ===\n")

        lines.append(f"CROSS-PLATFORM CONTENT INTELLIGENCE ({len(shared)} shared YouTube videos tracked across Reddit):")
        if clean_vid_id and not video_eng:
            lines.append(f"  [User is currently inspecting video: {clean_vid_id}]")

        for v in shared[:6]:
            title = v.youtube_title or v.youtube_video_id
            subs = ", ".join(f"r/{s}" for s in v.reddit_subreddits) if v.reddit_subreddits else "None"
            lines.append(f"\n  • Video: \"{title}\" (ID: {v.youtube_video_id})")
            lines.append(f"    Discussed in: {subs}")
            lines.append(f"    Reddit Discussions: {v.total_reddit_shares} shares/threads, {v.reddit_total_comments} comments, {v.reddit_total_upvotes} upvotes")
            if v.propagation_speed:
                lines.append(f"    Propagation Speed: {v.propagation_speed}")
            if v.youtube_sentiment and v.reddit_sentiment:
                yt_dom = v.youtube_sentiment.dominant_label
                rd_dom = v.reddit_sentiment.dominant_label
                lines.append(f"    YouTube Sentiment: {yt_dom} ({v.youtube_sentiment.positive*100:.0f}% pos, {v.youtube_sentiment.negative*100:.0f}% neg)")
                lines.append(f"    Reddit Sentiment: {rd_dom} ({v.reddit_sentiment.positive*100:.0f}% pos, {v.reddit_sentiment.negative*100:.0f}% neg)")
                if v.sentiment_disparity_note:
                    lines.append(f"    Sentiment Disparity: {v.sentiment_disparity_note}")
            if v.topics:
                lines.append(f"    Discussion Topics: {', '.join(v.topics[:5])}")

        lines.append("\n=== GENERAL TRACKED PLATFORM ACCOUNTS (BACKGROUND CONTEXT ONLY) ===")
        if yt_summary:
            lines.append(yt_summary)
        if rd_summary:
            lines.append("\n" + rd_summary)

        res = "\n".join(lines)
        _set_cached_context(cache_key, res)
        return res
    except Exception as exc:
        return f"(Could not fetch Cross-Platform data: {exc})"


# ─── Schemas ─────────────────────────────────────────────────────────────────

PlatformContext = Literal["youtube", "reddit", "cross-platform"]


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ChatbotRequest(BaseModel):
    question: str = Field(
        ...,
        min_length=3,
        max_length=1000,
        description="The user's natural-language question",
        examples=["Why is my comment sentiment trending negative?"],
    )
    context: PlatformContext = Field(
        ...,
        description="Active dashboard platform: 'youtube' | 'reddit' | 'cross-platform'",
        examples=["youtube"],
    )
    active_item: Optional[str] = Field(
        default=None,
        description="Active channel_id, subreddit_name, or video_id currently in view on the dashboard",
        examples=["UCBwmMxybNva6P_5VmxjzwqA"],
    )
    history: list[ChatMessage] = Field(
        default=[],
        description="Previous conversation turns (up to 6) for multi-turn support",
    )


class ChatbotResponse(BaseModel):
    answer: str = Field(..., description="AI-generated response text")
    context: str = Field(..., description="Platform context that was used")
    model: str = Field(..., description="LLM model that produced the response")


# ─── System prompt builder ────────────────────────────────────────────────────

def _build_system_prompt(context: str, live_data: str, question: str = "") -> str:
    """Build a focused system prompt grounded in live data and the user's exact question."""

    base_instructions = {
        "youtube": (
            "You are an elite YouTube Video Performance & Growth Consultant with deep mastery "
            "of the YouTube recommendation algorithm, viewer psychology, retention mechanics, "
            "CTR optimization, high-converting video hooks, and sentiment-driven content strategy."
        ),
        "reddit": (
            "You are an elite Reddit Community & Growth Strategist with deep knowledge "
            "of subreddit cultures, upvote dynamics, karma mechanics, comment sentiment management, "
            "trend discovery, and non-spammy community engagement tactics."
        ),
        "cross-platform": (
            "You are a master Cross-Platform Digital Strategist specializing in the synergy "
            "between YouTube and Reddit. You excel at audience retention, content propagation, "
            "bridging YouTube videos to Reddit discussions, analyzing sentiment disparities, "
            "and designing dual-platform content strategies that hook viewers and cultivate positive sentiment."
        ),
    }

    # Platform-specific playbooks — only consulted when the question is strategic/creative
    youtube_playbook = (
        "YOUTUBE GROWTH & PERFORMANCE PLAYBOOK (use ONLY when the question is strategy/advice oriented):\n"
        "• CTR & Packaging: Apply the '3-Second Glance Rule' for thumbnails; place high-impact keywords in the first 45 chars of titles.\n"
        "• Retention: Use the Proof-First cold open (0-5s); diagnose drop-offs by segment (0-30s = hook mismatch, mid = pacing fatigue, end cliff = early wrap telegraphing).\n"
        "• Comment Sentiment Engine: Pinned question strategy within 1 hour of upload; address negative feedback with pinned gracious clarifications."
    )

    reddit_playbook = (
        "REDDIT COMMUNITY & GROWTH PLAYBOOK (use ONLY when the question is strategy/advice oriented):\n"
        "• Anti-Self-Promotion: 90/10 Rule — deliver full value natively; never lead with links.\n"
        "• Upvote Velocity: Engage every commenter in the first 60-90 mins after posting.\n"
        "• Focus Group Mining: Mine skepticism and recurring pain points to script better YouTube content."
    )

    cross_platform_playbook = (
        "CROSS-PLATFORM SYNERGY PLAYBOOK (use ONLY when the question is strategy/advice oriented):\n"
        "• YouTube = visual storytelling & emotional hooks; Reddit = rigorous critique & focus-group feedback.\n"
        "• Transform video insights into native Reddit threads; mine subreddit controversies for YouTube video ideas.\n"
        "• Sentiment Disparity: YouTube viewers respond to personality & visuals; Reddit scrutinizes commercial intent & technical claims."
    )

    playbooks = {
        "youtube": youtube_playbook,
        "reddit": reddit_playbook,
        "cross-platform": cross_platform_playbook,
    }

    # Build an intent-aware answering directive based on the user's question
    question_anchor = ""
    if question:
        question_anchor = (
            f"\n\n=== USER'S EXACT QUESTION (answer THIS — nothing else unless it helps answer this) ===\n"
            f"\"{question}\"\n"
            "=== END OF QUESTION ===\n"
        )

    rules = (
        "STRICT RESPONSE RULES — FOLLOW IN ORDER:\n\n"
        "STEP 1 — READ THE QUESTION CAREFULLY.\n"
        "   Identify what the user is literally asking: a data lookup, a trend explanation, "
        "a strategic recommendation, a comparison, or a general how-to. "
        "Do NOT add information the user did not ask for.\n\n"
        "STEP 2 — DETERMINE ANSWER TYPE:\n"
        "   A) DATA QUESTION (e.g. 'what is my sentiment?', 'how many views?', 'which subreddit?'):\n"
        "      → Answer ONLY using numbers from the LIVE DATA block. Quote exact figures. "
        "Never hallucinate or estimate metrics. If data is missing, say so clearly.\n"
        "   B) EXPLANATION / ANALYSIS QUESTION (e.g. 'why is Reddit sentiment low?', 'what does this contrast mean?'):\n"
        "      → Lead with the live data figures, then explain the likely cause using platform psychology. "
        "Keep the explanation tightly linked to the actual numbers shown.\n"
        "   C) STRATEGY / ADVICE QUESTION (e.g. 'how do I improve CTR?', 'how do I grow on Reddit?'):\n"
        "      → Use the platform playbook. Reference the user's actual metrics where available "
        "to make advice specific and personalized, not generic.\n"
        "   D) CONVERSATIONAL / FOLLOW-UP QUESTION:\n"
        "      → Stay in context of the prior conversation turn. Answer concisely.\n\n"
        "STEP 3 — CONTEXT PRIORITY:\n"
        "   - If an 'CURRENTLY ANALYZED VIDEO' section exists in the live data, any question about "
        "'sentiment', 'audience', 'contrast', 'analysis', or 'performance' refers to THAT VIDEO's "
        "YouTube vs Reddit comparison — NOT to generic channel-level data.\n"
        "   - General tracked channels/subreddits at the bottom of the live data are background context only. "
        "Do NOT list them as the answer when the user is asking about a specific active item.\n"
        "   - If a specific channel or subreddit is the active item, answer about it specifically.\n\n"
        "STEP 4 — FORMAT:\n"
        "   - Match response length to question complexity. Simple question → concise answer (2-5 sentences or a short list). "
        "Complex multi-part question → structured sections with bold headers and bullet points.\n"
        "   - Never pad with unsolicited advice, unrelated metrics, or generic disclaimers.\n"
        "   - No raw asterisks. Use clean markdown: **bold**, bullet •, numbered steps.\n"
        "   - Maintain conversation continuity — refer to earlier turns when relevant.\n\n"
        f"{playbooks.get(context, cross_platform_playbook)}"
    )

    return (
        f"{base_instructions.get(context, base_instructions['cross-platform'])}\n\n"
        f"{rules}"
        f"{question_anchor}\n"
        f"=== LIVE DATA FROM DATABASE (fetched right now) ===\n"
        f"{live_data}\n"
        f"=== END OF LIVE DATA ===\n\n"
        "Answer the user's question directly and precisely using the data and rules above. "
        "Stay on topic. Do not volunteer information that was not asked for."
    )


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post(
    "/query",
    response_model=ChatbotResponse,
    summary="Query the context-aware AI analyst with real-time dashboard data",
    description=(
        "Submit a question along with the active dashboard platform context. "
        "The system fetches REAL metrics from MongoDB + PostgreSQL, injects them "
        "into the system prompt, then calls DeepSeek V4.1 Flash via River.ai so "
        "answers are based on your actual data — not hallucinated numbers."
    ),
)
async def chatbot_query(payload: ChatbotRequest) -> ChatbotResponse:
    """
    1. Fetch real-time metrics from the database for the given context and active item.
    2. Build a system prompt containing those metrics.
    3. Call DeepSeek V4.1 Flash via River.ai with the enriched prompt.
    4. Return the grounded, data-aware response.
    """
    # NOTE: do NOT call get_settings.cache_clear() here — that kills the LRU cache on
    # every request, forcing a full .env re-parse each call (unnecessary latency).
    settings = get_settings()

    if not settings.RIVER_API_KEY or settings.RIVER_API_KEY == "your_river_api_key_here":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Chatbot is not configured. Please paste your actual RIVER_API_KEY in your "
                ".env file and save the file (Cmd+S). Get an API key at https://river.ai"
            ),
        )

    # ── 1. Fetch live data based on context ──────────────────────────────────
    if payload.context == "youtube":
        live_data = await _fetch_youtube_context(payload.active_item)
    elif payload.context == "reddit":
        live_data = await _fetch_reddit_context(payload.active_item)
    else:  # cross-platform
        live_data = await _fetch_cross_platform_context(payload.active_item)

    # ── 2. Build grounded system prompt ──────────────────────────────────────
    system_prompt = _build_system_prompt(payload.context, live_data, question=payload.question)

    # ── 3. Call DeepSeek V4.1 Flash via River.ai using the shared client ─────
    client = _get_llm_client()

    model = settings.RIVER_MODEL

    # Build messages list: system + prior history (last 6 turns) + current question
    history_msgs = [
        {"role": m.role, "content": m.content}
        for m in payload.history[-6:]
    ]

    # Classify question length to tune max_tokens:
    # short/factual questions get a tight cap; longer analytical questions get more room.
    q_words = len(payload.question.split())
    if q_words <= 10:
        max_tok = 400    # concise factual answer
    elif q_words <= 25:
        max_tok = 700    # moderate explanation
    else:
        max_tok = 1200   # detailed strategic / multi-part answer

    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                *history_msgs,
                {"role": "user",   "content": payload.question},
            ],
            temperature=0.3,   # lower = more focused, less hallucination / tangents
            max_tokens=max_tok,
        )
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid RIVER_API_KEY. Please verify your key at https://river.ai",
        )
    except RateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="River.ai rate limit reached. Please wait a moment and try again.",
        )
    except APIConnectionError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not connect to River.ai API. Please try again later.",
        )
    except Exception as exc:
        import logging as _logging
        _logging.getLogger(__name__).error("Unexpected LLM error: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="An unexpected error occurred. Please try again.",
        )

    answer = completion.choices[0].message.content or "No response generated."

    return ChatbotResponse(
        answer=answer,
        context=payload.context,
        model=model,
    )


# ── Streaming endpoint ────────────────────────────────────────────────────────
# Returns tokens as they arrive (text/event-stream) — the frontend renders each
# chunk immediately, so the user sees words appearing right away instead of
# waiting for the full response.

@router.post(
    "/stream",
    summary="Streaming version of the AI analyst — tokens arrive in real time",
)
async def chatbot_stream(payload: ChatbotRequest) -> StreamingResponse:
    """
    Same as /query but streams the LLM response as server-sent events (SSE).
    Each event is:  data: <token text>\\n\\n
    A final event:  data: [DONE]\\n\\n  signals completion.
    """
    settings = get_settings()

    if not settings.RIVER_API_KEY or settings.RIVER_API_KEY == "your_river_api_key_here":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chatbot is not configured. Set RIVER_API_KEY in .env",
        )

    # ── 1. Fetch context (same as non-streaming endpoint) ─────────────────────
    if payload.context == "youtube":
        live_data = await _fetch_youtube_context(payload.active_item)
    elif payload.context == "reddit":
        live_data = await _fetch_reddit_context(payload.active_item)
    else:
        live_data = await _fetch_cross_platform_context(payload.active_item)

    system_prompt = _build_system_prompt(payload.context, live_data, question=payload.question)

    client = _get_llm_client()
    model  = settings.RIVER_MODEL

    history_msgs = [
        {"role": m.role, "content": m.content}
        for m in payload.history[-6:]
    ]

    q_words = len(payload.question.split())
    if q_words <= 10:
        max_tok = 400
    elif q_words <= 25:
        max_tok = 700
    else:
        max_tok = 1200

    async def event_generator():
        try:
            stream = await client.chat.completions.create(
                model=model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    *history_msgs,
                    {"role": "user",   "content": payload.question},
                ],
                temperature=0.3,
                max_tokens=max_tok,
                stream=True,
            )
            async for chunk in stream:
                token = chunk.choices[0].delta.content
                if token:
                    # Escape newlines so SSE framing is not broken
                    safe = token.replace("\n", "\\n")
                    yield f"data: {safe}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as exc:
            import logging as _logging
            _logging.getLogger(__name__).error("Stream error: %s", exc, exc_info=True)
            yield f"data: [ERROR] {exc}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # disable nginx buffering in production
        },
    )
