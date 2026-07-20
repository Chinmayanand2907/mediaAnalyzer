"""
Celery tasks for data ingestion from external platforms.

Phase 1 — Intelligence Engine additions:
    task_process_sentiment(platform, target_id)
        Fetches unprocessed comment documents from MongoDB, batches them
        through the globally cached RoBERTa model (or VADER fallback),
        computes Positive / Neutral / Negative percentage distributions,
        and persists the scores into the corresponding PlatformAccount row's
        ``extra_metadata`` JSON column in PostgreSQL.
"""

import asyncio
import json
import uuid
from datetime import datetime, timezone

from celery import shared_task
from celery.utils.log import get_task_logger
from sqlalchemy import select

from app.db.mongodb import (
    connect_mongo,
    close_mongo,
    get_video_payloads_collection,
    get_comments_collection,
)
from app.db.postgres import (
    AsyncSessionLocal,
    PlatformAccount,
    Platform,
)

logger = get_task_logger(__name__)


# ─── Async Helpers ──────────────────────────────────────────────────────────

async def _ingest_youtube_data_async(channel_id: str) -> None:
    """Async implementation of YouTube data ingestion."""
    # Connect to MongoDB for this task execution
    await connect_mongo()
    try:
        # 1. Fetch data using external clients (Placeholder)
        logger.info(f"Fetching YouTube data for channel {channel_id} (Placeholder)")
        # mock_data = await youtube_client.get_channel_data(channel_id)
        mock_payload = {
            "platform": "youtube",
            "platform_id": channel_id,
            "title": f"Mock Channel {channel_id}",
            "stats": {"views": 1000, "likes": 50},
            "raw": {"description": "Sample description"},
            "ingested_at": datetime.now(timezone.utc)
        }
        mock_comments = [
            {
                "platform": "youtube",
                "platform_id": f"comment_{channel_id}_{i}",
                "parent_id": channel_id,
                "author": f"user{i}",
                "body": f"This is comment {i}",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "raw": {},
                "ingested_at": datetime.now(timezone.utc)
            } for i in range(5)
        ]

        # 2. Store raw text in MongoDB
        logger.info(f"Storing raw YouTube data in MongoDB for {channel_id}")
        payloads_coll = get_video_payloads_collection()
        comments_coll = get_comments_collection()
        
        await payloads_coll.update_one(
            {"platform": "youtube", "platform_id": channel_id},
            {"$set": mock_payload},
            upsert=True
        )
        if mock_comments:
            # Upsert comments to avoid duplicates on re-run
            for comment in mock_comments:
                await comments_coll.update_one(
                    {"platform": "youtube", "platform_id": comment["platform_id"]},
                    {"$set": comment},
                    upsert=True
                )

        # 3. Save structured metadata metrics to PostgreSQL
        logger.info(f"Saving structured YouTube metrics to Postgres for {channel_id}")
        async with AsyncSessionLocal() as session:
            stmt = select(PlatformAccount).where(
                PlatformAccount.platform == Platform.YOUTUBE,
                PlatformAccount.platform_id == channel_id
            )
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()
            
            if not account:
                account = PlatformAccount(
                    id=uuid.uuid4(),
                    platform=Platform.YOUTUBE,
                    platform_id=channel_id,
                    display_name=mock_payload["title"],
                    description=mock_payload["raw"].get("description"),
                    subscriber_count=1000, # Mock
                )
                session.add(account)
            else:
                account.display_name = mock_payload["title"]
                account.subscriber_count = 1000
                account.description = mock_payload["raw"].get("description")
                
            await session.commit()

        # 4. Kick off NLP sentiment analysis for this channel
        logger.info(f"Dispatching sentiment analysis task for YouTube channel {channel_id}")
        task_process_sentiment.delay("youtube", channel_id)

    finally:
        # Always close the MongoDB connection when done
        await close_mongo()


