"""
YouTube Router  —  /api/v1/youtube
====================================

Endpoints
---------
GET  /channels                          — list all tracked YouTube channels (Postgres)
GET  /channels/{channel_id}             — full channel metrics snapshot
GET  /channels/{channel_id}/sentiment   — sentiment distribution across all stored comments
GET  /channels/{channel_id}/comments    — paginated comment list with per-comment sentiment
POST /channels/{channel_id}/ingest      — enqueue a background Celery ingestion task

All DB reads use:
  • PostgreSQL (async SQLAlchemy) for structured account / metrics data
  • MongoDB (Motor) for raw comment payloads and video snapshots
"""

from __future__ import annotations

import re
from collections import Counter
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.schemas import (
    CommentSentimentItem,
    SentimentDistribution,
    TaskEnqueuedResponse,
    YouTubeChannelListItem,
    YouTubeChannelMetrics,
)
from app.db.mongodb import get_comments_collection, get_video_payloads_collection
from app.db.postgres import Platform, PlatformAccount, get_db_session
from app.services.analytics.sentiment_service import SentimentService, SentimentLabel
from app.tasks.ingestion_tasks import tasks_ingest_youtube_data

router = APIRouter(prefix="/youtube", tags=["YouTube"])

# Module-level singleton so the HuggingFace model loads once.
_sentiment_svc = SentimentService()


# ─── Helper ──────────────────────────────────────────────────────────────────

def _account_not_found(channel_id: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"YouTube channel '{channel_id}' is not being tracked. "
               "Trigger an ingestion first via POST /ingest.",
    )


# ─── Endpoints ───────────────────────────────────────────────────────────────

@router.get(
    "/channels",
    response_model=List[YouTubeChannelListItem],
    summary="List tracked YouTube channels",
)
async def list_youtube_channels(
    session: AsyncSession = Depends(get_db_session),
) -> List[YouTubeChannelListItem]:
    """Return all YouTube channels that have been ingested at least once."""
    stmt = select(PlatformAccount).where(
        PlatformAccount.platform == Platform.YOUTUBE
    ).order_by(PlatformAccount.updated_at.desc())

    result = await session.execute(stmt)
    accounts = result.scalars().all()

    return [
        YouTubeChannelListItem(
            channel_id=acc.platform_id,
            display_name=acc.display_name,
            subscriber_count=acc.subscriber_count,
            last_ingested_at=acc.updated_at.isoformat() if acc.updated_at else None,
        )
        for acc in accounts
    ]


@router.get(
    "/channels/{channel_id}",
    response_model=YouTubeChannelMetrics,
    summary="Get YouTube channel metrics",
)
async def get_youtube_channel(
    channel_id: str,
    session: AsyncSession = Depends(get_db_session),
) -> YouTubeChannelMetrics:
    """
    Combine Postgres account metadata with the latest MongoDB video_payload
    snapshot to produce a full channel metrics card.
    """
    # 1. Postgres — account metadata
    stmt = select(PlatformAccount).where(
        PlatformAccount.platform == Platform.YOUTUBE,
        PlatformAccount.platform_id == channel_id,
    )
    result = await session.execute(stmt)
    account = result.scalar_one_or_none()

    if account is None:
        raise _account_not_found(channel_id)

    # 2. MongoDB — latest video payload snapshot
    payloads_coll = get_video_payloads_collection()
    payload_doc = await payloads_coll.find_one(
        {"platform": "youtube", "platform_id": channel_id},
        {"_id": 0, "stats": 1, "ingested_at": 1},
    )

    stats = (payload_doc or {}).get("stats", {})
    ingested_at = (payload_doc or {}).get("ingested_at")

    return YouTubeChannelMetrics(
        channel_id=account.platform_id,
        display_name=account.display_name,
        description=account.description,
        subscriber_count=account.subscriber_count,
        profile_image_url=account.profile_image_url,
        total_views=stats.get("views"),
        total_likes=stats.get("likes"),
        total_videos=stats.get("video_count"),
        last_ingested_at=ingested_at.isoformat() if hasattr(ingested_at, "isoformat") else str(ingested_at) if ingested_at else None,
    )


@router.get(
    "/channels/{channel_id}/sentiment",
    response_model=SentimentDistribution,
    summary="Comment sentiment distribution for a YouTube channel",
)
async def get_youtube_sentiment(
    channel_id: str,
    limit: int = Query(default=200, ge=1, le=1000, description="Max comments to analyse"),
    session: AsyncSession = Depends(get_db_session),
) -> SentimentDistribution:
    """
    Fetch the most recent *limit* comments from MongoDB, run them through the
    SentimentService, and return an aggregate positive/neutral/negative
    distribution ready for a pie/donut chart in the dashboard.
    """
    # Confirm channel is tracked
    stmt = select(PlatformAccount).where(
        PlatformAccount.platform == Platform.YOUTUBE,
        PlatformAccount.platform_id == channel_id,
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none() is None:
        raise _account_not_found(channel_id)

    comments_coll = get_comments_collection()
    cursor = (
        comments_coll
        .find({"platform": "youtube", "parent_id": channel_id}, {"_id": 0, "body": 1})
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
    "/channels/{channel_id}/comments",
    response_model=List[CommentSentimentItem],
    summary="Paginated comments with sentiment for a YouTube channel",
)
async def get_youtube_comments(
    channel_id: str,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    sentiment_filter: Optional[str] = Query(
        default=None,
        description="Filter by sentiment label: positive | neutral | negative",
    ),
) -> List[CommentSentimentItem]:
    """
    Paginated list of comments enriched with per-comment sentiment labels.
    Suitable for the table view in the React dashboard.
    """
    comments_coll = get_comments_collection()
    skip = (page - 1) * page_size
    fetch_size = page_size * 3  # over-fetch so we can filter after analysis

    cursor = (
        comments_coll
        .find(
            {"platform": "youtube", "parent_id": channel_id},
            {"_id": 0, "platform_id": 1, "author": 1, "body": 1, "published_at": 1},
        )
        .sort("ingested_at", -1)
        .skip(skip)
        .limit(fetch_size)
    )
    docs = await cursor.to_list(length=fetch_size)

    if not docs:
        return []

    texts = [d.get("body", "") for d in docs]
    results = _sentiment_svc.analyze_batch(texts)

    items: List[CommentSentimentItem] = []
    for doc, res in zip(docs, results):
        if sentiment_filter and res.label.value != sentiment_filter:
            continue
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
        if len(items) >= page_size:
            break

    return items


@router.post(
    "/channels/{channel_id}/ingest",
    response_model=TaskEnqueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger async YouTube data ingestion",
)
async def trigger_youtube_ingest(channel_id: str) -> TaskEnqueuedResponse:
    """
    Enqueue a Celery background task to pull the latest data for *channel_id*
    from the YouTube Data API and store it in MongoDB + Postgres.

    Returns immediately with a task ID — the client can poll Celery's result
    backend for completion status.
    """
    try:
        task = tasks_ingest_youtube_data.delay(channel_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Failed to enqueue ingestion task. Is the Celery worker running? ({exc})",
        )

    return TaskEnqueuedResponse(
        task_id=task.id,
        message=f"Ingestion task queued for YouTube channel '{channel_id}'. "
                "Data will be available within a few seconds.",
    )
