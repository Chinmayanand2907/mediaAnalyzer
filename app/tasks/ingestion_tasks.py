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

import certifi
from celery import shared_task
from celery.utils.log import get_task_logger
from motor.motor_asyncio import AsyncIOMotorClient
from pymongo import UpdateOne
from sqlalchemy import select


from app.core.config import get_settings
from app.db.postgres import (
    AsyncSessionLocal,
    PlatformAccount,
    Platform,
)

logger = get_task_logger(__name__)
settings = get_settings()

# ─── Motor Client Factory ────────────────────────────────────────────────────

def _make_motor_client() -> AsyncIOMotorClient:
    """
    Create a *task-local* Motor client bound to the current event loop.

    Each Celery task calls ``asyncio.run()``, which creates a brand-new
    event loop.  Motor's connection pool is tied to the loop it was created
    on, so we must never reuse a client across ``asyncio.run()`` boundaries.
    This factory is called at the top of every async helper and the returned
    client is closed in the corresponding ``finally`` block before
    ``asyncio.run()`` tears down the loop.
    """
    return AsyncIOMotorClient(
        settings.MONGO_URI,
        maxPoolSize=10,               # modest pool — this client is short-lived
        minPoolSize=0,
        serverSelectionTimeoutMS=15000,  # wait longer for Atlas primary election
        connectTimeoutMS=10000,
        tlsCAFile=certifi.where(),
    )


# ─── Async Helpers ──────────────────────────────────────────────────────────

