import pytest
from unittest.mock import AsyncMock, patch
from app.tasks.ingestion_tasks import tasks_ingest_youtube_data, tasks_ingest_reddit_data, _ingest_youtube_data_async, _ingest_reddit_data_async

@pytest.fixture
def mock_db(mocker):
    """Mock the DB interactions inside the ingestion tasks."""
    mock_motor = mocker.patch("app.tasks.ingestion_tasks._make_motor_client", new_callable=mocker.MagicMock)
    mock_db_instance = mocker.MagicMock()
    mock_motor.return_value.__getitem__.return_value = mock_db_instance
    mock_collection = mocker.MagicMock()
    mock_collection.update_one = AsyncMock()
    mock_collection.bulk_write = AsyncMock()
    mock_db_instance.__getitem__.return_value = mock_collection
    
    mock_session = mocker.MagicMock()
    mock_session_instance = AsyncMock()
    mock_session_instance.add = mocker.MagicMock()
    mock_execute_result = mocker.MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = None
    mock_session_instance.execute.return_value = mock_execute_result
    mock_session.return_value.__aenter__.return_value = mock_session_instance
    
    mocker.patch("app.tasks.ingestion_tasks.AsyncSessionLocal", mock_session)
    mocker.patch("app.core.celery_app.celery_app.send_task")
    return mock_session_instance

@pytest.mark.asyncio
async def test_ingest_youtube_data_async(mock_db, mocker):
    """Test the async logic of YouTube ingestion."""
    mock_yt = mocker.patch("app.services.external.youtube_client.YouTubeClient")
    instance = mock_yt.return_value
    instance.fetch_channel_videos = AsyncMock(return_value=mocker.MagicMock(items=[]))
    
    mocker.patch("app.tasks.ingestion_tasks.asyncio.to_thread", side_effect=[
        {"display_name": "Test YT Channel", "title": "Test YT Channel", "description": "", "subscriber_count": 100, "profile_image_url": "", "channel_id": "test_channel"},
    ])
    await _ingest_youtube_data_async("test_channel")
    
    assert mock_db.execute.called
    assert mock_db.commit.called

def test_tasks_ingest_youtube_data(mocker, mock_db):
    """Test the celery task wrapper."""
    mock_asyncio_run = mocker.patch("app.tasks.ingestion_tasks.asyncio.run", side_effect=lambda coro: coro.close())
    
    result = tasks_ingest_youtube_data(channel_id="test_channel")
    
    assert result == "Successfully ingested YouTube data for test_channel"
    assert mock_asyncio_run.called

@pytest.mark.asyncio
async def test_ingest_reddit_data_async(mock_db, mocker):
    """Test the async logic of Reddit ingestion."""
    mock_reddit = mocker.patch("app.services.external.reddit_client.RedditClient")
    instance = mock_reddit.return_value
    instance.fetch_hot_threads = AsyncMock(return_value=mocker.MagicMock(threads=[]))
    instance.fetch_top_comments_batched = AsyncMock(return_value={})

    mocker.patch("app.tasks.ingestion_tasks.asyncio.to_thread", side_effect=[
        {"display_name": "Test Subreddit", "title": "Test Subreddit", "description": "desc", "subscriber_count": 100, "over18": False},
        [], # _fetch_recent_posts
        []  # _fetch_comments_for_posts
    ])
    await _ingest_reddit_data_async("test_subreddit")
    
    assert mock_db.execute.called
    assert mock_db.commit.called

def test_tasks_ingest_reddit_data(mocker, mock_db):
    """Test the celery task wrapper for Reddit."""
    mock_asyncio_run = mocker.patch("app.tasks.ingestion_tasks.asyncio.run", side_effect=lambda coro: coro.close())
    
    result = tasks_ingest_reddit_data(subreddit_name="test_subreddit")

    
    assert result == "Successfully ingested Reddit data for test_subreddit"
    assert mock_asyncio_run.called
