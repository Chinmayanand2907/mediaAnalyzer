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
  api.get(`/youtube/channels/${channelId}`, { signal });

export const fetchYoutubeSentiment = (channelId, limit = 200, signal) =>
  api.get(`/youtube/channels/${channelId}/sentiment`, { params: { limit }, signal });

export const fetchYoutubeComments = (channelId, page = 1, pageSize = 20, sentimentFilter = null, signal) =>
  api.get(`/youtube/channels/${channelId}/comments`, {
    params: { page, page_size: pageSize, ...(sentimentFilter && { sentiment_filter: sentimentFilter }) },
    signal,
  });

export const triggerYoutubeIngest = (channelId) =>
  api.post(`/youtube/channels/${channelId}/ingest`);

// ────────────────────────────────────────────────────────────────────────────
// Reddit
// ────────────────────────────────────────────────────────────────────────────

export const fetchRedditSubreddits = (signal) =>
  api.get('/reddit/subreddits', { signal });

export const fetchRedditSubreddit = (subredditName, signal) =>
  api.get(`/reddit/subreddits/${subredditName}`, { signal });

export const fetchRedditSentiment = (subredditName, limit = 200, signal) =>
  api.get(`/reddit/subreddits/${subredditName}/sentiment`, { params: { limit }, signal });

export const fetchRedditComments = (subredditName, page = 1, pageSize = 20, sentimentFilter = null, signal) =>
  api.get(`/reddit/subreddits/${subredditName}/comments`, {
    params: { page, page_size: pageSize, ...(sentimentFilter && { sentiment_filter: sentimentFilter }) },
    signal,
  });

export const fetchRedditKeywords = (subredditName, limit = 200, topN = 20, signal) =>
  api.get(`/reddit/subreddits/${subredditName}/keywords`, { params: { limit, top_n: topN }, signal });

export const triggerRedditIngest = (subredditName) =>
  api.post(`/reddit/subreddits/${subredditName}/ingest`);

// ────────────────────────────────────────────────────────────────────────────
// Cross-Platform
// ────────────────────────────────────────────────────────────────────────────

export const fetchEngagementComparison = (signal) =>
  api.get('/cross-platform/engagement-comparison', { signal });

export const fetchSharedVideos = (subredditName, limit = 500, signal) =>
  api.get('/cross-platform/shared-videos', { params: { subreddit_name: subredditName, limit }, signal });

export const fetchCorrelationSummary = (subredditName, commentScanLimit = 300, signal) =>
  api.get('/cross-platform/correlation-summary', {
    params: { subreddit_name: subredditName, comment_scan_limit: commentScanLimit },
    signal,
  });
