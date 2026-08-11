import pytest
from unittest.mock import AsyncMock, patch
from app.tasks.ingestion_tasks import tasks_ingest_youtube_data, tasks_ingest_reddit_data, _ingest_youtube_data_async, _ingest_reddit_data_async

@pytest.fixture
def mock_db(mocker):
    """Mock the DB interactions inside the ingestion tasks."""
    mocker.patch("app.tasks.ingestion_tasks.connect_mongo", new_callable=AsyncMock)
    mocker.patch("app.tasks.ingestion_tasks.close_mongo", new_callable=AsyncMock)
    mock_payloads = mocker.patch("app.tasks.ingestion_tasks.get_video_payloads_collection")
    mock_payloads.return_value.update_one = AsyncMock()
    
    mock_comments = mocker.patch("app.tasks.ingestion_tasks.get_comments_collection")
    mock_comments.return_value.update_one = AsyncMock()
    
    mock_session = mocker.MagicMock()
    mock_session_instance = AsyncMock()
    mock_execute_result = mocker.MagicMock()
    mock_execute_result.scalar_one_or_none.return_value = None
    mock_session_instance.execute.return_value = mock_execute_result
    mock_session.return_value.__aenter__.return_value = mock_session_instance
    
    mocker.patch("app.tasks.ingestion_tasks.AsyncSessionLocal", mock_session)
    return mock_session_instance

@pytest.mark.asyncio
async def test_ingest_youtube_data_async(mock_db, mocker):
    """Test the async logic of YouTube ingestion."""
    mocker.patch("app.tasks.ingestion_tasks.asyncio.to_thread", side_effect=[
        {"id": "test_channel", "snippet": {"title": "Test YT Channel"}, "statistics": {"subscriberCount": 100}}, # _fetch_channel_info
        [], # _fetch_channel_videos
        []  # _fetch_video_comments
    ])
    await _ingest_youtube_data_async("test_channel")
    
    assert mock_db.execute.called
    assert mock_db.commit.called

def test_tasks_ingest_youtube_data(mocker, mock_db):
    """Test the celery task wrapper."""
    mock_asyncio_run = mocker.patch("app.tasks.ingestion_tasks.asyncio.run")
    
    result = tasks_ingest_youtube_data(channel_id="test_channel")
    
    assert result == "Successfully ingested YouTube data for test_channel"
    assert mock_asyncio_run.called

@pytest.mark.asyncio
async def test_ingest_reddit_data_async(mock_db, mocker):
    """Test the async logic of Reddit ingestion."""
    mocker.patch("app.tasks.ingestion_tasks.asyncio.to_thread", side_effect=[
        {"id": "test_subreddit", "title": "Test Subreddit", "subscribers": 100, "public_description": "desc"}, # _fetch_sub_info
        [], # _fetch_recent_posts
        []  # _fetch_comments_for_posts
    ])
    await _ingest_reddit_data_async("test_subreddit")
    
    assert mock_db.execute.called
    assert mock_db.commit.called

def test_tasks_ingest_reddit_data(mocker, mock_db):
    """Test the celery task wrapper for Reddit."""
    mock_asyncio_run = mocker.patch("app.tasks.ingestion_tasks.asyncio.run")
    
    result = tasks_ingest_reddit_data(subreddit_name="test_subreddit")

    
    assert result == "Successfully ingested Reddit data for test_subreddit"
    assert mock_asyncio_run.called
