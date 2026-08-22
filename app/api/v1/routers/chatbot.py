"""
Chatbot Router  —  /api/v1/chatbot
====================================

Endpoints
---------
POST /query   — Accept a user question + active dashboard context, pull
                REAL-TIME metrics from MongoDB + PostgreSQL, inject them
                into a dynamic system prompt, and return an AI answer from
                Groq Cloud (LLaMA 3.3 70B).

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

import re
import string
from collections import Counter
from typing import Literal

from fastapi import APIRouter, HTTPException, status
from openai import AsyncOpenAI, APIConnectionError, AuthenticationError, RateLimitError
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.db.mongodb import get_comments_collection, get_video_payloads_collection, get_mongo_db
from app.db.postgres import Platform, PlatformAccount, AsyncSessionLocal

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

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


# ─── Real-time context fetchers ───────────────────────────────────────────────

async def _fetch_youtube_context() -> str:
    """Pull real YouTube metrics from PostgreSQL + MongoDB."""
    from sqlalchemy import select, text

    try:
        payloads_coll = get_video_payloads_collection()
        comments_coll = get_comments_collection()

        # --- PostgreSQL: get all tracked YouTube channels ---
        channels_data = []
        from sqlalchemy import select as sa_select  # noqa: PLC0415

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
            return "No YouTube channels are currently being tracked in the database."

        lines = [f"TRACKED YOUTUBE CHANNELS ({len(channels_data)} total):"]

        for ch in channels_data[:5]:  # limit to top 5 to keep prompt size manageable
            chan_id = ch["channel_id"]
            name    = ch["name"]

            # MongoDB: latest snapshot stats for this channel
            payload = await payloads_coll.find_one(
                {"platform": "youtube", "platform_id": chan_id},
                {"_id": 0, "stats": 1},
            )
            stats = (payload or {}).get("stats", {}) if payload else {}

            # MongoDB: recent comment count + sentiment
            total_comments = await comments_coll.count_documents(
                {"platform": "youtube", "parent_id": chan_id}
            )

            # Fetch a sample of recent comments for keyword extraction
            sample_cursor = (
                comments_coll
                .find({"platform": "youtube", "parent_id": chan_id}, {"_id": 0, "body": 1})
                .sort("ingested_at", -1)
                .limit(50)
            )
            sample_docs = await sample_cursor.to_list(length=50)
            bodies = [d.get("body", "") for d in sample_docs]
            keywords = _extract_keywords(bodies, top_n=5) if bodies else []

            # Sentiment counts — YouTube comments use sentiment_label field
            pos_count = await comments_coll.count_documents(
                {"platform": "youtube", "parent_id": chan_id, "sentiment_label": "positive"}
            )
            neg_count = await comments_coll.count_documents(
                {"platform": "youtube", "parent_id": chan_id, "sentiment_label": "negative"}
            )
            neu_count = await comments_coll.count_documents(
                {"platform": "youtube", "parent_id": chan_id, "sentiment_label": "neutral"}
            )
            analyzed = pos_count + neg_count + neu_count
            # Fall back to processed count if labels not yet assigned
            if analyzed == 0:
                analyzed = await comments_coll.count_documents(
                    {"platform": "youtube", "parent_id": chan_id, "sentiment_processed": True}
                )

            lines.append(f"\n  Channel: {name} (ID: {chan_id})")
            lines.append(f"    Subscribers: {_fmt(stats.get('subscribers') or ch.get('subscribers'))}")
            lines.append(f"    Total Views: {_fmt(stats.get('views'))}")
            lines.append(f"    Total Likes: {_fmt(stats.get('likes'))}")
            lines.append(f"    Total Videos: {_fmt(stats.get('videos'))}")
            lines.append(f"    Tracked Comments: {_fmt(total_comments)}")
            if analyzed > 0:
                lines.append(
                    f"    Sentiment (of {_fmt(analyzed)} analyzed): "
                    f"✅ {pos_count} positive | ⚪ {neu_count} neutral | ❌ {neg_count} negative"
                )
                dominant = max(
                    [("positive", pos_count), ("neutral", neu_count), ("negative", neg_count)],
                    key=lambda x: x[1]
                )[0]
                lines.append(f"    Dominant Sentiment: {dominant}")
            if keywords:
                lines.append(f"    Top Keywords in Comments: {', '.join(keywords)}")

        return "\n".join(lines)

    except Exception as exc:
        return f"(Could not fetch YouTube data: {exc})"


async def _fetch_reddit_context() -> str:
    """Pull real Reddit metrics from PostgreSQL + MongoDB."""
    try:
        payloads_coll = get_video_payloads_collection()
        comments_coll = get_comments_collection()

        # PostgreSQL: all tracked subreddits
        from sqlalchemy import select as sa_select  # noqa: PLC0415
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
            return "No subreddits are currently being tracked in the database."

        lines = [f"TRACKED SUBREDDITS ({len(subreddits_data)} total):"]

        for sub in subreddits_data[:5]:
            sub_id = sub["subreddit_name"]
            name   = sub["name"]

            # MongoDB: latest payload for subreddit-level stats
            payload = await payloads_coll.find_one(
                {"platform": "reddit", "platform_id": sub_id},
                {"_id": 0, "stats": 1},
            )
            stats = (payload or {}).get("stats", {}) if payload else {}

            # Comment stats
            total_comments = await comments_coll.count_documents(
                {"platform": "reddit", "parent_id": sub_id}
            )

            # Keyword extraction from recent comments
            sample_cursor = (
                comments_coll
                .find({"platform": "reddit", "parent_id": sub_id}, {"_id": 0, "body": 1})
                .sort("ingested_at", -1)
                .limit(100)
            )
            sample_docs = await sample_cursor.to_list(length=100)
            bodies = [d.get("body", "") for d in sample_docs]
            keywords = _extract_keywords(bodies, top_n=8) if bodies else []

            # Sentiment — Reddit comments use sentiment_label OR sentiment_processed flag
            pos_count = await comments_coll.count_documents(
                {"platform": "reddit", "parent_id": sub_id, "sentiment_label": "positive"}
            )
            neg_count = await comments_coll.count_documents(
                {"platform": "reddit", "parent_id": sub_id, "sentiment_label": "negative"}
            )
            neu_count = await comments_coll.count_documents(
                {"platform": "reddit", "parent_id": sub_id, "sentiment_label": "neutral"}
            )
            analyzed = pos_count + neg_count + neu_count
            if analyzed == 0:
                # Fall back: use count of processed docs if labels not yet populated
                analyzed = await comments_coll.count_documents(
                    {"platform": "reddit", "parent_id": sub_id, "sentiment_processed": True}
                )

            lines.append(f"\n  r/{name} (internal ID: {sub_id})")
            lines.append(f"    Members: {_fmt(stats.get('members', stats.get('subscribers')) or sub.get('members'))}")
            lines.append(f"    Total Posts Tracked: {_fmt(stats.get('posts', stats.get('total_posts')))}")
            lines.append(f"    Tracked Comments in DB: {_fmt(total_comments)}")
            if analyzed > 0:
                lines.append(
                    f"    Sentiment (of {_fmt(analyzed)} analyzed): "
                    f"✅ {pos_count} positive | ⚪ {neu_count} neutral | ❌ {neg_count} negative"
                )
                dominant = max(
                    [("positive", pos_count), ("neutral", neu_count), ("negative", neg_count)],
                    key=lambda x: x[1]
                )[0]
                lines.append(f"    Dominant Sentiment: {dominant}")
            if keywords:
                lines.append(f"    Top Trending Keywords: {', '.join(keywords)}")

        return "\n".join(lines)

    except Exception as exc:
        return f"(Could not fetch Reddit data: {exc})"


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
    """Build a system prompt that includes the live data snapshot."""

    base_instructions = {
        "youtube": (
            "You are an expert YouTube Video Performance Consultant with deep knowledge "
            "of the YouTube algorithm, audience retention, CTR optimisation, and "
            "sentiment-driven content strategy. "
        ),
        "reddit": (
            "You are an expert Reddit Community Management Specialist with deep "
            "knowledge of subreddit growth strategies, upvote mechanics, community "
            "engagement tactics, keyword trend analysis, and sentiment management. "
        ),
        "cross-platform": (
            "You are an expert Cross-Platform Content Strategist specialising in "
            "bridging YouTube and Reddit audiences. You synthesise insights from both "
            "platforms to create integrated channel playbooks. "
        ),
    }

    rules = (
        "IMPORTANT RULES:\n"
        "- You have been given REAL, LIVE data from the user's actual database below.\n"
        "- ALWAYS use this real data to answer questions — never invent or fabricate numbers.\n"
        "- If a specific metric shows 'N/A', it means it hasn't been ingested yet; say so clearly.\n"
        "- For Reddit: sentiment may show only a processed count (not a pos/neg breakdown) — if so, say 'sentiment analysis has run on X comments but label breakdown is pending'.\n"
        "- Give concise, data-informed, actionable advice based strictly on the numbers provided.\n"
        "- Do NOT give generic social media advice unrelated to the live data shown.\n"
        "- Keep answers under 400 words unless a detailed breakdown is explicitly requested.\n"
        "- If the user asks about something not in the data, clearly state what data IS available and suggest running an ingestion.\n"
        "- You are having a conversation — remember earlier messages in this chat.\n"
    )

    return (
        f"{base_instructions.get(context, base_instructions['youtube'])}\n\n"
        f"{rules}\n\n"
        f"=== LIVE DATA FROM DATABASE (fetched right now) ===\n"
        f"{live_data}\n"
        f"=== END OF LIVE DATA ===\n\n"
        f"Use the above real data to answer the user's question."
    )


# ─── Endpoint ────────────────────────────────────────────────────────────────

@router.post(
    "/query",
    response_model=ChatbotResponse,
    summary="Query the context-aware AI analyst with real-time dashboard data",
    description=(
        "Submit a question along with the active dashboard platform context. "
        "The system fetches REAL metrics from MongoDB + PostgreSQL, injects them "
        "into the system prompt, then calls Groq LLM so answers are based on your "
        "actual data — not hallucinated numbers."
    ),
)
async def chatbot_query(payload: ChatbotRequest) -> ChatbotResponse:
    """
    1. Fetch real-time metrics from the database for the given context.
    2. Build a system prompt containing those metrics.
    3. Call the Groq API with the enriched prompt.
    4. Return the grounded, data-aware response.
    """
    settings = get_settings()

    if not settings.GROQ_API_KEY:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "Chatbot is not configured. Please set GROQ_API_KEY in your "
                ".env file. Get a free API key at https://console.groq.com"
            ),
        )

    # ── 1. Fetch live data based on context ──────────────────────────────────
    if payload.context == "youtube":
        live_data = await _fetch_youtube_context()
    elif payload.context == "reddit":
        live_data = await _fetch_reddit_context()
    else:  # cross-platform
        yt_data  = await _fetch_youtube_context()
        rd_data  = await _fetch_reddit_context()
        live_data = f"--- YouTube ---\n{yt_data}\n\n--- Reddit ---\n{rd_data}"

    # ── 2. Build grounded system prompt ──────────────────────────────────────
    system_prompt = _build_system_prompt(payload.context, live_data)

    # ── 3. Call Groq Cloud LLM ────────────────────────────────────────────────
    client = AsyncOpenAI(
        api_key=settings.GROQ_API_KEY,
        base_url="https://api.groq.com/openai/v1",
    )

    model = settings.GROQ_MODEL

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
            temperature=0.4,
            max_tokens=800,  # increased from 512 to avoid truncated answers
        )
    except AuthenticationError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid GROQ_API_KEY. Please verify your key at https://console.groq.com",
        )
    except RateLimitError:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Groq API rate limit reached. Please wait a moment and try again.",
        )
    except APIConnectionError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Could not connect to the Groq API. Please try again later.",
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
