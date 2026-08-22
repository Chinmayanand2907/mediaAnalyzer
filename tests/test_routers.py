import pytest
from app.db.postgres import PlatformAccount, Platform

@pytest.mark.asyncio
async def test_youtube_channels_empty(test_client):
    """Test the /api/v1/youtube/channels endpoint when no channels exist."""
    response = await test_client.get("/api/v1/youtube/channels")
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.asyncio
async def test_youtube_channels_with_data(test_client, db_session):
    """Test the /api/v1/youtube/channels endpoint with data."""
    # Seed data
    account = PlatformAccount(
        platform=Platform.YOUTUBE,
        platform_id="UC123",
        display_name="Test Channel",
        subscriber_count=1000
    )
    db_session.add(account)
    await db_session.commit()
    
    response = await test_client.get("/api/v1/youtube/channels")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    assert data[0]["channel_id"] == "UC123"
    assert data[0]["display_name"] == "Test Channel"

@pytest.mark.asyncio
async def test_youtube_channel_not_found(test_client):
    response = await test_client.get("/api/v1/youtube/channels/nonexistent")
    assert response.status_code == 404

@pytest.mark.asyncio
async def test_reddit_subreddits_empty(test_client):
    """Test the /api/v1/reddit/subreddits endpoint when no subreddits exist."""
    response = await test_client.get("/api/v1/reddit/subreddits")
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.asyncio
async def test_reddit_trigger_ingest(test_client, mocker):
    """Test triggering a celery task for reddit."""
    mock_task = mocker.patch("app.api.v1.routers.reddit.celery_app.send_task")
    mock_task.return_value.id = "test-task-id"
    
    response = await test_client.post("/api/v1/reddit/subreddits/python/ingest")
    assert response.status_code == 202
    assert response.json()["task_id"] == "test-task-id"

@pytest.mark.asyncio
async def test_cross_platform_shared_videos_empty(test_client):
    """Test cross-platform shared videos with no data."""
    response = await test_client.get("/api/v1/cross-platform/shared-videos?subreddit_name=python")
    assert response.status_code == 200
    assert response.json() == []

@pytest.mark.asyncio
async def test_cross_platform_engagement_comparison(test_client, db_session):
    """Test the engagement-comparison endpoint."""
    account1 = PlatformAccount(
        platform=Platform.YOUTUBE,
        platform_id="UC_A",
        display_name="Channel A",
        subscriber_count=5000
    )
    account2 = PlatformAccount(
        platform=Platform.REDDIT,
        platform_id="python",
        display_name="Python",
        subscriber_count=10000
    )
    db_session.add_all([account1, account2])
    await db_session.commit()
    
    response = await test_client.get("/api/v1/cross-platform/engagement-comparison")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 2
    platforms = [d["platform"] for d in data]
    assert "youtube" in platforms
    assert "reddit" in platforms

@pytest.mark.asyncio
async def test_cross_platform_shared_videos_with_data(test_client):
    """Test cross-platform shared videos with mock MongoDB comments containing YouTube links."""
    from app.db.mongodb import get_comments_collection, get_video_payloads_collection
    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    # Insert Reddit comments containing YouTube links
    await comments_coll.insert_many([
        {
            "platform": "reddit",
            "platform_id": "c1",
            "parent_id": "gaming",
            "post_id": "p1",
            "author": "GamerUser1",
            "body": "Check out this great gameplay: https://youtu.be/dQw4w9WgXcQ it is awesome!",
            "score": 45,
            "published_at": "2024-05-10T12:00:00Z",
            "permalink": "/r/gaming/comments/p1/c1",
            "sentiment_label": "positive",
            "ingested_at": "2024-05-10T12:05:00Z",
        },
        {
            "platform": "reddit",
            "platform_id": "c2",
            "parent_id": "gaming",
            "post_id": "p2",
            "author": "GamerUser2",
            "body": "Here is the youtube link https://www.youtube.com/watch?v=dQw4w9WgXcQ again.",
            "score": 12,
            "published_at": "2024-05-10T15:30:00Z",
            "permalink": "/r/gaming/comments/p2/c2",
            "sentiment_label": "neutral",
            "ingested_at": "2024-05-10T15:35:00Z",
        }
    ])

    # Insert YouTube payload
    await payloads_coll.insert_one({
        "platform": "youtube",
        "platform_id": "dQw4w9WgXcQ",
        "title": "Never Gonna Give You Up",
        "stats": {"views": 1500000000, "likes": 18000000},
        "raw": {"description": "Rick Astley"},
    })

    response = await test_client.get("/api/v1/cross-platform/shared-videos?subreddit_name=gaming")
    assert response.status_code == 200
    data = response.json()
    assert len(data) == 1
    item = data[0]
    assert item["youtube_video_id"] == "dQw4w9WgXcQ"
    assert item["total_reddit_shares"] == 2
    assert item["youtube_title"] == "Never Gonna Give You Up"
    assert item["youtube_views"] == 1500000000
    assert len(item["reddit_discussions"]) == 2
    assert item["reddit_discussions"][0]["author"] in ["GamerUser1", "GamerUser2"]
    assert item["reddit_sentiment"] is not None
    assert item["reddit_sentiment"]["sample_size"] == 2

