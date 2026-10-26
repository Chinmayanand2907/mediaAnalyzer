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
from openai import AsyncOpenAI, APIConnectionError, AuthenticationError, RateLimitError
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.db.mongodb import get_comments_collection, get_video_payloads_collection, get_mongo_db
from app.db.postgres import Platform, PlatformAccount, AsyncSessionLocal

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

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
_CACHE_TTL_SECONDS = 60.0


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
    """Fetch metrics and sentiment for a single YouTube channel concurrently."""
    chan_id = ch["channel_id"]
    name = ch["name"]

    payload_task = payloads_coll.find_one(
        {"platform": "youtube", "platform_id": chan_id},
        {"_id": 0, "stats": 1},
    )
    total_comments_task = comments_coll.count_documents(
        {"platform": "youtube", "parent_id": chan_id}
    )
    pos_task = comments_coll.count_documents(
        {"platform": "youtube", "parent_id": chan_id, "sentiment_label": "positive"}
    )
    neg_task = comments_coll.count_documents(
        {"platform": "youtube", "parent_id": chan_id, "sentiment_label": "negative"}
    )
    neu_task = comments_coll.count_documents(
        {"platform": "youtube", "parent_id": chan_id, "sentiment_label": "neutral"}
    )
    sample_cursor = (
        comments_coll
        .find({"platform": "youtube", "parent_id": chan_id}, {"_id": 0, "body": 1})
        .sort("ingested_at", -1)
        .limit(50)
    )
    sample_task = sample_cursor.to_list(length=50)

    # Run all 6 channel queries in parallel
    results = await asyncio.gather(
        payload_task,
        total_comments_task,
        pos_task,
        neg_task,
        neu_task,
        sample_task,
        return_exceptions=True,
    )

    payload = results[0] if not isinstance(results[0], Exception) else None
    total_comments = results[1] if not isinstance(results[1], Exception) else 0
    pos_count = results[2] if not isinstance(results[2], Exception) else 0
    neg_count = results[3] if not isinstance(results[3], Exception) else 0
    neu_count = results[4] if not isinstance(results[4], Exception) else 0
    sample_docs = results[5] if not isinstance(results[5], Exception) else []

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
        # Dynamic fallback inference ONLY on active channel to avoid slow background CPU spikes
        try:
            svc = _get_sentiment_svc()
            model_results = svc.analyze_batch(bodies[:30])
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
    """Fetch metrics and sentiment for a single subreddit concurrently."""
    sub_id = sub["subreddit_name"]
    name = sub["name"]

    payload_task = payloads_coll.find_one(
        {"platform": "reddit", "platform_id": sub_id},
        {"_id": 0, "stats": 1},
    )
    total_comments_task = comments_coll.count_documents(
        {"platform": "reddit", "parent_id": sub_id}
    )
    pos_task = comments_coll.count_documents(
        {"platform": "reddit", "parent_id": sub_id, "sentiment_label": "positive"}
    )
    neg_task = comments_coll.count_documents(
        {"platform": "reddit", "parent_id": sub_id, "sentiment_label": "negative"}
    )
    neu_task = comments_coll.count_documents(
        {"platform": "reddit", "parent_id": sub_id, "sentiment_label": "neutral"}
    )
    sample_cursor = (
        comments_coll
        .find({"platform": "reddit", "parent_id": sub_id}, {"_id": 0, "body": 1})
        .sort("ingested_at", -1)
        .limit(100)
    )
    sample_task = sample_cursor.to_list(length=100)

    # Run all 6 subreddit queries in parallel
    results = await asyncio.gather(
        payload_task,
        total_comments_task,
        pos_task,
        neg_task,
        neu_task,
        sample_task,
        return_exceptions=True,
    )

    payload = results[0] if not isinstance(results[0], Exception) else None
    total_comments = results[1] if not isinstance(results[1], Exception) else 0
    pos_count = results[2] if not isinstance(results[2], Exception) else 0
    neg_count = results[3] if not isinstance(results[3], Exception) else 0
    neu_count = results[4] if not isinstance(results[4], Exception) else 0
    sample_docs = results[5] if not isinstance(results[5], Exception) else []

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
        # Dynamic fallback inference ONLY on active subreddit to prevent CPU overhead
        try:
            svc = _get_sentiment_svc()
            model_results = svc.analyze_batch(bodies[:30])
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
    cache_key = f"cross-platform:{active_video_id or ''}"
    cached = _get_cached_context(cache_key)
    if cached is not None:
        return cached

    try:
        from app.api.v1.routers.cross_platform import get_shared_videos

        shared_task = get_shared_videos(
            subreddit_name=None,
            video_url_or_id=active_video_id,
            limit=200,
        )
        yt_task = _fetch_youtube_context()
        rd_task = _fetch_reddit_context()

        # Run shared videos, YouTube context, and Reddit context concurrently
        shared, yt_summary, rd_summary = await asyncio.gather(
            shared_task, yt_task, rd_task
        )

        lines = [f"CROSS-PLATFORM CONTENT INTELLIGENCE ({len(shared)} shared YouTube videos tracked across Reddit):"]
        if active_video_id:
            lines.append(f"  [User is currently inspecting video: {active_video_id}]")

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

        lines.append("\n=== TRACKED PLATFORM ACCOUNTS SUMMARY ===")
        lines.append(yt_summary)
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

