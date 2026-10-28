/**
 * API client — axios instance pre-configured with base URL.
 *
 * All API call functions live here so components never hard-code endpoints.
 * The Vite dev proxy (vite.config.js) forwards /api → http://localhost:8000
 * so no CORS issues in development.
 *
 * VITE_API_BASE should be set to the backend ROOT url (no trailing slash, no /api/v1).
 * Examples:
 *   - Production:  VITE_API_BASE=https://your-app.hf.space
 *   - Local dev:   leave unset (Vite proxy handles /api → localhost:8000)
 *
 * The axios instance appends /api/v1 automatically via its baseURL.
 * ChatBotPanel uses the same VITE_API_BASE to construct /api/v1/chatbot/query.
 */

import axios from 'axios';

// Backend root URL (no path). In local dev this is empty so the Vite proxy
// can rewrite /api/v1/... → http://localhost:8000/api/v1/...
const BACKEND_ROOT = import.meta.env.VITE_API_BASE || '';

// Full base URL for the axios instance — all endpoints are relative to /api/v1.
const API_BASE = `${BACKEND_ROOT}/api/v1`;

const api = axios.create({
  baseURL: API_BASE,
  timeout: 30000,
  headers: { 'Content-Type': 'application/json' },
});

// ── Response interceptor: unwrap data, surface errors cleanly ──────────────
// Preserves abort/status info so callers can branch on 404/422/503 and
// useAnalytics can ignore CanceledError/AbortError.
api.interceptors.response.use(
  (res) => res.data,
  (err) => {
    const rawDetail = err.response?.data?.detail ?? err.response?.data?.message;
    const message = Array.isArray(rawDetail)
      ? rawDetail.map((d) => d.msg || JSON.stringify(d)).join('; ')
      : rawDetail || err.message || 'Unknown API error';
    const wrapped = new Error(message);
    wrapped.name = err.name || 'Error';
    wrapped.code = err.code;
    wrapped.status = err.response?.status;
    wrapped.response = err.response;
    wrapped.config = err.config;
    return Promise.reject(wrapped);
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
    timeout: 60000,
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


