"""
Reddit Router  —  /api/v1/reddit
===================================

Endpoints
---------
GET  /subreddits                              — list all tracked subreddits (Postgres)
GET  /subreddits/{subreddit_name}             — subreddit metadata + member count
GET  /subreddits/{subreddit_name}/sentiment   — comment sentiment distribution (pie chart data)
GET  /subreddits/{subreddit_name}/comments    — paginated comments with per-comment sentiment
GET  /subreddits/{subreddit_name}/keywords    — top keywords extracted from comment corpus
POST /subreddits/{subreddit_name}/ingest      — enqueue async Celery ingestion task
"""

from __future__ import annotations

import re
import string
from datetime import datetime, timezone
from collections import Counter
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    CommentSentimentItem,
    KeywordItem,
    RedditSubredditListItem,
    RedditSubredditMetrics,
    SentimentDistribution,
    TaskEnqueuedResponse,
)
from app.db.mongodb import get_comments_collection, get_video_payloads_collection
from app.db.postgres import Platform, PlatformAccount, get_db_session
from app.services.analytics.sentiment_service import SentimentService
from app.core.celery_app import celery_app

router = APIRouter(prefix="/reddit", tags=["Reddit"])

_sentiment_svc = SentimentService()

# Common English stopwords for keyword extraction (no external library needed).
_STOPWORDS = frozenset(
    "the a an and or but in on at to for of with by from is are was were be been "
    "being have has had do does did will would could should may might shall can "
    "not no nor so yet both either neither one two three i me my we our you your "
    "he she it its they them their this that these those what which who whom how "
    "when where why than then also just more very much many some any all each "
    "about after before between into through during again further once "
    # URL scheme / structural fragments
    "http https www ftp "
    # Generic TLDs and domain noise
    "com net org edu gov io co uk de fr au ca "
    # Platform-specific path fragments that appear after punctuation stripping
    "youtube watch reddit youtu imgur twitter facebook instagram tiktok "
    "amp utm ref source medium campaign "
    # Single/double chars that slip through min-length check after URL stripping
    "ve re ll ve".split()
)

# Pre-compiled regex that matches any token that looks like a URL.
_URL_RE = re.compile(r"https?://\S+|www\.\S+", re.IGNORECASE)


# ─── Helpers ─────────────────────────────────────────────────────────────────