@pytest.mark.asyncio
async def test_cross_platform_sentiment_comparison(test_client):
    """Test the sentiment-comparison endpoint."""
    from app.db.mongodb import get_comments_collection
    comments_coll = get_comments_collection()
    await comments_coll.insert_many([
        {"platform": "reddit", "parent_id": "gaming", "sentiment_label": "positive"},
        {"platform": "reddit", "parent_id": "gaming", "sentiment_label": "negative"},
        {"platform": "youtube", "parent_id": "ch1", "sentiment_label": "positive"},
    ])

    response = await test_client.get("/api/v1/cross-platform/sentiment-comparison?subreddit_name=gaming")
    assert response.status_code == 200
    data = response.json()
    assert "youtube_sentiment" in data
    assert "reddit_sentiment" in data
    assert "sentiment_gap" in data
    assert "audience_response_summary" in data

@pytest.mark.asyncio
async def test_cross_platform_topic_correlation(test_client):
    """Test the topic-correlation endpoint."""
    from app.db.mongodb import get_comments_collection, get_video_payloads_collection
    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    await comments_coll.insert_one({
        "platform": "reddit",
        "parent_id": "gaming",
        "body": "Gaming gameplay walkthrough and review discussion",
    })
    await payloads_coll.insert_one({
        "platform": "youtube",
        "platform_id": "vid1",
        "title": "Epic Gaming Walkthrough Gameplay Part 1",
    })

    response = await test_client.get("/api/v1/cross-platform/topic-correlation?subreddit_name=gaming")
    assert response.status_code == 200
    data = response.json()
    assert "shared_topics" in data
    assert "youtube_topics" in data
    assert "reddit_topics" in data
    assert "top_correlations" in data

@pytest.mark.asyncio
async def test_cross_platform_correlation_summary(test_client, db_session):
    """Test the complete correlation-summary endpoint."""
    account = PlatformAccount(
        platform=Platform.REDDIT,
        platform_id="gaming",
        display_name="Gaming",
        subscriber_count=30000000
    )
    db_session.add(account)
    await db_session.commit()

    response = await test_client.get("/api/v1/cross-platform/correlation-summary?subreddit_name=gaming")
    assert response.status_code == 200
    data = response.json()
    assert "shared_videos" in data
    assert "platform_comparison" in data
    assert "sentiment_comparison" in data
    assert "topic_correlation" in data
    assert "correlation_summary" in data
    assert "avg_propagation_lag_hours" in data["correlation_summary"]


@pytest.mark.asyncio
async def test_cross_platform_video_engagement(test_client):
    """Test the video-engagement endpoint for a specific YouTube video."""
    from app.db.mongodb import get_comments_collection, get_video_payloads_collection
    comments_coll = get_comments_collection()
    payloads_coll = get_video_payloads_collection()

    await comments_coll.insert_many([
        {
            "platform": "reddit",
            "platform_id": "comm_1",
            "parent_id": "gaming",
            "post_id": "p_game",
            "author": "PlayerOne",
            "body": "Check this video https://www.youtube.com/watch?v=dQw4w9WgXcQ it is very cool",
            "score": 50,
            "published_at": "2024-05-10T12:00:00Z",
            "sentiment_label": "positive",
            "ingested_at": "2024-05-10T12:05:00Z",
        },
        {
            "platform": "reddit",
            "platform_id": "comm_2",
            "parent_id": "technology",
            "post_id": "p_tech",
            "author": "TechUser",
            "body": "Here is https://youtu.be/dQw4w9WgXcQ for context.",
            "score": 25,
            "published_at": "2024-05-10T14:00:00Z",
            "sentiment_label": "neutral",
            "ingested_at": "2024-05-10T14:05:00Z",
        }
    ])

    await payloads_coll.insert_one({
        "platform": "youtube",
        "platform_id": "dQw4w9WgXcQ",
        "title": "Never Gonna Give You Up",
        "stats": {"views": 1500000000, "likes": 18000000, "comment_count": 500000},
        "raw": {"description": "Rick Astley"},
    })

    # Test with full YouTube URL
    response = await test_client.get("/api/v1/cross-platform/video-engagement?video_url_or_id=https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert response.status_code == 200
    data = response.json()
    assert data["youtube_video_id"] == "dQw4w9WgXcQ"
    assert data["subreddits_count"] == 2
    assert "gaming" in data["subreddits_list"]
    assert "technology" in data["subreddits_list"]
    assert data["total_reddit_discussions"] == 2
    assert data["reddit_total_upvotes"] == 75
    assert data["youtube_views"] == 1500000000
    assert data["youtube_title"] == "Never Gonna Give You Up"
    assert len(data["discussions"]) == 2



