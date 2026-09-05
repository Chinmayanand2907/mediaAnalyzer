import pytest
import numpy as np
from unittest.mock import patch, MagicMock

from app.services.analytics.semantic_matcher import (
    SemanticMatcher,
    get_semantic_matcher,
    _clean_text,
)


def test_clean_text():
    raw = "Check this out https://youtube.com/watch?v=123 and www.example.com cool!"
    cleaned = _clean_text(raw)
    assert "https://" not in cleaned
    assert "www.example.com" not in cleaned
    assert cleaned == "Check this out and cool!"


def test_semantic_matcher_encoding():
    matcher = SemanticMatcher()
    texts = [
        "Never Gonna Give You Up by Rick Astley",
        "Python FastAPI web development tutorial",
    ]
    embs = matcher.encode(texts)
    assert isinstance(embs, np.ndarray)
    assert embs.shape[0] == 2
    assert embs.shape[1] == 384
    # Check L2 normalization: norm should be close to 1.0
    norm_0 = float(np.linalg.norm(embs[0]))
    assert abs(norm_0 - 1.0) < 1e-3


def test_semantic_matcher_cosine_similarity():
    matcher = SemanticMatcher()
    texts_a = ["Rick Astley song Never Gonna Give You Up"]
    texts_b = [
        "Rick Astley song Never Gonna Give You Up",
        "Quantum mechanics and quantum physics equations",
    ]
    embs_a = matcher.encode(texts_a)
    embs_b = matcher.encode(texts_b)

    sim = matcher.compute_similarity(embs_a, embs_b)
    assert sim.shape == (1, 2)
    # Identical text should have similarity close to 1.0
    assert sim[0, 0] > 0.95
    # Unrelated text should have much lower similarity
    assert sim[0, 1] < 0.35


def test_semantic_match_discussions_to_videos_positive():
    matcher = SemanticMatcher(threshold=0.50)
    discussions = [
        {
            "platform_id": "c_rick",
            "body": "Have you seen Rick Astley's classic Never Gonna Give You Up music video? Absolute masterpiece.",
        },
        {
            "platform_id": "c_bread",
            "body": "How do you get a good crust on sourdough bread when baking at home in a Dutch oven?",
        },
    ]
    candidate_videos = [
        {
            "video_id": "dQw4w9WgXcQ",
            "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
            "description": "The official video for Never Gonna Give You Up by Rick Astley.",
        },
        {
            "video_id": "phys_101",
            "title": "Physics 101: Introduction to Mechanics",
            "description": "Calculus-based introduction to classical mechanics.",
        },
    ]

    matches = matcher.match_discussions_to_videos(discussions, candidate_videos)
    assert "dQw4w9WgXcQ" in matches
    assert len(matches["dQw4w9WgXcQ"]) == 1

    matched_doc, score = matches["dQw4w9WgXcQ"][0]
    assert matched_doc["platform_id"] == "c_rick"
    assert score >= 0.50

    # Unrelated bread comment should not be matched to physics or Rick Astley
    assert "phys_101" not in matches


def test_semantic_matcher_fallback_tfidf():
    matcher = SemanticMatcher(threshold=0.30)
    # Simulate transformer unavailable
    matcher._fallback_mode = True
    matcher._model = None
    matcher._model_load_attempted = True

    discussions = [
        {
            "platform_id": "c1",
            "body": "Python programming language asynchronous await event loop guide",
        }
    ]
    candidate_videos = [
        {
            "video_id": "v_py",
            "title": "Python Asyncio Complete Tutorial Guide",
            "description": "Learn async await event loops in python",
        }
    ]

    matches = matcher.match_discussions_to_videos(discussions, candidate_videos)
    assert "v_py" in matches
    assert len(matches["v_py"]) == 1
    assert matches["v_py"][0][1] > 0.30