def _as_utc(dt: datetime) -> datetime:
    """Return *dt* as a timezone-aware UTC datetime regardless of its original tzinfo."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _subreddit_not_found(name: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Subreddit 'r/{name}' is not being tracked. "
               "Trigger an ingestion first via POST /ingest.",
    )


def _extract_keywords(texts: List[str], top_n: int = 20) -> List[KeywordItem]:
    """Simple frequency-based keyword extraction from a list of comment bodies.

    URLs are stripped before tokenisation so that link fragments (``https``,
    ``watch``, ``v``, ``t.co``, etc.) never reach the word count.  The
    expanded ``_STOPWORDS`` set provides a second layer of defence for any
    domain tokens that survive punctuation stripping.
    """
    translator = str.maketrans("", "", string.punctuation)
    word_counts: Counter = Counter()

    for text in texts:
        # Layer 1 — remove full URLs before doing anything else.
        clean = _URL_RE.sub(" ", text)
        # Layer 2 — strip punctuation, lowercase, split.
        words = clean.lower().translate(translator).split()
        # Layer 3 — stopword filter + minimum token length.
        filtered = [w for w in words if len(w) > 3 and w not in _STOPWORDS]
        word_counts.update(filtered)

    return [
        KeywordItem(keyword=word, frequency=count)
        for word, count in word_counts.most_common(top_n)
    ]


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get(
    "/subreddits",
    response_model=List[RedditSubredditListItem],
    summary="List all tracked subreddits",
)
async def list_subreddits(
    session: AsyncSession = Depends(get_db_session),
) -> List[RedditSubredditListItem]:
    """Return all subreddits recorded in Postgres, newest first."""
    stmt = select(PlatformAccount).where(
        PlatformAccount.platform == Platform.REDDIT
    ).order_by(PlatformAccount.updated_at.desc())

    result = await session.execute(stmt)
    accounts = result.scalars().all()

    return [
        RedditSubredditListItem(
            subreddit_name=acc.platform_id,
            display_name=acc.display_name,
            member_count=acc.subscriber_count,
            last_ingested_at=acc.updated_at.isoformat() if acc.updated_at else None,
        )
        for acc in accounts
    ]


@router.get(
    "/subreddits/{subreddit_name}",
    response_model=RedditSubredditMetrics,
    summary="Get subreddit tracking data",
)
async def get_subreddit(
    subreddit_name: str,
    session: AsyncSession = Depends(get_db_session),
) -> RedditSubredditMetrics:
    """
    Combine Postgres account metadata with the latest MongoDB payload snapshot
    to produce a full subreddit metrics card for the dashboard state dropdown.
    """
    stmt = select(PlatformAccount).where(
        PlatformAccount.platform == Platform.REDDIT,
        PlatformAccount.platform_id == subreddit_name,
    )
    result = await session.execute(stmt)
    account = result.scalar_one_or_none()

    if account is None:
        raise _subreddit_not_found(subreddit_name)

    # Latest MongoDB snapshot (member count may be fresher here)
    payloads_coll = get_video_payloads_collection()
    payload_doc = await payloads_coll.find_one(
        {"platform": "reddit", "platform_id": subreddit_name},
        {"_id": 0, "stats": 1, "ingested_at": 1},
    )
    mongo_ingested = (payload_doc or {}).get("ingested_at")
    pg_updated = account.updated_at

    # Normalise both timestamps to aware UTC before comparing.
    if mongo_ingested is not None:
        m_dt: datetime | None = _as_utc(mongo_ingested)
    else:
        m_dt = None

    if pg_updated is not None:
        pg_dt: datetime | None = _as_utc(pg_updated)
    else:
        pg_dt = None

    if pg_dt is not None and m_dt is not None:
        last_ingested = pg_dt if pg_dt > m_dt else m_dt
    else:
        last_ingested = pg_dt or m_dt

    return RedditSubredditMetrics(
        subreddit_name=account.platform_id,
        display_name=account.display_name,
        description=account.description,
        member_count=account.subscriber_count,
        last_ingested_at=last_ingested.isoformat() if hasattr(last_ingested, "isoformat") else str(last_ingested) if last_ingested else None,
    )


@router.get(
    "/subreddits/{subreddit_name}/sentiment",
    response_model=SentimentDistribution,
    summary="Comment sentiment matrix for a subreddit",
)
async def get_subreddit_sentiment(
    subreddit_name: str,
    limit: int = Query(default=200, ge=1, le=1000),
    session: AsyncSession = Depends(get_db_session),
) -> SentimentDistribution:
    """
    Run the latest *limit* subreddit comments through SentimentService and
    return an aggregate distribution suited for a dashboard donut chart.
    """
    stmt = select(PlatformAccount).where(
        PlatformAccount.platform == Platform.REDDIT,
        PlatformAccount.platform_id == subreddit_name,
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise _subreddit_not_found(subreddit_name)

    comments_coll = get_comments_collection()
    cursor = (
        comments_coll
        .find(
            {"platform": "reddit", "parent_id": subreddit_name},
            {"_id": 0, "body": 1},
        )
        .sort("ingested_at", -1)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)

    if not docs:
        return SentimentDistribution(
            positive=0.0, neutral=1.0, negative=0.0,
            dominant_label="neutral", total_comments_analysed=0,
        )

    texts = [d.get("body", "") for d in docs]
    results = _sentiment_svc.analyze_batch(texts)
    agg = _sentiment_svc.aggregate_sentiment(results)

    return SentimentDistribution(
        positive=round(agg["positive"], 4),
        neutral=round(agg["neutral"], 4),
        negative=round(agg["negative"], 4),
        dominant_label=agg["dominant_label"],
        total_comments_analysed=len(results),
    )


@router.get(
    "/subreddits/{subreddit_name}/comments",
    response_model=List[CommentSentimentItem],
    summary="Paginated comments with sentiment for a subreddit",
)
async def get_subreddit_comments(
    subreddit_name: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sentiment_filter: Optional[str] = Query(
        default=None,
        description="Filter by sentiment label: positive | neutral | negative",
    ),
) -> List[CommentSentimentItem]:
    """
    Returns a paginated, sentiment-annotated list of subreddit comments.
    Use the `sentiment_filter` query param to show only positive/neutral/negative
    entries in the dashboard comment table.

    When sentiment_filter is provided the query is pushed down to MongoDB
    (using the ``sentiment_label`` field written by the ingestion worker)
    so pagination is correct across the full collection.
    """
    comments_coll = get_comments_collection()
    skip = (page - 1) * page_size

    mongo_filter: dict = {"platform": "reddit", "parent_id": subreddit_name}
    if sentiment_filter:
        # Only return comments that have been sentiment-labelled and match the filter.
        mongo_filter["sentiment_label"] = sentiment_filter

    cursor = (
        comments_coll
        .find(
            mongo_filter,
            {"_id": 0, "platform_id": 1, "author": 1, "body": 1,
             "published_at": 1, "sentiment_label": 1},
        )
        .sort("ingested_at", -1)
        .skip(skip)
        .limit(page_size)
    )
    docs = await cursor.to_list(length=page_size)

    if not docs:
        return []

    # Run the sentiment service only on docs that don't yet have a stored label.
    texts_needed = [
        (i, d.get("body", ""))
        for i, d in enumerate(docs)
        if not d.get("sentiment_label")
    ]
    live_results: dict = {}
    if texts_needed:
        indices, texts = zip(*texts_needed)
        results = _sentiment_svc.analyze_batch(list(texts))
        live_results = dict(zip(indices, results))

    items: List[CommentSentimentItem] = []
    for i, doc in enumerate(docs):
        stored_label = doc.get("sentiment_label")
        if stored_label:
            # Use the pre-computed label stored by the ingestion worker.
            items.append(
                CommentSentimentItem(
                    comment_id=doc.get("platform_id", ""),
                    author=doc.get("author", "anonymous"),
                    body=doc.get("body", ""),
                    published_at=doc.get("published_at"),
                    sentiment_label=stored_label,
                    sentiment_score=0.0,
                    engine="stored",
                )
            )
        elif i in live_results:
            res = live_results[i]
            items.append(
                CommentSentimentItem(
                    comment_id=doc.get("platform_id", ""),
                    author=doc.get("author", "anonymous"),
                    body=doc.get("body", ""),
                    published_at=doc.get("published_at"),
                    sentiment_label=res.label.value,
                    sentiment_score=round(res.score, 4),
                    engine=res.engine,
                )
            )

    return items


@router.get(
    "/subreddits/{subreddit_name}/keywords",
    response_model=List[KeywordItem],
    summary="Top keywords from subreddit comment corpus",
)
async def get_subreddit_keywords(
    subreddit_name: str,
    limit: int = Query(default=200, ge=10, le=1000, description="Comments to scan for keywords"),
    top_n: int = Query(default=20, ge=5, le=50, description="Number of top keywords to return"),
) -> List[KeywordItem]:
    """
    Extract the most frequently used non-stopword tokens from the latest
    subreddit comments. Useful for word-cloud and trending-topic widgets.
    """
    comments_coll = get_comments_collection()
    cursor = (
        comments_coll
        .find(
            {"platform": "reddit", "parent_id": subreddit_name},
            {"_id": 0, "body": 1},
        )
        .sort("ingested_at", -1)
        .limit(limit)
    )
    docs = await cursor.to_list(length=limit)

    if not docs:
        return []

    texts = [d.get("body", "") for d in docs if d.get("body")]
    return _extract_keywords(texts, top_n=top_n)


@router.post(
    "/subreddits/{subreddit_name}/ingest",
    response_model=TaskEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger async Reddit data ingestion",
)
async def trigger_reddit_ingest(subreddit_name: str) -> TaskEnqueuedResponse:
    """
    Enqueue a Celery task to fetch the latest posts and comments for
    *subreddit_name* via the Reddit API (PRAW) and store results in
    MongoDB + Postgres.
    """
    try:
        task = celery_app.send_task(
            "app.tasks.ingestion_tasks.tasks_ingest_reddit_data",
            args=[subreddit_name],
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to enqueue ingestion task. Is the Celery worker running? ({exc})",
        )

    return TaskEnqueuedResponse(
        task_id=task.id,
        message=f"Ingestion task queued for 'r/{subreddit_name}'. "
                "Data will be available within a few seconds.",
    )