async def _ingest_youtube_data_async(channel_id: str) -> None:
    """Async implementation of YouTube data ingestion using the real YouTube Data API v3."""
    from app.services.external.youtube_client import YouTubeClient, YouTubeAPIError

    client = _make_motor_client()
    try:
        db = client[settings.MONGO_DB]
        comments_coll  = db["comments"]
        payloads_coll  = db["video_payloads"]

        clean_input = channel_id.strip()
        logger.info(f"Fetching real YouTube data for channel input '{clean_input}'")
        yt = YouTubeClient()

        # ── 1. Fetch channel metadata with multi-strategy resolution ──────
        def _fetch_channel_info():
            # Strategy A: Direct Channel ID lookup
            req = yt._service.channels().list(
                part="snippet,statistics,brandingSettings",
                id=clean_input,
            )
            res = req.execute()
            items = res.get("items", [])
            if items:
                return items[0]

            # Strategy B: Handle lookup (e.g. @mkbhd)
            handle = clean_input if clean_input.startswith("@") else f"@{clean_input}"
            try:
                req = yt._service.channels().list(
                    part="snippet,statistics,brandingSettings",
                    forHandle=handle,
                )
                res = req.execute()
                items = res.get("items", [])
                if items:
                    return items[0]
            except Exception as e:
                logger.debug(f"Handle lookup failed: {e}")

            # Strategy C: Username lookup
            try:
                req = yt._service.channels().list(
                    part="snippet,statistics,brandingSettings",
                    forUsername=clean_input,
                )
                res = req.execute()
                items = res.get("items", [])
                if items:
                    return items[0]
            except Exception as e:
                logger.debug(f"Username lookup failed: {e}")

            # Strategy D: Search channel by query (costs 100 quota units — last resort)
            try:
                logger.warning(
                    "Falling back to search.list for '%s' — costs 100 quota units. "
                    "Pass the channel ID directly to avoid this.",
                    clean_input,
                )
                s_req = yt._service.search().list(
                    part="snippet",
                    q=clean_input,
                    type="channel",
                    maxResults=1,
                )
                s_res = s_req.execute()
                s_items = s_res.get("items", [])
                if s_items:
                    found_id = (
                        s_items[0].get("snippet", {}).get("channelId")
                        or s_items[0].get("id", {}).get("channelId")
                    )
                    if found_id:
                        req = yt._service.channels().list(
                            part="snippet,statistics,brandingSettings",
                            id=found_id,
                        )
                        res = req.execute()
                        items = res.get("items", [])
                        if items:
                            return items[0]
            except Exception as e:
                logger.debug(f"Search lookup failed: {e}")

            return None

        ch = await asyncio.to_thread(_fetch_channel_info)
        if not ch:
            raise ValueError(f"YouTube channel '{clean_input}' not found via API.")

        canonical_channel_id = ch.get("id", clean_input)
        snippet = ch.get("snippet", {})
        stats   = ch.get("statistics", {})
        thumbnails = snippet.get("thumbnails", {})
        thumb_url = (
            thumbnails.get("high", {}).get("url")
            or thumbnails.get("medium", {}).get("url")
            or thumbnails.get("default", {}).get("url")
        )

        display_name     = snippet.get("title", canonical_channel_id)
        description      = snippet.get("description", "")
        subscriber_count = int(stats.get("subscriberCount", 0))
        view_count       = int(stats.get("viewCount", 0))
        video_count      = int(stats.get("videoCount", 0))

        # ── 2. Fetch recent videos ────────────────────────────────────────
        logger.info(f"Fetching recent videos for channel {canonical_channel_id}")
        try:
            videos_resp = await yt.fetch_channel_videos(canonical_channel_id, max_results=10)
            video_ids = [v.video_id for v in videos_resp.videos if v.video_id]
        except YouTubeAPIError as e:
            logger.warning(f"Could not fetch videos for {canonical_channel_id}: {e}")
            video_ids = []

        # ── 3. Fetch comments from recent videos ──────────────────────────
        logger.info(f"Fetching comments for {len(video_ids)} videos from channel {canonical_channel_id}")
        total_likes = 0

        for vid_id in video_ids[:5]:  # limit to 5 videos to save API quota
            try:
                threads_resp = await yt.fetch_comment_threads(vid_id, max_results=50)
                for thread in threads_resp.threads:
                    top = thread.top_comment
                    total_likes += top.like_count
                    comment_doc = {
                        "platform":     "youtube",
                        "platform_id":  top.comment_id,
                        "parent_id":    canonical_channel_id,
                        "video_id":     vid_id,
                        "author":       top.author_name,
                        "body":         top.text,
                        "like_count":   top.like_count,
                        "published_at": top.published_at,
                        "raw":          {},
                        "ingested_at":  datetime.now(timezone.utc),
                    }
                    await comments_coll.update_one(
                        {"platform": "youtube", "platform_id": top.comment_id},
                        {"$set": comment_doc},
                        upsert=True,
                    )
            except YouTubeAPIError as e:
                logger.warning(f"Skipping comments for video {vid_id}: {e}")
                continue

        # ── 4. Store channel payload in MongoDB ───────────────────────────
        logger.info(f"Storing YouTube payload in MongoDB for {canonical_channel_id}")
        payload_doc = {
            "platform":    "youtube",
            "platform_id": canonical_channel_id,
            "title":       display_name,
            "stats": {
                "views":       view_count,
                "likes":       total_likes,
                "video_count": video_count,
            },
            "raw": {"description": description},
            "ingested_at": datetime.now(timezone.utc),
        }
        await payloads_coll.update_one(
            {"platform": "youtube", "platform_id": canonical_channel_id},
            {"$set": payload_doc},
            upsert=True,
        )

        # ── 5. Upsert channel record in PostgreSQL ────────────────────────
        logger.info(f"Saving YouTube channel metrics to Postgres for {canonical_channel_id}")
        async with AsyncSessionLocal() as session:
            stmt = select(PlatformAccount).where(
                PlatformAccount.platform == Platform.YOUTUBE,
                PlatformAccount.platform_id == canonical_channel_id,
            )
            result  = await session.execute(stmt)
            account = result.scalar_one_or_none()

            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            if not account:
                account = PlatformAccount(
                    id=uuid.uuid4(),
                    platform=Platform.YOUTUBE,
                    platform_id=canonical_channel_id,
                    display_name=display_name,
                    description=description,
                    subscriber_count=subscriber_count,
                    profile_image_url=thumb_url,
                    updated_at=now_utc,
                )
                session.add(account)
            else:
                account.display_name    = display_name
                account.description     = description
                account.subscriber_count = subscriber_count
                account.profile_image_url = thumb_url
                account.updated_at      = now_utc

            await session.commit()

        # ── 6. Kick off sentiment analysis ────────────────────────────────
        logger.info(f"Dispatching sentiment task for YouTube channel {canonical_channel_id}")
        from app.core.celery_app import celery_app
        celery_app.send_task("app.tasks.ingestion_tasks.task_process_sentiment", args=["youtube", canonical_channel_id])

    finally:
        client.close()