async def _ingest_reddit_data_async(subreddit_name: str) -> None:
    """Async implementation of Reddit data ingestion."""
    # Connect to MongoDB for this task execution
    await connect_mongo()
    try:
        # 1. Fetch data using external clients (Placeholder)
        logger.info(f"Fetching Reddit data for subreddit {subreddit_name} (Placeholder)")
        # mock_data = await reddit_client.get_subreddit_data(subreddit_name)
        mock_payload = {
            "platform": "reddit",
            "platform_id": subreddit_name,
            "title": f"r/{subreddit_name}",
            "stats": {"members": 50000},
            "raw": {"description": "A great subreddit"},
            "ingested_at": datetime.now(timezone.utc)
        }
        mock_comments = [
            {
                "platform": "reddit",
                "platform_id": f"comment_{subreddit_name}_{i}",
                "parent_id": subreddit_name,
                "author": f"user{i}",
                "body": f"This is comment {i}",
                "published_at": datetime.now(timezone.utc).isoformat(),
                "raw": {},
                "ingested_at": datetime.now(timezone.utc)
            } for i in range(5)
        ]

        # 2. Store raw text in MongoDB
        logger.info(f"Storing raw Reddit data in MongoDB for {subreddit_name}")
        payloads_coll = get_video_payloads_collection()
        comments_coll = get_comments_collection()
        
        await payloads_coll.update_one(
            {"platform": "reddit", "platform_id": subreddit_name},
            {"$set": mock_payload},
            upsert=True
        )
        if mock_comments:
            for comment in mock_comments:
                await comments_coll.update_one(
                    {"platform": "reddit", "platform_id": comment["platform_id"]},
                    {"$set": comment},
                    upsert=True
                )

        # 3. Save structured metadata metrics to PostgreSQL
        logger.info(f"Saving structured Reddit metrics to Postgres for {subreddit_name}")
        async with AsyncSessionLocal() as session:
            stmt = select(PlatformAccount).where(
                PlatformAccount.platform == Platform.REDDIT,
                PlatformAccount.platform_id == subreddit_name
            )
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()
            
            if not account:
                account = PlatformAccount(
                    id=uuid.uuid4(),
                    platform=Platform.REDDIT,
                    platform_id=subreddit_name,
                    display_name=mock_payload["title"],
                    description=mock_payload["raw"].get("description"),
                    subscriber_count=50000, # Mock
                )
                session.add(account)
            else:
                account.display_name = mock_payload["title"]
                account.subscriber_count = 50000
                account.description = mock_payload["raw"].get("description")
                
            await session.commit()

        # 4. Kick off NLP sentiment analysis for this subreddit
        logger.info(f"Dispatching sentiment analysis task for subreddit {subreddit_name}")
        task_process_sentiment.delay("reddit", subreddit_name)

    finally:
        # Always close the MongoDB connection when done
        await close_mongo()


# ─── Sentiment Processing Helpers ───────────────────────────────────────────

def _roberta_label_to_category(label: str) -> str:
    """
    Map a RoBERTa output label to a canonical sentiment category.

    cardiffnlp/twitter-roberta-base-sentiment-latest emits:
        LABEL_0  → Negative
        LABEL_1  → Neutral
        LABEL_2  → Positive

    Some checkpoints also emit the word directly ("positive" / "neutral" /
    "negative"), so we handle both forms defensively.
    """
    label_lower = label.lower()
    if label_lower in ("label_2", "positive"):
        return "positive"
    if label_lower in ("label_1", "neutral"):
        return "neutral"
    # LABEL_0, "negative", or any unexpected label → negative
    return "negative"


def _vader_compound_to_category(compound: float) -> str:
    """
    Convert VADER compound score to a canonical sentiment category.

    Standard VADER thresholds (Hutto & Gilbert, 2014):
        compound >=  0.05  → positive
        compound <= -0.05  → negative
        otherwise          → neutral
    """
    if compound >= 0.05:
        return "positive"
    if compound <= -0.05:
        return "negative"
    return "neutral"


def _run_roberta_batch(texts: list[str]) -> list[str]:
    """
    Run a list of texts through the globally cached RoBERTa pipeline.

    Returns a list of canonical category strings ("positive" / "neutral" /
    "negative") in the same order as the input.
    """
    # Import the module-level globals set by the worker_process_init signal.
    from app.tasks.celery_app import _roberta_pipeline  # noqa: PLC0415

    if _roberta_pipeline is None:
        raise RuntimeError(
            "RoBERTa pipeline is not loaded. "
            "Ensure worker_process_init has fired before calling this function."
        )

    # The pipeline accepts a list and returns a list of {label, score} dicts.
    # batch_size=32 balances GPU utilisation vs. memory pressure.
    results = _roberta_pipeline(texts, batch_size=32)
    return [_roberta_label_to_category(r["label"]) for r in results]


