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

  it('shows validation error for invalid channel IDs and keeps Ingest disabled', async () => {
    apiClient.fetchYoutubeChannels.mockResolvedValue([]);
    apiClient.fetchYoutubeChannel.mockResolvedValue(null);
    apiClient.fetchYoutubeSentiment.mockResolvedValue(null);
    apiClient.fetchYoutubeComments.mockResolvedValue([]);

    render(<YoutubeView />);
    const user = userEvent.setup();

    // Open the input mode
    const addBtn = await screen.findByTitle('Add a new channel by ID');
    await user.click(addBtn);

    const input = screen.getByPlaceholderText(/UCxxxxxxxxxxxxxxxxxxxxxxxxx/i);
    const ingestBtn = screen.getByRole('button', { name: /Ingest/i });

    const invalidInputs = ['mkbhd', '@MrBeast', 'UCshort', 'ACxxxxxxxxxxxxxxxxxxxxxxxx'];
    for (const bad of invalidInputs) {
      await user.clear(input);
      await user.type(input, bad);
      expect(screen.getByText(/Must start with "UC" and be exactly 24 characters/i)).toBeInTheDocument();
      expect(ingestBtn).toBeDisabled();
    }
  });

  it('clears validation error and enables Ingest for a valid Channel ID', async () => {
    apiClient.fetchYoutubeChannels.mockResolvedValue([]);
    apiClient.fetchYoutubeChannel.mockResolvedValue(null);
    apiClient.fetchYoutubeSentiment.mockResolvedValue(null);
    apiClient.fetchYoutubeComments.mockResolvedValue([]);
    apiClient.triggerYoutubeIngest.mockResolvedValue({ task_id: 'task-1', message: 'ok' });

    render(<YoutubeView />);
    const user = userEvent.setup();

    const addBtn = await screen.findByTitle('Add a new channel by ID');
    await user.click(addBtn);

    const input = screen.getByPlaceholderText(/UCxxxxxxxxxxxxxxxxxxxxxxxxx/i);
    const ingestBtn = screen.getByRole('button', { name: /Ingest/i });

    // Type an invalid ID first
    await user.type(input, 'mkbhd');
    expect(ingestBtn).toBeDisabled();

    // Clear and type a valid Channel ID (exactly 24 chars starting with UC)
    await user.clear(input);
    await user.type(input, 'UCBcRF18a7Qf58cCRy5xuWwQ');

    // Error should be gone; Ingest should be enabled
    expect(screen.queryByText(/Must start with "UC"/i)).not.toBeInTheDocument();
    expect(ingestBtn).not.toBeDisabled();
  });
});