async def _ingest_reddit_data_async(subreddit_name: str) -> None:
    """Async implementation of Reddit data ingestion using the real PRAW client."""
    from app.services.external.reddit_client import RedditClient, RedditClientError

    client = _make_motor_client()
    try:
        db = client[settings.MONGO_DB]
        comments_coll = db["comments"]
        payloads_coll = db["video_payloads"]

        clean_sub = subreddit_name.strip().lstrip('/').replace('r/', '').replace('/r/', '').strip().lower()
        logger.info(f"Fetching real Reddit data for r/{clean_sub}")
        reddit = RedditClient()

        # ── 1. Fetch subreddit metadata ───────────────────────────────────
        def _fetch_sub_info():
            sub = reddit._reddit.subreddit(clean_sub)
            return {
                "display_name":   sub.display_name,
                "title":          sub.title,
                "description":    sub.public_description or sub.description or "",
                "subscriber_count": sub.subscribers,
                "over18":         sub.over18,
            }

        sub_info = await asyncio.to_thread(_fetch_sub_info)

        display_name     = sub_info["title"] or f"r/{clean_sub}"
        description      = sub_info["description"]
        subscriber_count = sub_info["subscriber_count"] or 0

        # ── 2. Fetch hot threads ──────────────────────────────────────────
        logger.info(f"Fetching hot threads for r/{clean_sub}")
        try:
            hot_resp = await reddit.fetch_hot_threads(clean_sub, limit=10)
            threads  = hot_resp.threads
        except RedditClientError as e:
            logger.warning(f"Could not fetch threads for r/{clean_sub}: {e}")
            threads = []

        # ── 3. Fetch comments from each hot thread ────────────────────────
        logger.info(f"Fetching comments from {len(threads)} hot threads in r/{clean_sub}")

        for thread in threads[:5]:  # limit to 5 posts
            try:
                comments_resp = await reddit.fetch_top_comments(
                    thread.post_id, limit=30, include_replies=False
                )
                for comment in comments_resp.comments:
                    if not comment.body or comment.body in ("[deleted]", "[removed]"):
                        continue
                    comment_doc = {
                        "platform":     "reddit",
                        "platform_id":  comment.comment_id,
                        "parent_id":    clean_sub,
                        "post_id":      thread.post_id,
                        "author":       comment.author,
                        "body":         comment.body,
                        "score":        comment.score,
                        "published_at": datetime.fromtimestamp(
                            comment.created_utc, tz=timezone.utc
                        ).isoformat() if comment.created_utc else None,
                        "permalink":    comment.permalink,
                        "raw":          {},
                        "ingested_at":  datetime.now(timezone.utc),
                    }
                    await comments_coll.update_one(
                        {"platform": "reddit", "platform_id": comment.comment_id},
                        {"$set": comment_doc},
                        upsert=True,
                    )
            except RedditClientError as e:
                logger.warning(f"Skipping comments for post {thread.post_id}: {e}")
                continue

        # ── 4. Store subreddit payload in MongoDB ─────────────────────────
        logger.info(f"Storing Reddit payload in MongoDB for r/{clean_sub}")
        payload_doc = {
            "platform":    "reddit",
            "platform_id": clean_sub,
            "title":       display_name,
            "stats":       {"members": subscriber_count},
            "raw":         {"description": description},
            "ingested_at": datetime.now(timezone.utc),
        }
        await payloads_coll.update_one(
            {"platform": "reddit", "platform_id": clean_sub},
            {"$set": payload_doc},
            upsert=True,
        )

        # ── 5. Upsert subreddit record in PostgreSQL ──────────────────────
        logger.info(f"Saving Reddit metrics to Postgres for r/{clean_sub}")
        async with AsyncSessionLocal() as session:
            stmt = select(PlatformAccount).where(
                PlatformAccount.platform == Platform.REDDIT,
                PlatformAccount.platform_id == clean_sub,
            )
            result  = await session.execute(stmt)
            account = result.scalar_one_or_none()

            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)
            if not account:
                account = PlatformAccount(
                    id=uuid.uuid4(),
                    platform=Platform.REDDIT,
                    platform_id=clean_sub,
                    display_name=display_name,
                    description=description,
                    subscriber_count=subscriber_count,
                    updated_at=now_utc,
                )
                session.add(account)
            else:
                account.display_name     = display_name
                account.description      = description
                account.subscriber_count = subscriber_count
                account.updated_at       = now_utc

            await session.commit()

        # ── 6. Kick off sentiment analysis ────────────────────────────────
        logger.info(f"Dispatching sentiment task for r/{clean_sub}")
        from app.core.celery_app import celery_app
        celery_app.send_task("app.tasks.ingestion_tasks.task_process_sentiment", args=["reddit", clean_sub])

    finally:
        client.close()



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
    Run texts through RoBERTa if the pipeline is pre-loaded, otherwise fall
    back to VADER so sentiment analysis never crashes.
    """
    # Try the pre-loaded pipeline from the worker_process_init signal
    try:
        from app.core.celery_app import _roberta_pipeline  # noqa: PLC0415
        if _roberta_pipeline is not None:
            results = _roberta_pipeline(texts, batch_size=32)
            return [_roberta_label_to_category(r["label"]) for r in results]
    except Exception:
        pass

    # Fallback: use VADER directly (no pre-loading required)
    logger.warning("[Sentiment] RoBERTa not available — falling back to VADER.")
    return _run_vader_batch(texts)


def _run_vader_batch(texts: list[str]) -> list[str]:
    """
    Run texts through VADER. Instantiated on-demand so it works even when
    worker_process_init hasn't pre-loaded a global analyzer.
    """
    from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer  # noqa: PLC0415
    analyzer = SentimentIntensityAnalyzer()

    categories = []
    for text in texts:
        scores = analyzer.polarity_scores(text)
        categories.append(_vader_compound_to_category(scores["compound"]))
    return categories


async def _process_sentiment_async(platform: str, target_id: str) -> dict:
    """
    Core async implementation of the sentiment extraction loop.

    Steps
    -----
    1. Create a task-local Motor client (safe for this asyncio.run() loop).
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
    client = _make_motor_client()
    try:
        db = client[settings.MONGO_DB]
        comments_coll = db["comments"]

        # ── 1. Fetch unprocessed comments in batches to avoid OOM ─────────────────
        # Build cursor but do NOT use to_list(length=None) — that loads everything
        # into RAM at once alongside the 500 MB RoBERTa model.
        _SENTIMENT_BATCH = 500

        cursor = comments_coll.find(
            {
                "platform": platform,
                "parent_id": target_id,
                "sentiment_processed": {"$ne": True},
            },
            {"_id": 1, "body": 1},
        )

        all_doc_ids: list = []
        all_categories: list[str] = []
        batch_docs: list = []
        batch_bulk_ops: list = []

        async def _flush_batch(batch: list) -> None:
            """Run inference on a batch and bulk-write results."""
            if not batch:
                return
            b_ids = [d["_id"] for d in batch]
            b_texts = [d.get("body", "") or "" for d in batch]
            b_cats = _run_roberta_batch(b_texts)
            all_doc_ids.extend(b_ids)
            all_categories.extend(b_cats)
            now_utc_b = datetime.now(timezone.utc)
            ops = [
                UpdateOne(
                    {"_id": doc_id},
                    {"$set": {
                        "sentiment_processed": True,
                        "sentiment_processed_at": now_utc_b,
                        "sentiment_label": category,
                    }},
                )
                for doc_id, category in zip(b_ids, b_cats)
            ]
            if ops:
                await comments_coll.bulk_write(ops, ordered=False)

        async for doc in cursor:
            batch_docs.append(doc)
            if len(batch_docs) >= _SENTIMENT_BATCH:
                await _flush_batch(batch_docs)
                batch_docs = []

        # Flush any remaining documents
        await _flush_batch(batch_docs)

        total = len(all_doc_ids)
        if total == 0:
            logger.info(
                "[Sentiment] No unprocessed comments for %s/%s.", platform, target_id
            )
            return {"total": 0, "positive_pct": 0.0, "neutral_pct": 0.0, "negative_pct": 0.0}

        logger.info(
            "[Sentiment] Processing %d comment(s) for %s/%s.",
            total, platform, target_id,
        )

        # ── 4. Tally counts (categories already computed per-batch above) ─────────
        counts = {"positive": 0, "neutral": 0, "negative": 0}
        for cat in all_categories:
            counts[cat] += 1
        
        positive_ratio = round(counts["positive"] / total, 4)
        neutral_ratio  = round(counts["neutral"]  / total, 4)
        negative_ratio = round(counts["negative"] / total, 4)

        logger.info(
            "[Sentiment] %s/%s → +%.1f%% / ~%.1f%% / -%.1f%%",
            platform, target_id,
            positive_ratio * 100, neutral_ratio * 100, negative_ratio * 100,
        )

        # ── 5. Bulk-mark processed comments in MongoDB ──────────────────────────
        # Write sentiment_label per-document so routers can filter directly in
        # MongoDB instead of having to fetch and filter in Python.
        now_utc = datetime.now(timezone.utc)
        bulk_ops = [
            UpdateOne(
                {"_id": doc_id},
                {
                    "$set": {
                        "sentiment_processed": True,
                        "sentiment_processed_at": now_utc,
                        "sentiment_label": category,
                    }
                },
            )
            for doc_id, category in zip(doc_ids, categories)
        ]
        if bulk_ops:
            await comments_coll.bulk_write(bulk_ops, ordered=False)

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
                "positive_pct": positive_ratio,
                "neutral_pct": neutral_ratio,
                "negative_pct": negative_ratio,
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
                existing_meta: dict = account.extra_metadata or {}
                # Ensure it's a dict just in case
                if not isinstance(existing_meta, dict):
                    existing_meta = {}

                existing_meta.update(
                    {
                        "sentiment": {
                            "positive_pct": positive_ratio,
                            "neutral_pct": neutral_ratio,
                            "negative_pct": negative_ratio,
                            "total_comments_analyzed": total,
                            "model": "roberta_or_vader",
                            "analyzed_at": datetime.now(timezone.utc).isoformat(),
                        }
                    }
                )
                account.extra_metadata = existing_meta
                account.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
                await session.commit()
                logger.info(
                    "[Sentiment] Sentiment scores persisted to PostgreSQL for %s/%s.",
                    platform,
                    target_id,
                )

        return {
            "total": total,
            "positive_pct": positive_ratio,
            "neutral_pct": neutral_ratio,
            "negative_pct": negative_ratio,
        }

    finally:
        client.close()