def _run_vader_batch(texts: list[str]) -> list[str]:
    """
    Run a list of texts through the globally cached VADER analyzer.

    Returns a list of canonical category strings in the same order as the
    input.
    """
    from app.tasks.celery_app import _vader_analyzer  # noqa: PLC0415

    if _vader_analyzer is None:
        raise RuntimeError(
            "VADER analyzer is not loaded. "
            "Ensure worker_process_init has fired before calling this function."
        )

    categories = []
    for text in texts:
        scores = _vader_analyzer.polarity_scores(text)
        categories.append(_vader_compound_to_category(scores["compound"]))
    return categories


async def _process_sentiment_async(platform: str, target_id: str) -> dict:
    """
    Core async implementation of the sentiment extraction loop.

    Steps
    -----
    1. Connect to MongoDB.
    2. Fetch all comments for (platform, parent_id=target_id) that have not
       yet been sentiment-processed (``sentiment_processed`` field absent or
       False).
    3. Batch the ``body`` texts through whichever NLP model is active.
    4. Tally Positive / Neutral / Negative counts; compute percentages.
    5. Bulk-mark processed comments in MongoDB.
    6. Write sentiment percentages into the PlatformAccount.extra_metadata
       JSON column in PostgreSQL.

    Returns
    -------
    dict with keys: total, positive_pct, neutral_pct, negative_pct
    """
    await connect_mongo()
    try:
        comments_coll = get_comments_collection()

        # ── 1. Fetch unprocessed comments ────────────────────────────────────
        cursor = comments_coll.find(
            {
                "platform": platform,
                "parent_id": target_id,
                "sentiment_processed": {"$ne": True},
            },
            # Projection: only the fields we need
            {"_id": 1, "body": 1},
        )
        docs = await cursor.to_list(length=None)

        if not docs:
            logger.info(
                "[Sentiment] No unprocessed comments for %s/%s.", platform, target_id
            )
            return {"total": 0, "positive_pct": 0.0, "neutral_pct": 0.0, "negative_pct": 0.0}

        logger.info(
            "[Sentiment] Processing %d comment(s) for %s/%s.",
            len(docs),
            platform,
            target_id,
        )

        # ── 2. Extract text bodies ────────────────────────────────────────────
        doc_ids = [d["_id"] for d in docs]
        texts = [d.get("body", "") or "" for d in docs]

        # ── 3. Run through NLP model ──────────────────────────────────────────
        from app.tasks.celery_app import _use_vader  # noqa: PLC0415

        if _use_vader:
            categories = _run_vader_batch(texts)
        else:
            categories = _run_roberta_batch(texts)

        # ── 4. Tally counts and compute percentages ───────────────────────────
        total = len(categories)
        counts = {"positive": 0, "neutral": 0, "negative": 0}
        for cat in categories:
            counts[cat] += 1

        positive_pct = round(counts["positive"] / total * 100, 2)
        neutral_pct  = round(counts["neutral"]  / total * 100, 2)
        negative_pct = round(counts["negative"] / total * 100, 2)

        logger.info(
            "[Sentiment] %s/%s → +%.1f%% / ~%.1f%% / -%.1f%%",
            platform, target_id,
            positive_pct, neutral_pct, negative_pct,
        )

        # ── 5. Bulk-mark processed comments in MongoDB ────────────────────────
        await comments_coll.update_many(
            {"_id": {"$in": doc_ids}},
            {
                "$set": {
                    "sentiment_processed": True,
                    "sentiment_processed_at": datetime.now(timezone.utc),
                }
            },
        )

        # ── 6. Persist sentiment scores in PostgreSQL ─────────────────────────
        # Convert platform string to the Platform enum used by the ORM.
        try:
            platform_enum = Platform(platform.lower())
        except ValueError:
            logger.warning(
                "[Sentiment] Unknown platform '%s'. Skipping PostgreSQL update.", platform
            )
            return {
                "total": total,
                "positive_pct": positive_pct,
                "neutral_pct": neutral_pct,
                "negative_pct": negative_pct,
            }

        async with AsyncSessionLocal() as session:
            stmt = select(PlatformAccount).where(
                PlatformAccount.platform == platform_enum,
                PlatformAccount.platform_id == target_id,
            )
            result = await session.execute(stmt)
            account = result.scalar_one_or_none()

            if account is None:
                logger.warning(
                    "[Sentiment] PlatformAccount not found for %s/%s. "
                    "Run the ingestion task first.",
                    platform,
                    target_id,
                )
            else:
                # Merge sentiment scores into the existing extra_metadata JSON blob.
                existing_meta: dict = {}
                if account.extra_metadata:
                    try:
                        existing_meta = json.loads(account.extra_metadata)
                    except json.JSONDecodeError:
                        logger.warning(
                            "[Sentiment] Could not parse existing extra_metadata "
                            "for %s/%s — overwriting.",
                            platform,
                            target_id,
                        )

                existing_meta.update(
                    {
                        "sentiment": {
                            "positive_pct": positive_pct,
                            "neutral_pct": neutral_pct,
                            "negative_pct": negative_pct,
                            "total_comments_analyzed": total,
                            "model": "vader" if _use_vader else "roberta",
                            "analyzed_at": datetime.now(timezone.utc).isoformat(),
                        }
                    }
                )
                account.extra_metadata = json.dumps(existing_meta)
                account.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()
                logger.info(
                    "[Sentiment] Sentiment scores persisted to PostgreSQL for %s/%s.",
                    platform,
                    target_id,
                )

        return {
            "total": total,
            "positive_pct": positive_pct,
            "neutral_pct": neutral_pct,
            "negative_pct": negative_pct,
        }

    finally:
        await close_mongo()


