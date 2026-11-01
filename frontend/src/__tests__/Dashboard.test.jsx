import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import Dashboard from '../pages/Dashboard';

// Mock all API calls to prevent network errors when children mount
vi.mock('../api/client', () => ({
  fetchYoutubeChannels: vi.fn(() => Promise.resolve([])),
  fetchYoutubeChannel: vi.fn(() => Promise.resolve({})),
  fetchYoutubeSentiment: vi.fn(() => Promise.resolve({ positive: 0, neutral: 0, negative: 0, total_comments_analysed: 0 })),
  fetchYoutubeComments: vi.fn(() => Promise.resolve([])),
  fetchRedditSubreddits: vi.fn(() => Promise.resolve([])),
  fetchRedditSubreddit: vi.fn(() => Promise.resolve({})),
  fetchRedditSentiment: vi.fn(() => Promise.resolve({ positive: 0, neutral: 0, negative: 0, total_comments_analysed: 0 })),
  fetchRedditKeywords: vi.fn(() => Promise.resolve([])),
  fetchRedditComments: vi.fn(() => Promise.resolve([])),
  fetchEngagementComparison: vi.fn(() => Promise.resolve([])),
  fetchSharedVideos: vi.fn(() => Promise.resolve([])),
  fetchTopVideos: vi.fn(() => Promise.resolve([])),
  fetchCrossPlatformSentiment: vi.fn(() => Promise.resolve({
    youtube_sentiment: { positive: 0.7, neutral: 0.2, negative: 0.1, dominant_label: 'positive', sample_size: 10 },
    reddit_sentiment: { positive: 0.5, neutral: 0.3, negative: 0.2, dominant_label: 'positive', sample_size: 10 },
    sentiment_gap: 0.2,
    audience_response_summary: 'Aligned',
  })),
  fetchCrossPlatformTopics: vi.fn(() => Promise.resolve({ shared_topics: [], youtube_topics: [], reddit_topics: [], top_correlations: [] })),
  fetchCorrelationSummary: vi.fn(() => Promise.resolve({})),
  fetchVideoCrossPlatformEngagement: vi.fn(() => Promise.resolve(null)),
}));


describe('Dashboard Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    sessionStorage.clear();
  });

  it('renders YoutubeView by default and switches platforms correctly', async () => {
    const user = userEvent.setup();
    render(<Dashboard />);

    expect(screen.getByRole('heading', { name: 'YouTube Analytics' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'Reddit Insights' })).not.toBeInTheDocument();

    const switchButton = screen.getByRole('button', { name: /switch platform/i });
    await act(async () => {
      await user.click(switchButton);
    });

    const redditOption = screen.getAllByRole('button').find(btn => btn.textContent.includes('Reddit Insights'));
    expect(redditOption).toBeInTheDocument();
    await act(async () => {
      await user.click(redditOption);
    });

    expect(screen.getByRole('heading', { name: 'Reddit Insights' })).toBeInTheDocument();
    expect(screen.queryByRole('heading', { name: 'YouTube Analytics' })).not.toBeInTheDocument();

    await act(async () => {
      await user.click(screen.getByRole('button', { name: /switch platform/i }));
    });
    const crossOption = screen.getAllByRole('button').find(btn => btn.textContent.includes('Cross-Platform'));
    await act(async () => {
      await user.click(crossOption);
    });

    expect(screen.getByRole('heading', { name: 'Cross-Platform Analysis' })).toBeInTheDocument();
  });
});
