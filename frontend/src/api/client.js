/**
 * API client — axios instance pre-configured with base URL.
 *
 * All API call functions live here so components never hard-code endpoints.
 * The Vite dev proxy (vite.config.js) forwards /api → http://localhost:8000
 * so no CORS issues in development.
 */

import axios from 'axios';

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 15000,
  headers: { 'Content-Type': 'application/json' },
});

// ── Response interceptor: unwrap data, surface errors cleanly ──────────────
api.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const message =
      err.response?.data?.detail ||
      err.response?.data?.message ||
      err.message ||
      'Unknown API error';
    return Promise.reject(new Error(message));
  }
);

// ────────────────────────────────────────────────────────────────────────────
// YouTube
// ────────────────────────────────────────────────────────────────────────────

export const fetchYoutubeChannels = (signal) =>
  api.get('/youtube/channels', { signal });

export const fetchYoutubeChannel = (channelId, signal) =>
  api.get(`/youtube/channels/${encodeURIComponent(channelId)}`, { signal });

export const fetchYoutubeSentiment = (channelId, limit = 200, signal) =>
  api.get(`/youtube/channels/${encodeURIComponent(channelId)}/sentiment`, { params: { limit }, signal });

export const fetchYoutubeComments = (channelId, page = 1, pageSize = 20, sentimentFilter = null, signal) =>
  api.get(`/youtube/channels/${encodeURIComponent(channelId)}/comments`, {
    params: { page, page_size: pageSize, ...(sentimentFilter && { sentiment_filter: sentimentFilter }) },
    signal,
  });

export const triggerYoutubeIngest = (channelId) =>
  api.post(`/youtube/channels/${encodeURIComponent(channelId)}/ingest`);

// ────────────────────────────────────────────────────────────────────────────
// Reddit
// ────────────────────────────────────────────────────────────────────────────

export const fetchRedditSubreddits = (signal) =>
  api.get('/reddit/subreddits', { signal });

export const fetchRedditSubreddit = (subredditName, signal) =>
  api.get(`/reddit/subreddits/${encodeURIComponent(subredditName)}`, { signal });

export const fetchRedditSentiment = (subredditName, limit = 200, signal) =>
  api.get(`/reddit/subreddits/${encodeURIComponent(subredditName)}/sentiment`, { params: { limit }, signal });

export const fetchRedditComments = (subredditName, page = 1, pageSize = 20, sentimentFilter = null, signal) =>
  api.get(`/reddit/subreddits/${encodeURIComponent(subredditName)}/comments`, {
    params: { page, page_size: pageSize, ...(sentimentFilter && { sentiment_filter: sentimentFilter }) },
    signal,
  });

export const fetchRedditKeywords = (subredditName, limit = 200, topN = 20, signal) =>
  api.get(`/reddit/subreddits/${encodeURIComponent(subredditName)}/keywords`, { params: { limit, top_n: topN }, signal });

export const triggerRedditIngest = (subredditName) =>
  api.post(`/reddit/subreddits/${encodeURIComponent(subredditName)}/ingest`);

// ────────────────────────────────────────────────────────────────────────────
// Cross-Platform
// ────────────────────────────────────────────────────────────────────────────

export const fetchEngagementComparison = (signal) =>
  api.get('/cross-platform/engagement-comparison', { signal });

export const fetchSharedVideos = (subredditName, limit = 500, signal, videoUrlOrId = null) =>
  api.get('/cross-platform/shared-videos', {
    params: {
      ...(subredditName && { subreddit_name: subredditName }),
      ...(videoUrlOrId && { video_url_or_id: videoUrlOrId }),
      limit,
    },
    signal,
  });

export const fetchVideoCrossPlatformEngagement = (videoUrlOrId, commentScanLimit = 2000, signal) =>
  api.get('/cross-platform/video-engagement', {
    params: { video_url_or_id: videoUrlOrId, comment_scan_limit: commentScanLimit },
    signal,
  });

export const fetchTopVideos = (topic, maxResults = 10, signal) =>
  api.get('/cross-platform/top-videos', { params: { topic, max_results: maxResults }, signal });

export const fetchCrossPlatformSentiment = (subredditName, signal, videoUrlOrId = null) =>
  api.get('/cross-platform/sentiment-comparison', {
    params: {
      ...(subredditName && { subreddit_name: subredditName }),
      ...(videoUrlOrId && { video_url_or_id: videoUrlOrId }),
    },
    signal,
  });

export const fetchCrossPlatformTopics = (subredditName, signal) =>
  api.get('/cross-platform/topic-correlation', {
    params: { ...(subredditName && { subreddit_name: subredditName }) },
    signal,
  });

export const fetchCorrelationSummary = (subredditName, commentScanLimit = 300, signal, videoUrlOrId = null) =>
  api.get('/cross-platform/correlation-summary', {
    params: {
      ...(subredditName && { subreddit_name: subredditName }),
      ...(videoUrlOrId && { video_url_or_id: videoUrlOrId }),
      comment_scan_limit: commentScanLimit,
    },
    signal,
  });