# ─── Celery Tasks ───────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3)
def tasks_ingest_youtube_data(self, channel_id: str) -> str:
    """
    Celery task to ingest YouTube data.
    """
    logger.info(f"Starting YouTube ingestion task for channel: {channel_id}")
    try:
        # Since Celery tasks are synchronous, we run the async code using asyncio
        asyncio.run(_ingest_youtube_data_async(channel_id))
        return f"Successfully ingested YouTube data for {channel_id}"
    except Exception as exc:
        logger.error(f"Error ingesting YouTube data: {exc}")
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=3)
def tasks_ingest_reddit_data(self, subreddit_name: str) -> str:
    """
    Celery task to ingest Reddit data.
    """
    logger.info(f"Starting Reddit ingestion task for subreddit: {subreddit_name}")
    try:
        # Since Celery tasks are synchronous, we run the async code using asyncio
        asyncio.run(_ingest_reddit_data_async(subreddit_name))
        return f"Successfully ingested Reddit data for {subreddit_name}"
    except Exception as exc:
        logger.error(f"Error ingesting Reddit data: {exc}")
        raise self.retry(exc=exc, countdown=60)


@shared_task(bind=True, max_retries=3, name="app.tasks.ingestion_tasks.task_process_sentiment")
def task_process_sentiment(self, platform: str, target_id: str) -> str:
    """
    Celery task: run sentiment analysis on all unprocessed comments for a
    given platform target (YouTube channel or Reddit subreddit).

    Algorithm
    ---------
    1. Fetch comment ``body`` texts from MongoDB where
       ``sentiment_processed != True``.
    2. Batch texts through the globally cached RoBERTa model (or VADER
       fallback) that was loaded by the ``worker_process_init`` signal in
       ``celery_app.py``.
    3. Compute Positive / Neutral / Negative percentage distribution.
    4. Bulk-mark processed comments in MongoDB to avoid re-processing.
    5. Persist the sentiment scores into the ``extra_metadata`` JSON column
       of the matching ``PlatformAccount`` row in PostgreSQL.

    Parameters
    ----------
    platform  : "youtube" | "reddit"
    target_id : channel ID or subreddit name (matches ``parent_id`` in
                the MongoDB comments collection).

    Returns
    -------
    str  Human-readable summary of processed comment count and score
         distribution.
    """
    logger.info(
        "[Sentiment Task] Starting for %s/%s.", platform, target_id
    )
    try:
        result = asyncio.run(_process_sentiment_async(platform, target_id))
        summary = (
            f"Sentiment analysis complete for {platform}/{target_id}: "
            f"{result['total']} comment(s) processed — "
            f"positive={result['positive_pct']}% | "
            f"neutral={result['neutral_pct']}% | "
            f"negative={result['negative_pct']}%"
        )
        logger.info("[Sentiment Task] %s", summary)
        return summary
    except Exception as exc:
        logger.error(
            "[Sentiment Task] Error processing %s/%s: %s", platform, target_id, exc
        )
        raise self.retry(exc=exc, countdown=60)
