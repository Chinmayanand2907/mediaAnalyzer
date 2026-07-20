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
    mock_task = mocker.patch("app.api.v1.routers.reddit.tasks_ingest_reddit_data.delay")
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
