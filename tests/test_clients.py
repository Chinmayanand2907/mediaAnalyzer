import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from pydantic import ValidationError

from app.services.external.youtube_client import (
    YouTubeClient, VideoMetadata, ChannelVideosResponse, CommentThreadsResponse
)
from app.services.external.reddit_client import (
    RedditClient, HotThreadsResponse, PostDetailResponse, TopCommentsResponse
)

pytestmark = pytest.mark.asyncio

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  YouTube Client Schema & Mapping Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def test_youtube_video_metadata_mapping():
    """Test that YouTube video API payloads map correctly to VideoMetadata Pydantic models."""
    # Dummy raw payload from YouTube list API
    mock_payload = {
        "items": [{
            "id": "dQw4w9WgXcQ",
            "snippet": {
                "title": "Never Gonna Give You Up",
                "description": "Rick Astley - Never Gonna Give You Up",
                "channelId": "UCuAXFUrRGywIeOPZGy78Dyg",
                "channelTitle": "RickAstleyVEVO",
                "publishedAt": "2009-10-25T06:57:33Z",
                "tags": ["Rick Astley", "Never Gonna Give You Up"],
                "categoryId": "10",
                "thumbnails": {
                    "high": {"url": "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"}
                }
            },
            "statistics": {
                "viewCount": "1500000000",
                "likeCount": "17000000",
                "commentCount": "1200000",
                "favoriteCount": "0"
            },
            "contentDetails": {
                "duration": "PT3M33S"
            }
        }]
    }

    with patch("app.services.external.youtube_client.build") as mock_build:
        # Set up mock execute return value
        mock_execute = MagicMock()
        mock_execute.execute.return_value = mock_payload
        
        mock_videos = MagicMock()
        mock_videos.list.return_value = mock_execute
        
        mock_service = MagicMock()
        mock_service.videos.return_value = mock_videos
        
        mock_build.return_value = mock_service
        
        # Instantiate client and call method
        client = YouTubeClient(api_key="mock_key")
        metadata = await client.fetch_video_metadata("dQw4w9WgXcQ")
        
        # Verify schema mapping
        assert isinstance(metadata, VideoMetadata)
        assert metadata.video_id == "dQw4w9WgXcQ"
        assert metadata.title == "Never Gonna Give You Up"
        assert metadata.statistics.view_count == 1500000000
        assert metadata.statistics.like_count == 17000000
        assert metadata.statistics.comment_count == 1200000
        assert metadata.thumbnail_url == "https://i.ytimg.com/vi/dQw4w9WgXcQ/hqdefault.jpg"
        assert metadata.tags == ["Rick Astley", "Never Gonna Give You Up"]