@pytest.mark.asyncio
async def test_cross_platform_shared_videos_semantic_only(test_client):
    """
    Test that Reddit comments discussing a video by title WITHOUT any URL
    are successfully detected and linked via semantic matching.
    """
    from app.db.mongodb import get_comments_collection, get_video_payloads_collection

    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    # Clear any previous test data
    await comments_coll.delete_many({})
    await payloads_coll.delete_many({})

    # 1. Insert a candidate YouTube video into payloads
    await payloads_coll.insert_one({
        "platform": "youtube",
        "platform_id": "dQw4w9WgXcQ",
        "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
        "stats": {"views": 1400000000, "likes": 16000000},
        "raw": {"description": "The official video for Never Gonna Give You Up by Rick Astley"},
        "ingested_at": "2024-05-10T10:00:00Z",
    })

    # 2. Insert Reddit comment with NO URL (only title / content discussion)
    await comments_coll.insert_one({
        "platform": "reddit",
        "platform_id": "c_semantic_1",
        "parent_id": "music",
        "post_id": "p_music",
        "author": "MusicLover99",
        "body": "Rick Astley's Never Gonna Give You Up is the greatest 80s pop song ever made honestly.",
        "score": 85,
        "published_at": "2024-05-10T12:00:00Z",
        "permalink": "/r/music/comments/p_music/c_semantic_1",
        "sentiment_label": "positive",
        "sentiment_score": 0.95,
        "ingested_at": "2024-05-10T12:05:00Z",
    })

    # 3. Request shared videos for subreddit 'music'
    response = await test_client.get("/api/v1/cross-platform/shared-videos?subreddit_name=music")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    item = data[0]
    assert item["youtube_video_id"] == "dQw4w9WgXcQ"
    assert item["match_type"] == "semantic"
    assert item["similarity_score"] is not None
    assert item["similarity_score"] >= 0.50
    assert len(item["reddit_discussions"]) == 1

    disc = item["reddit_discussions"][0]
    assert disc["discussion_id"] == "c_semantic_1"
    assert disc["match_type"] == "semantic"
    assert disc["similarity_score"] is not None


@pytest.mark.asyncio
async def test_cross_platform_shared_videos_hybrid_matching(test_client):
    """
    Test that when one comment has a URL and another comment discusses the title,
    the video item gets classified as match_type='hybrid'.
    """
    from app.db.mongodb import get_comments_collection, get_video_payloads_collection

    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    await comments_coll.delete_many({})
    await payloads_coll.delete_many({})

    # YouTube video in payloads
    await payloads_coll.insert_one({
        "platform": "youtube",
        "platform_id": "dQw4w9WgXcQ",
        "title": "Rick Astley - Never Gonna Give You Up (Official Music Video)",
        "stats": {"views": 1400000000, "likes": 16000000},
        "raw": {"description": "Rick Astley music video"},
        "ingested_at": "2024-05-10T10:00:00Z",
    })

    # Comment 1: URL match
    await comments_coll.insert_one({
        "platform": "reddit",
        "platform_id": "c_url",
        "parent_id": "popculture",
        "post_id": "p_pop",
        "author": "UrlPoster",
        "body": "Direct link to video: https://youtu.be/dQw4w9WgXcQ enjoy!",
        "score": 10,
        "published_at": "2024-05-10T11:00:00Z",
        "permalink": "/r/popculture/comments/p_pop/c_url",
        "sentiment_label": "positive",
        "ingested_at": "2024-05-10T11:05:00Z",
    })

    # Comment 2: Semantic match (no URL)
    await comments_coll.insert_one({
        "platform": "reddit",
        "platform_id": "c_sem",
        "parent_id": "popculture",
        "post_id": "p_pop",
        "author": "TextDiscuss",
        "body": "Rick Astley's Never Gonna Give You Up song is playing everywhere right now.",
        "score": 25,
        "published_at": "2024-05-10T12:00:00Z",
        "permalink": "/r/popculture/comments/p_pop/c_sem",
        "sentiment_label": "neutral",
        "ingested_at": "2024-05-10T12:05:00Z",
    })

    response = await test_client.get("/api/v1/cross-platform/shared-videos?subreddit_name=popculture")
    assert response.status_code == 200
    data = response.json()

    assert len(data) == 1
    item = data[0]
    assert item["youtube_video_id"] == "dQw4w9WgXcQ"
    assert item["match_type"] == "hybrid"
    assert item["total_reddit_shares"] == 2
    assert len(item["reddit_discussions"]) == 2
