import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import CrossPlatformView from '../views/CrossPlatformView';

import * as apiClient from '../api/client';

vi.mock('../api/client', () => ({
  fetchRedditSubreddits: vi.fn(),
  fetchSharedVideos: vi.fn(),
  fetchTopVideos: vi.fn(),
  fetchCrossPlatformSentiment: vi.fn(),
  fetchCorrelationSummary: vi.fn(),
  fetchVideoCrossPlatformEngagement: vi.fn(),
}));

const mockSharedVideos = [
  {
    youtube_video_id: 'dQw4w9WgXcQ',
    youtube_url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    reddit_post_ids: ['post1'],
    reddit_subreddits: ['gaming'],
    total_reddit_shares: 2,
    youtube_views: 1200000,
    youtube_likes: 95000,
    youtube_title: 'Never Gonna Give You Up',
    youtube_channel_title: 'Rick Astley',
    youtube_published_at: '2024-01-01T00:00:00Z',
    youtube_sentiment: { positive: 0.85, neutral: 0.10, negative: 0.05, dominant_label: 'positive', sample_size: 100 },
    reddit_total_upvotes: 250,
    reddit_total_comments: 45,
    reddit_first_shared_at: '2024-01-01T04:00:00Z',
    propagation_delay_hours: 4.0,
    propagation_speed: 'Rapid (< 6h)',
    reddit_sentiment: { positive: 0.50, neutral: 0.30, negative: 0.20, dominant_label: 'positive', sample_size: 2 },
    sentiment_disparity_note: 'YouTube is more positive.',
    topics: ['music', 'rickroll'],
    reddit_discussions: [
      {
        discussion_id: 'c1',
        post_id: 'post1',
        subreddit: 'gaming',
        author: 'GamerX',
        body: 'Check out this awesome track!',
        score: 45,
        published_at: '2024-01-01T04:00:00Z',
        permalink: '/r/gaming/comments/post1/c1',
        sentiment_label: 'positive',
      },
    ],
  },
];

const mockSentiment = {
  youtube_sentiment: { positive: 0.85, neutral: 0.10, negative: 0.05, dominant_label: 'positive', sample_size: 100 },
  reddit_sentiment: { positive: 0.50, neutral: 0.30, negative: 0.20, dominant_label: 'positive', sample_size: 45 },
  sentiment_gap: 0.35,
  audience_response_summary: 'YouTube audience is more positive.',
};

const mockSummary = {
  correlation_summary: {
    total_cross_platform_videos: 1,
    avg_propagation_lag_hours: 4.0,
    total_discussions_linked: 1,
  },
};

import { clearAnalyticsCache } from '../hooks/useAnalytics';

describe('CrossPlatformView Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearAnalyticsCache();
    localStorage.clear();
    sessionStorage.clear();
    apiClient.fetchRedditSubreddits.mockResolvedValue([{ subreddit_name: 'gaming', display_name: 'Gaming' }]);
    apiClient.fetchSharedVideos.mockResolvedValue(mockSharedVideos);
    apiClient.fetchTopVideos.mockResolvedValue([]);
    apiClient.fetchCrossPlatformSentiment.mockResolvedValue(mockSentiment);
    apiClient.fetchCorrelationSummary.mockResolvedValue(mockSummary);
    apiClient.fetchVideoCrossPlatformEngagement.mockResolvedValue(null);
  });

  const mockEngagement = {
    youtube_video_id: 'dQw4w9WgXcQ',
    youtube_url: 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
    youtube_title: 'Never Gonna Give You Up',
    youtube_channel_title: 'Rick Astley',
    youtube_views: 1200000,
    youtube_likes: 95000,
    subreddits_count: 2,
    subreddits_list: ['gaming', 'music'],
    reddit_total_comments: 45,
    reddit_total_upvotes: 250,
    reddit_posts_count: 2,
    propagation_speed: 'Rapid (< 6h)',
    discussions: [
      {
        discussion_id: 'd1',
        subreddit: 'gaming',
        post_title: 'Check out this awesome track!',
        author: 'GamerX',
        score: 45,
        num_comments: 2,
        top_comments: [],
      },
    ],
  };

  it('renders updated KPI cards and analyzes video on submission', async () => {
    apiClient.fetchVideoCrossPlatformEngagement.mockResolvedValue(mockEngagement);
    const user = userEvent.setup();
    render(<CrossPlatformView />);

    expect(await screen.findByText('Cross-Platform Analysis')).toBeInTheDocument();
    // Video mode with no video entered: KPI cards render placeholders
    expect(screen.getByText('Subreddits Discussing')).toBeInTheDocument();
    expect(screen.getByText('Reddit Comments')).toBeInTheDocument();
    expect(screen.getByText('YouTube Reach')).toBeInTheDocument();
    expect(screen.getByText('Reddit Posts')).toBeInTheDocument();

    // Analyze video
    const input = screen.getByPlaceholderText(/e\.g\. https:\/\/youtu\.be/i);
    await act(async () => {
      await user.type(input, 'dQw4w9WgXcQ');
      await user.click(screen.getByRole('button', { name: /Analyze Video/i }));
    });

    expect(await screen.findByText('Never Gonna Give You Up')).toBeInTheDocument();
    expect(screen.getByText('Check out this awesome track!')).toBeInTheDocument();
  });

  it('shows sentiment comparison section', async () => {
    render(<CrossPlatformView />);

    expect(await screen.findByText('Audience Sentiment: YouTube vs Reddit')).toBeInTheDocument();
  });
});