async def test_youtube_channel_videos_mapping():
    """Test mapping search.list response to ChannelVideosResponse."""
    mock_payload = {
        "pageInfo": {"totalResults": 100},
        "nextPageToken": "CAUQAA",
        "items": [
            {
                "id": {"videoId": "vid123"},
                "snippet": {
                    "title": "Video 1",
                    "description": "Desc 1",
                    "publishedAt": "2026-01-01T00:00:00Z",
                    "thumbnails": {
                        "high": {"url": "https://thumb.url/1.jpg"}
                    }
                }
            }
        ]
    }
    
    with patch("app.services.external.youtube_client.build") as mock_build:
        mock_execute = MagicMock()
        mock_execute.execute.return_value = mock_payload
        mock_search = MagicMock()
        mock_search.list.return_value = mock_execute
        mock_service = MagicMock()
        mock_service.search.return_value = mock_search
        mock_build.return_value = mock_service
        
        client = YouTubeClient(api_key="mock_key")
        response = await client.fetch_channel_videos("channel123")
        
        assert isinstance(response, ChannelVideosResponse)
        assert response.channel_id == "channel123"
        assert len(response.videos) == 1
        assert response.videos[0].video_id == "vid123"
        assert response.videos[0].title == "Video 1"
        assert response.next_page_token == "CAUQAA"

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Reddit Client Schema & Mapping Tests
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async def test_reddit_hot_threads_mapping():
    """Test that Reddit submissions correctly map to HotThreadsResponse."""
    # Create fake submission objects
    mock_submission = MagicMock()
    mock_submission.id = "post123"
    mock_submission.subreddit = "python"
    mock_submission.title = "Awesome Python"
    mock_submission.author = "python_dev"
    mock_submission.selftext = "Check out this project!"
    mock_submission.url = "https://example.com"
    mock_submission.permalink = "/r/python/comments/post123"
    mock_submission.score = 500
    mock_submission.upvote_ratio = 0.95
    mock_submission.num_comments = 42
    mock_submission.created_utc = 1700000000.0
    mock_submission.is_self = True
    mock_submission.link_flair_text = "Discussion"
    mock_submission.over_18 = False
    mock_submission.thumbnail = "self"

    with patch("app.services.external.reddit_client.praw.Reddit") as mock_praw:
        # Configure Reddit mock to return our fake submission list
        mock_subreddit = MagicMock()
        mock_subreddit.hot.return_value = [mock_submission]
        
        mock_reddit_instance = MagicMock()
        mock_reddit_instance.subreddit.return_value = mock_subreddit
        mock_praw.return_value = mock_reddit_instance
        
        client = RedditClient(
            client_id="mock", client_secret="mock", user_agent="mock"
        )
        
        response = await client.fetch_hot_threads("python", limit=5)
        
        assert isinstance(response, HotThreadsResponse)
        assert response.subreddit == "python"
        assert len(response.threads) == 1
        
        thread = response.threads[0]
        assert thread.post_id == "post123"
        assert thread.title == "Awesome Python"
        assert thread.author == "python_dev"
        assert thread.score == 500
        assert thread.upvote_ratio == 0.95
        assert thread.link_flair_text == "Discussion"
        assert thread.thumbnail is None  # should be converted from 'self' to None

async def test_reddit_post_detail_mapping():
    """Test mapping submission and comment tree to PostDetailResponse."""
    mock_submission = MagicMock()
    mock_submission.id = "post123"
    mock_submission.subreddit = "python"
    mock_submission.title = "Post Title"
    mock_submission.author = "author1"
    mock_submission.selftext = "Post Body"
    mock_submission.url = "https://example.com"
    mock_submission.permalink = "/r/python/comments/post123"
    mock_submission.score = 100
    mock_submission.upvote_ratio = 0.9
    mock_submission.num_comments = 5
    mock_submission.created_utc = 1700000000.0
    mock_submission.is_self = True
    mock_submission.link_flair_text = None
    mock_submission.over_18 = False
    mock_submission.thumbnail = None

    mock_comment = MagicMock()
    mock_comment.id = "comment999"
    mock_comment.author = "commenter_one"
    mock_comment.body = "Great point!"
    mock_comment.score = 15
    mock_comment.created_utc = 1700000100.0
    mock_comment.permalink = "/r/python/comments/post123/comment999"
    mock_comment.is_submitter = False
    mock_comment.edited = False

    # Mock the submission comments tree (which is a CommentForest, not a raw list)
    mock_comments = MagicMock()
    mock_comments.replace_more = MagicMock()
    mock_comments.__getitem__.return_value = [mock_comment]
    mock_submission.comments = mock_comments

    with patch("app.services.external.reddit_client.praw.Reddit") as mock_praw:
        mock_reddit_instance = MagicMock()
        mock_reddit_instance.submission.return_value = mock_submission
        mock_praw.return_value = mock_reddit_instance
        
        client = RedditClient(
            client_id="mock", client_secret="mock", user_agent="mock"
        )
        
        response = await client.fetch_post_details("post123")
        
        assert isinstance(response, PostDetailResponse)
        assert response.post.post_id == "post123"
        assert len(response.comments) == 1
        assert response.comments[0].comment_id == "comment999"
        assert response.comments[0].body == "Great point!"
        assert response.comments[0].author == "commenter_one"
