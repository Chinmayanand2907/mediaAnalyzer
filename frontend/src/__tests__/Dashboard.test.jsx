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
  fetchCorrelationSummary: vi.fn(() => Promise.resolve({})),
}));

describe('Dashboard Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders YoutubeView by default and switches platforms correctly', async () => {
    const user = userEvent.setup();
    render(<Dashboard />);

    // Assert: Check default view (YouTube)
    expect(screen.getAllByText('YouTube Analytics').length).toBeGreaterThan(0);
    expect(screen.queryByText('Reddit Insights')).not.toBeInTheDocument();

    // Act: Click the dropdown toggle in the Navbar
    const switchButton = screen.getByRole('button', { name: /switch platform/i });
    await act(async () => {
      await user.click(switchButton);
    });

    // Act: Click 'Reddit Insights' from the dropdown
    const redditOption = screen.getAllByRole('button').find(btn => btn.textContent.includes('Reddit Insights'));
    expect(redditOption).toBeInTheDocument();
    await act(async () => {
      await user.click(redditOption);
    });

    // Assert: Reddit view should be visible, YouTube hidden
    expect(await screen.findByText(/Community engagement and keyword trends/i)).toBeInTheDocument();
    expect(screen.queryByText('Sentiment intelligence across your tracked channels')).not.toBeInTheDocument();

    // Act: Switch to Cross-Platform
    await act(async () => {
      await user.click(screen.getByRole('button', { name: /switch platform/i }));
    });
    const crossOption = screen.getAllByRole('button').find(btn => btn.textContent.includes('Cross-Platform'));
    await act(async () => {
      await user.click(crossOption);
    });

    // Assert: Cross-Platform view should be visible
    expect(await screen.findByText(/Global Engagement Index/i)).toBeInTheDocument();
  });
});
