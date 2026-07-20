import pytest
from app.services.external.youtube_client import YouTubeClient, VideoMetadata, ChannelVideosResponse
from app.services.external.reddit_client import RedditClient, HotThreadsResponse

# ─── YouTubeClient Tests ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_youtube_fetch_video_metadata(mocker):
    """Test fetch_video_metadata parses response correctly."""
    
    # Mock the googleapiclient.discovery.build object
    mock_build = mocker.patch("app.services.external.youtube_client.build")
    
    # Setup mock response for videos().list().execute()
    mock_execute = mocker.MagicMock()
    mock_execute.execute.return_value = {
        "items": [
            {
                "id": "dQw4w9WgXcQ",
                "snippet": {
                    "title": "Never Gonna Give You Up",
                    "channelId": "UC...",
                    "channelTitle": "Rick Astley"
                },
                "statistics": {
                    "viewCount": "1000",
                    "likeCount": "100",
                    "commentCount": "50"
                }
            }
        ]
    }
    
    mock_service = mocker.MagicMock()
    mock_service.videos().list.return_value = mock_execute
    mock_build.return_value = mock_service
    
    client = YouTubeClient(api_key="test_key")
    result = await client.fetch_video_metadata("dQw4w9WgXcQ")
    
    assert isinstance(result, VideoMetadata)
    assert result.video_id == "dQw4w9WgXcQ"
    assert result.title == "Never Gonna Give You Up"
    assert result.statistics.view_count == 1000
    assert result.statistics.like_count == 100

@pytest.mark.asyncio
async def test_youtube_fetch_channel_videos(mocker):
    """Test fetch_channel_videos parsing."""
    
    mock_build = mocker.patch("app.services.external.youtube_client.build")
    
    mock_execute = mocker.MagicMock()
    mock_execute.execute.return_value = {
        "pageInfo": {"totalResults": 1},
        "items": [
            {
                "id": {"videoId": "vid1"},
                "snippet": {
                    "title": "Test Video",
                    "description": "Desc"
                }
            }
        ]
    }
    
    mock_service = mocker.MagicMock()
    mock_service.search().list.return_value = mock_execute
    mock_build.return_value = mock_service
    
    client = YouTubeClient(api_key="test_key")
    result = await client.fetch_channel_videos("channel1")
    
    assert isinstance(result, ChannelVideosResponse)
    assert result.total_results == 1
    assert len(result.videos) == 1
    assert result.videos[0].video_id == "vid1"
    assert result.videos[0].title == "Test Video"

# ─── RedditClient Tests ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reddit_fetch_hot_threads(mocker):
    """Test fetch_hot_threads correctly converts PRAW submissions."""
    
    mock_praw = mocker.patch("app.services.external.reddit_client.praw.Reddit")
    
    # Mock submission object
    mock_submission = mocker.MagicMock()
    mock_submission.id = "post1"
    mock_submission.subreddit = "python"
    mock_submission.title = "Test Post"
    mock_submission.author = "user1"
    mock_submission.selftext = "Body text"
    mock_submission.url = "http://test"
    mock_submission.permalink = "/r/python/post1"
    mock_submission.score = 500
    mock_submission.upvote_ratio = 0.95
    mock_submission.num_comments = 20
    mock_submission.created_utc = 1600000000.0
    mock_submission.is_self = True
    mock_submission.link_flair_text = None
    mock_submission.over_18 = False
    mock_submission.thumbnail = None
    
    # Setup mock reddit instance returning our mock submission
    mock_instance = mocker.MagicMock()
    mock_subreddit = mocker.MagicMock()
    mock_subreddit.hot.return_value = [mock_submission]
    mock_instance.subreddit.return_value = mock_subreddit
    mock_praw.return_value = mock_instance
    
    client = RedditClient(client_id="id", client_secret="secret", user_agent="agent")
    result = await client.fetch_hot_threads("python", limit=1)
    
    assert isinstance(result, HotThreadsResponse)
    assert result.count == 1
    assert result.threads[0].post_id == "post1"
    assert result.threads[0].title == "Test Post"
    assert result.threads[0].score == 500
    assert result.threads[0].author == "user1"