# ─── Celery Tasks ───────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=3, name="app.tasks.ingestion_tasks.tasks_ingest_youtube_data")
def tasks_ingest_youtube_data(self, channel_id: str) -> str:
    """
    Celery task to ingest YouTube data.
    """
    from app.services.external.youtube_client import YouTubeQuotaExceeded  # noqa: PLC0415

    logger.info(f"Starting YouTube ingestion task for channel: {channel_id}")
    try:
        asyncio.run(_ingest_youtube_data_async(channel_id))
        return f"Successfully ingested YouTube data for {channel_id}"
    except YouTubeQuotaExceeded as exc:
        # YouTube quota resets at midnight Pacific Time — retrying now wastes
        # capacity and fills the result backend with RETRY entries.
        logger.error(
            "YouTube API quota exceeded for %s — NOT retrying (resets midnight PT): %s",
            channel_id, exc,
        )
        return f"QUOTA_EXCEEDED: {exc}"
    except Exception as exc:
        logger.error(f"Error ingesting YouTube data: {exc}")
        # Exponential back-off: 30s → 60s → 120s for attempts 0, 1, 2
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)


@shared_task(bind=True, max_retries=3, name="app.tasks.ingestion_tasks.tasks_ingest_reddit_data")
def tasks_ingest_reddit_data(self, subreddit_name: str) -> str:
    """
    Celery task to ingest Reddit data.
    """
    logger.info(f"Starting Reddit ingestion task for subreddit: {subreddit_name}")
    try:
        asyncio.run(_ingest_reddit_data_async(subreddit_name))
        return f"Successfully ingested Reddit data for {subreddit_name}"
    except Exception as exc:
        logger.error(f"Error ingesting Reddit data: {exc}")
        # Exponential back-off: 30s → 60s → 120s
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)


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
        raise self.retry(exc=exc, countdown=2 ** self.request.retries * 30)
