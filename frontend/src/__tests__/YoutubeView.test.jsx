import { render, screen, act, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import YoutubeView from '../views/YoutubeView';

import * as apiClient from '../api/client';

vi.mock('../api/client', () => ({
  fetchYoutubeChannels: vi.fn(),
  fetchYoutubeChannel: vi.fn(),
  fetchYoutubeSentiment: vi.fn(),
  fetchYoutubeComments: vi.fn(),
  triggerYoutubeIngest: vi.fn(),
}));

const mockChannels = [
  { channel_id: 'UC123', display_name: 'Test Channel 1' },
  { channel_id: 'UC456', display_name: 'Test Channel 2' }
];

const mockMetrics = {
  channel_id: 'UC123',
  subscriber_count: 50000,
  total_views: 1000000,
  total_likes: 20000,
  total_videos: 150,
  description: 'A test channel description.',
  last_ingested_at: '2023-01-01T00:00:00Z',
};

const mockSentiment = {
  positive: 0.6,
  neutral: 0.3,
  negative: 0.1,
  dominant_label: 'positive',
  total_comments_analysed: 1000,
};

const mockComments = [
  { comment_id: 'C1', author: 'UserA', body: 'Great video!', sentiment_label: 'positive', sentiment_score: 0.9, engine: 'vader' },
];

describe('YoutubeView Component', () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it('renders channel list and fetches data on selection', async () => {
    apiClient.fetchYoutubeChannels.mockResolvedValue(mockChannels);
    apiClient.fetchYoutubeChannel.mockResolvedValue(mockMetrics);
    apiClient.fetchYoutubeSentiment.mockResolvedValue(mockSentiment);
    apiClient.fetchYoutubeComments.mockResolvedValue(mockComments);

    render(<YoutubeView />);
    const user = userEvent.setup();

    // Verify channel list loaded
    const select = await screen.findByRole('combobox');
    expect(screen.getByText('Test Channel 1')).toBeInTheDocument();

    // Verify empty state initially
    expect(screen.getByText(/Select a YouTube channel above/i)).toBeInTheDocument();

    // Act: Select a channel
    await act(async () => {
      await user.selectOptions(select, 'UC123');
    });

    // Verify metrics loaded (1000000 -> 1.0M)
    expect(await screen.findByText('1.0M')).toBeInTheDocument(); // total_views
    expect(screen.getByText('50.0K')).toBeInTheDocument(); // subscriber_count
    expect(screen.getByText('20.0K')).toBeInTheDocument(); // total_likes
    
    // Verify Sentiment loaded
    expect(screen.getByText('Comment Sentiment Distribution')).toBeInTheDocument();
    
    // Verify Comments loaded
    expect(screen.getByText('Great video!')).toBeInTheDocument();
  });
});