def _build_system_prompt(context: str, live_data: str) -> str:
    """Build a comprehensive system prompt that includes live data snapshot and strategic guidance."""

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

    # Platform-specific playbooks tailored to the active dashboard
    youtube_playbook = (
        "YOUTUBE GROWTH & PERFORMANCE PLAYBOOK:\n"
        "• Click-Through Rate (CTR) & Packaging:\n"
        "  - Thumbnail composition: Apply the '3-Second Glance Rule' (1 primary emotional focal point, high contrast, max 3 words of bold text that complement, never repeat, the title).\n"
        "  - Title engineering: Place high-impact keywords in the first 45 characters (mobile truncation boundary). Use cognitive tension or curiosity gaps without descending into cheap clickbait.\n"
        "• Retention Curves & The 0–15s Hook Window:\n"
        "  - Cold Open / Proof-First framework: Immediately demonstrate the climax, result, or high-stakes premise within 0-5s. Eliminate intro logos, theme music, or 'welcome back' pleasantries.\n"
        "  - Diagnosing Drop-offs: 0-30s drop indicates hook/title mismatch; mid-video downward slope signals pacing fatigue (inject pattern interrupts, camera zooms, or sound hits every 4-6 seconds); sharp cliff before the end means telegraphing the wrap-up too early (seamlessly transition straight to the end screen card).\n"
        "• Comment Section & Sentiment Engine:\n"
        "  - Pinned question strategy: Ask an opinion-seeking or debate-sparking question within 1 hour of upload to stimulate comment velocity for the algorithm.\n"
        "  - Sentiment reversal: Address negative feedback or confusion openly by pinning a gracious clarification; convert recurring community pain points into your next video topic."
    )

    reddit_playbook = (
        "REDDIT COMMUNITY & GROWTH PLAYBOOK:\n"
        "• Subreddit Culture & Anti-Self-Promotion Framing:\n"
        "  - The 90/10 Rule: Deliver 100% of the core insight/value natively inside the Reddit text post. Use structured Markdown: bold headers, TL;DR, and concise bullet points.\n"
        "  - Link etiquette: Never post raw video links or link-posts. Place external links (YouTube video, GitHub repo, live demo) only at the very bottom as an optional reference (*'For the full step-by-step video breakdown: [Link]'*).\n"
        "• Upvote Velocity & The First Hour Rule:\n"
        "  - Reddit's hot ranking algorithm heavily weighs early upvote velocity. Stay active in the thread for the first 60–90 minutes, answering every commenter with technical depth and humility.\n"
        "  - Strict rule compliance: Adhere to subreddit-specific submission guidelines, flairs, and self-promotion blackout days.\n"
        "• Sentiment & Focus Group Mining:\n"
        "  - Treat Reddit as an unfiltered, brutally honest focus group. Mine community feedback, skepticism, and recurring questions to identify unmet audience needs and script better YouTube content.\n"
        "  - Diffusing skepticism: Never respond defensively. Validate constructive criticism, explain technical trade-offs openly, and thank users for keeping you accountable."
    )

    cross_platform_playbook = (
        "CROSS-PLATFORM SYNERGY PLAYBOOK:\n"
        "• Dual-Platform Harmony:\n"
        "  - YouTube drives visual storytelling, emotional connection, and high-energy demos; Reddit provides rigorous technical critique, community discourse, and focus group testing.\n"
        "• Propagation & Bridging Strategy:\n"
        "  - Transform YouTube video insights into native, high-value Reddit discussion threads.\n"
        "  - Mine trending topics and controversies from subreddits to formulate high-demand YouTube video concepts.\n"
        "• Sentiment Disparity Diagnostics:\n"
        "  - Analyze why sentiment may diverge (e.g. YouTube viewers love personality and visuals, while Reddit users scrutinize commercial intent or technical claims). Bridge this gap with radical transparency."
    )

    playbooks = {
        "youtube": youtube_playbook,
        "reddit": reddit_playbook,
        "cross-platform": cross_platform_playbook,
    }

    rules = (
        "CORE OPERATING PRINCIPLES:\n"
        "1. DUAL CAPABILITY (Data Analysis + Strategic Advisory):\n"
        "   - FOR DATA-SPECIFIC QUESTIONS: You have REAL, LIVE data from the user's database below. "
        "Always ground specific numbers (views, likes, comments, subreddits, sentiment percentages, subscriber counts) "
        "strictly in this live data. Never invent or hallucinate metrics.\n"
        "   - FOR GENERAL STRATEGIC & CREATIVE QUESTIONS: (e.g. 'what type of videos get audiences hooked?', "
        "'how to gain positive sentiment?', 'how to optimize CTR?', 'how to post on Reddit without being marked as spam?'): "
        "Provide thorough, high-impact, expert strategic guidance using your playbook above! Break down concrete structures, "
        "step-by-step frameworks, psychological triggers, and actionable steps.\n\n"
        f"{playbooks.get(context, cross_platform_playbook)}\n\n"
        "2. PRECISION & CONTEXT:\n"
        "   - If the user is currently viewing a specific channel, subreddit, or video (indicated in the data below), "
        "tailor insights directly to that active subject.\n"
        "   - If a specific metric shows 'N/A' or 'not yet ingested', note it clearly and advise on next steps.\n"
        "   - Keep answers structured with bold highlights, clean bullet points, or numbered steps. "
        "Do not output raw asterisks without purpose; use clean, elegant markdown formatting.\n"
        "   - Maintain conversation continuity across turns."
    )

    return (
        f"{base_instructions.get(context, base_instructions['cross-platform'])}\n\n"
        f"{rules}\n\n"
        f"=== LIVE DATA FROM DATABASE (fetched right now) ===\n"
        f"{live_data}\n"
        f"=== END OF LIVE DATA ===\n\n"
        f"Use both your expert domain knowledge and the real live data above to answer the user's question."
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
    get_settings.cache_clear()
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
    system_prompt = _build_system_prompt(payload.context, live_data)

    # ── 3. Call DeepSeek V4.1 Flash via River.ai ─────────────────────────────
    client = AsyncOpenAI(
        api_key=settings.RIVER_API_KEY,
        base_url="https://api.river.ai/v1",
    )

    model = settings.RIVER_MODEL

    # Build messages list: system + prior history (last 6 turns) + current question
    history_msgs = [
        {"role": m.role, "content": m.content}
        for m in payload.history[-6:]
    ]

    try:
        completion = await client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                *history_msgs,
                {"role": "user",   "content": payload.question},
            ],
            temperature=0.5,
            max_tokens=2000,  # comprehensive strategic playbooks
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
