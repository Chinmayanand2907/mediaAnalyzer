import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import RedditView from '../views/RedditView';

import * as apiClient from '../api/client';

vi.mock('../api/client', () => ({
  fetchRedditSubreddits: vi.fn(),
  fetchRedditSubreddit: vi.fn(),
  fetchRedditSentiment: vi.fn(),
  fetchRedditKeywords: vi.fn(),
  fetchRedditComments: vi.fn(),
  triggerRedditIngest: vi.fn(),
}));

const mockSubreddits = [
  { subreddit_name: 'reactjs', display_name: 'ReactJS' },
];

const mockMetrics = {
  subreddit_name: 'reactjs',
  member_count: 350000,
};

const mockSentiment = {
  positive: 0.7,
  neutral: 0.2,
  negative: 0.1,
  dominant_label: 'positive',
  total_comments_analysed: 500,
};

const mockKeywords = [
  { keyword: 'hooks', frequency: 120 },
  { keyword: 'state', frequency: 95 },
];

const mockComments = [
  { comment_id: 'RC1', author: 'RedditorA', body: 'Love the new hooks!', sentiment_label: 'positive', sentiment_score: 0.95, engine: 'vader' },
];

describe('RedditView Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders subreddit list and displays engagement grids', async () => {
    apiClient.fetchRedditSubreddits.mockResolvedValue(mockSubreddits);
    apiClient.fetchRedditSubreddit.mockResolvedValue(mockMetrics);
    apiClient.fetchRedditSentiment.mockResolvedValue(mockSentiment);
    apiClient.fetchRedditKeywords.mockResolvedValue(mockKeywords);
    apiClient.fetchRedditComments.mockResolvedValue(mockComments);

    render(<RedditView />);
    const user = userEvent.setup();

    // Select a subreddit
    const select = await screen.findByRole('combobox');
    expect(screen.getByText('r/reactjs')).toBeInTheDocument();

    await act(async () => {
      await user.selectOptions(select, 'reactjs');
    });

    // Check Metrics Grid (350000 -> 350.0K)
    expect(await screen.findByText('350.0K')).toBeInTheDocument(); // members
    expect(screen.getByText('hooks')).toBeInTheDocument(); // top trending topic
    expect(screen.getByText('500')).toBeInTheDocument(); // active discussions (from sentiment total_comments)

    // Check Keywords Grid
    // Since Recharts might not render texts visibly in JSDOM the same way, we rely on the StatCard's top keyword rendering 'hooks'
    expect(screen.getByText('Trending Keywords')).toBeInTheDocument();

    // Check Comments Grid
    expect(screen.getByText('Love the new hooks!')).toBeInTheDocument();
  });
});
