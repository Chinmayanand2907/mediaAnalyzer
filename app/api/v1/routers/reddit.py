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
import asyncio
import string
from datetime import datetime, timezone
from collections import Counter
from typing import List, Optional, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
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

router = APIRouter(prefix="/reddit", tags=["reddit"])

# Global sentiment service instance
_sentiment_svc: SentimentService | None = None


def _get_sentiment_svc() -> SentimentService:
    """Return the process-level SentimentService, initializing it once."""
    global _sentiment_svc
    if _sentiment_svc is None:
        _sentiment_svc = SentimentService()
    return _sentiment_svc


def _clean_sub_name(name: str) -> str:
    """Clean and normalize a subreddit name input."""
    return name.strip().lstrip('/').replace('r/', '').replace('/r/', '').strip().lower()


_STOPWORDS = {
    "a", "about", "above", "after", "again", "against", "all", "am", "an", "and",
    "any", "are", "aren't", "as", "at", "be", "because", "been", "before", "being",
    "below", "between", "both", "but", "by", "can't", "cannot", "could", "couldn't",
    "did", "didn't", "do", "does", "doesn't", "doing", "don't", "down", "during",
    "each", "few", "for", "from", "further", "had", "hadn't", "has", "hasn't",
    "have", "haven't", "having", "he", "he'd", "he'll", "he's", "her", "here",
    "here's", "hers", "herself", "him", "himself", "his", "how", "how's", "i",
    "i'd", "i'll", "i'm", "i've", "if", "in", "into", "is", "isn't", "it", "it's",
    "its", "itself", "let's", "me", "more", "most", "mustn't", "my", "myself",
    "no", "nor", "not", "of", "off", "on", "once", "only", "or", "other", "ought",
    "our", "ours", "ourselves", "out", "over", "own", "same", "shan't", "she",
    "she'd", "she'll", "she's", "should", "shouldn't", "so", "some", "such", "than",
    "that", "that's", "the", "their", "theirs", "them", "themselves", "then",
    "there", "there's", "these", "they", "they'd", "they'll", "they're", "they've",
    "this", "those", "through", "to", "too", "under", "until", "up", "very", "was",
    "wasn't", "we", "we'd", "we'll", "we're", "we've", "were", "weren't", "what",
    "what's", "when", "when's", "where", "where's", "which", "while", "who", "who's",
    "whom", "why", "why's", "with", "won't", "would", "wouldn't", "you", "you'd",
    "you'll", "you're", "you've", "your", "yours", "yourself", "yourselves",
    # Additional generic / domain stopwords
    "just", "like", "will", "also", "get", "one", "even", "really", "much", "many",
    "know", "think", "people", "would", "could", "make", "made", "good", "well",
    "http", "https", "com", "www", "watch", "youtube", "reddit", "comments",
}

# Regex to strip full URLs from comment text before word extraction
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
    """Simple frequency-based keyword extraction from a list of comment bodies."""
    translator = str.maketrans("", "", string.punctuation)
    word_counts: Counter = Counter()

    for text in texts:
        clean = _URL_RE.sub(" ", text)
        words = clean.lower().translate(translator).split()
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
    clean_sub = _clean_sub_name(subreddit_name)
    stmt = select(PlatformAccount).where(
        PlatformAccount.platform == Platform.REDDIT,
        func.lower(PlatformAccount.platform_id) == clean_sub,
    )
    result = await session.execute(stmt)
    account = result.scalar_one_or_none()

    if account is None:
        raise _subreddit_not_found(clean_sub)

    # Latest MongoDB snapshot (member count may be fresher here)
    payloads_coll = get_video_payloads_collection()
    payload_doc = await payloads_coll.find_one(
        {"platform": "reddit", "platform_id": {"$regex": f"^{re.escape(clean_sub)}$", "$options": "i"}},
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
    clean_sub = _clean_sub_name(subreddit_name)
    stmt = select(PlatformAccount).where(
        PlatformAccount.platform == Platform.REDDIT,
        func.lower(PlatformAccount.platform_id) == clean_sub,
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise _subreddit_not_found(clean_sub)

    comments_coll = get_comments_collection()
    cursor = (
        comments_coll
        .find(
            {"platform": "reddit", "parent_id": {"$regex": f"^{re.escape(clean_sub)}$", "$options": "i"}},
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
    svc = _get_sentiment_svc()
    results = await asyncio.to_thread(svc.analyze_batch, texts)
    agg = svc.aggregate_sentiment(results)

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
    sentiment_filter: Optional[Literal["positive", "neutral", "negative"]] = Query(
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
    clean_sub = _clean_sub_name(subreddit_name)
    comments_coll = get_comments_collection()
    skip = (page - 1) * page_size

    mongo_filter: dict = {
        "platform": "reddit",
        "parent_id": {"$regex": f"^{re.escape(clean_sub)}$", "$options": "i"},
    }
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
        svc = _get_sentiment_svc()
        results = await asyncio.to_thread(svc.analyze_batch, list(texts))
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
    clean_sub = _clean_sub_name(subreddit_name)
    comments_coll = get_comments_collection()
    cursor = (
        comments_coll
        .find(
            {"platform": "reddit", "parent_id": {"$regex": f"^{re.escape(clean_sub)}$", "$options": "i"}},
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
    clean_sub = _clean_sub_name(subreddit_name)
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
