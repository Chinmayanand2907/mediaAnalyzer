import { useState, useMemo, useEffect } from 'react';
import {
  Search, Link as LinkIcon,
  Clock, Scale, MessageSquare, Sparkles, TrendingUp,
  Video, Layers, Eye, ThumbsUp, ExternalLink, Share2, X, CheckCircle2,
  Zap,
} from 'lucide-react';

import { useAnalytics } from '../hooks/useAnalytics';
import {
  fetchSharedVideos,
  fetchCrossPlatformSentiment,
  fetchVideoCrossPlatformEngagement,
} from '../api/client';

import StatCard            from '../components/layout/StatCard';
import CrossSentimentChart from '../components/charts/CrossSentimentChart';

function normalizeRedditUrl(permalink) {
  if (!permalink) return null;
  if (/^https?:\/\//i.test(permalink)) return permalink;
  return `https://reddit.com${permalink.startsWith('/') ? '' : '/'}${permalink}`;
}

function fmt(n) {
  if (n == null) return '—';
  if (n === 0) return '0';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

export default function CrossPlatformView({ onActiveChange }) {
  // ── YouTube Video search / selection state ────────────────────────────
  const [videoQuery, setVideoQuery] = useState('');
  const [activeVideo, setActiveVideo] = useState('');

  // Notify parent of active video change
  useEffect(() => {
    onActiveChange?.(activeVideo || null);
  }, [activeVideo, onActiveChange]);

  // ── Global "Recently Tracked" videos — all DB-tracked videos ──────────
  const { data: globalTracked } = useAnalytics(
    (signal) => fetchSharedVideos(null, 50, signal),
    [],
    { cacheKey: 'global:recently-tracked' }
  );

  // ── Session-analyzed videos: persisted in localStorage ───────────────
  const [sessionVideos, setSessionVideos] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('cx_recently_analyzed') || '[]');
    } catch { return []; }
  });

  // ── Sentiment Comparison (video-aware) ─────────────────────────────────
  const { data: sentimentComp, loading: sentLoading } = useAnalytics(
    (signal) => fetchCrossPlatformSentiment(null, signal, activeVideo || null),
    [activeVideo],
    { enabled: !!activeVideo, cacheKey: `sentiment:all:${activeVideo || 'none'}` }
  );

  // ── Specific Video Cross-Platform Engagement ──────────────────────────
  const { data: videoEngagement, loading: videoLoading } = useAnalytics(
    (signal) => fetchVideoCrossPlatformEngagement(activeVideo, 2000, signal),
    [activeVideo],
    { enabled: !!activeVideo }
  );

  // ── Record each successfully analyzed video into session + localStorage ──
  useEffect(() => {
    if (!videoEngagement || !activeVideo) return;
    const entry = {
      youtube_video_id: videoEngagement.youtube_video_id || activeVideo,
      youtube_title: videoEngagement.youtube_title || activeVideo,
      youtube_url: videoEngagement.youtube_url || null,
    };
    setSessionVideos((prev) => {
      const filtered = prev.filter(
        (v) => v.youtube_video_id !== entry.youtube_video_id
      );
      const next = [entry, ...filtered].slice(0, 5);
      try { localStorage.setItem('cx_recently_analyzed', JSON.stringify(next)); } catch { /* ignore */ }
      return next;
    });
  }, [videoEngagement, activeVideo]);

  // Merged chip list: session-analyzed first, then global DB videos, de-duplicated
  const recentlyTrackedChips = useMemo(() => {
    const sessionIds = new Set(sessionVideos.map((v) => v.youtube_video_id));
    const dbExtras = (globalTracked || []).filter(
      (v) => !sessionIds.has(v.youtube_video_id)
    );
    return [...sessionVideos, ...dbExtras].slice(0, 5);
  }, [sessionVideos, globalTracked]);

  // ── Dynamic Effective Sentiment (Video-specific) ──────────────────────
  const sampleSize = (s) => Number(s?.sample_size || 0);
  const hasSamples = (s) => sampleSize(s?.youtube_sentiment) > 0 || sampleSize(s?.reddit_sentiment) > 0;

  const effectiveSentiment = useMemo(() => {
    if (activeVideo) {
      const veYt = videoEngagement?.youtube_sentiment || null;
      const veRd = videoEngagement?.reddit_sentiment || null;
      if (videoEngagement && (sampleSize(veYt) > 0 || sampleSize(veRd) > 0)) {
        const yt = veYt || { positive: 0, neutral: 0, negative: 0, sample_size: 0 };
        const rd = veRd || { positive: 0, neutral: 0, negative: 0, sample_size: 0 };
        const gap = Number(((yt.positive || 0) - (rd.positive || 0)).toFixed(3));
        return {
          youtube_sentiment: yt,
          reddit_sentiment: rd,
          sentiment_gap: gap,
          audience_response_summary: videoEngagement.sentiment_disparity_note || (
            gap > 0.1
              ? `YouTube reception is notably more positive (${Math.round((yt.positive || 0) * 100)}%) than Reddit community discussion (${Math.round((rd.positive || 0) * 100)}%) for this video.`
              : gap < -0.1
              ? `Reddit discussion is more positive (${Math.round((rd.positive || 0) * 100)}%) than YouTube audience for this video.`
              : `Audience response is closely aligned between YouTube and Reddit for this video.`
          ),
          _scope: 'video',
          _videoId: activeVideo,
        };
      }
      // Fall back to the video-filtered sentiment-comparison.
      if (sentimentComp && hasSamples(sentimentComp)) {
        return { ...sentimentComp, _scope: 'video', _videoId: activeVideo };
      }
      // Explicit empty video scope.
      return {
        youtube_sentiment: { positive: 0, neutral: 0, negative: 0, sample_size: 0 },
        reddit_sentiment: { positive: 0, neutral: 0, negative: 0, sample_size: 0 },
        sentiment_gap: 0,
        audience_response_summary: 'No sentiment comments found for this video yet. Try a video with tracked discussions or ingest fresh data.',
        _scope: 'video',
        _videoId: activeVideo,
      };
    }
    return sentimentComp ? { ...sentimentComp, _scope: 'video' } : sentimentComp;
  }, [activeVideo, videoEngagement, sentimentComp]);

  const sentimentLoading = videoLoading || sentLoading;

  const handleVideoSearch = (e) => {
    e.preventDefault();
    if (videoQuery.trim()) {
      setActiveVideo(videoQuery.trim());
    }
  };

  const handleVideoSelect = (vid) => {
    const vidId = typeof vid === 'string' ? vid : vid.youtube_video_id;
    setVideoQuery(vidId);
    setActiveVideo(vidId);
  };

  const handleClearVideo = () => {
    setVideoQuery('');
    setActiveVideo('');
  };

  // ── Video engagement data ─────────────────────────────────────────────
  const currentVideoData = useMemo(() => {
    if (!activeVideo) return null;
    if (videoEngagement) return videoEngagement;
    return null;
  }, [activeVideo, videoEngagement]);

  // ── Computed KPI Values ────────────────────────────────────────────────
  const subredditsDiscussingCount = currentVideoData?.subreddits_count ?? '—';
  const subredditsListText = currentVideoData?.subreddits_list?.length > 0
    ? `r/${currentVideoData.subreddits_list.slice(0, 3).join(', r/')}${currentVideoData.subreddits_list.length > 3 ? ` +${currentVideoData.subreddits_list.length - 3} more` : ''}`
    : 'Enter a video ID or URL above';

  // Card 2 — Reddit Comments
  const redditTotalComments = currentVideoData?.reddit_total_comments ?? null;
  const redditTotalUpvotes  = currentVideoData?.reddit_total_upvotes  ?? null;
  const redditDiscussionsValue = activeVideo
    ? (redditTotalComments != null ? fmt(redditTotalComments) : '—')
    : '—';
  const redditDiscussionsSub = activeVideo
    ? (redditTotalUpvotes != null
        ? `${fmt(redditTotalUpvotes)} total upvotes across Reddit`
        : 'Enter a video ID or URL above')
    : 'Enter a video ID or URL above';

  // Card 4 — Reddit Posts
  const redditPostsCount = currentVideoData?.reddit_posts_count ?? null;
  const card4Value = activeVideo
    ? (redditPostsCount != null ? fmt(redditPostsCount) : '—')
    : '—';
  const card4Sub = activeVideo
    ? (redditPostsCount != null
        ? `Distinct Reddit thread${redditPostsCount !== 1 ? 's' : ''} about this video`
        : 'No Reddit posts found')
    : 'Enter a video ID or URL above';

  // Card 3 — YouTube Reach
  const hasVideoViews = currentVideoData?.youtube_views != null;
  const card3Value = hasVideoViews ? fmt(currentVideoData.youtube_views) : '—';
  const card3Sub   = hasVideoViews
    ? `${fmt(currentVideoData.youtube_likes)} likes · ${currentVideoData.propagation_speed || 'Active'}`
    : 'Select a video above to see reach';

  return (
    <div className="fade-up" style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>

      {/* ── Header ──────────────────────────────────────────────────────── */}
      <div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <h2 className="gradient-text-cx" style={{ fontSize: 24, fontWeight: 800, letterSpacing: '-0.03em' }}>
            Cross-Platform Analysis
          </h2>
          <span style={{
            fontSize: 11, fontWeight: 800,
            padding: '2px 8px', borderRadius: 12,
            background: 'rgba(6,182,212,0.15)',
            color: 'var(--cx-primary)',
            border: '1px solid rgba(6,182,212,0.3)',
          }}>
            YouTube ⟷ Reddit
          </span>
        </div>
        <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4, maxWidth: 720 }}>
          Analyze any YouTube video's cross-platform reach across Reddit communities — tracking discussion counts, community sentiment, viral propagation, and engagement metrics.
        </p>
      </div>

      {/* ── Search Control ───────────────────────────────────────────────── */}
      <div className="glass-card" style={{ padding: 20, border: '1px solid rgba(6,182,212,0.2)' }}>

        {/* Two-column layout — form left, hints right (collapses when video active) */}
        <div style={{ display: 'flex', gap: 20, alignItems: 'flex-start' }}>

          {/* Left: input + chips */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
              <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Paste a YouTube URL or video ID to see where it's being discussed on Reddit
              </p>
              {activeVideo && (
                <button
                  onClick={handleClearVideo}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 4,
                    padding: '3px 8px', borderRadius: 6,
                    background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.2)',
                    color: '#ef4444', fontSize: 11, fontWeight: 600, cursor: 'pointer',
                  }}
                >
                  <X size={12} /> Clear filter
                </button>
              )}
            </div>

            <form onSubmit={handleVideoSearch} style={{ display: 'flex', gap: 10, marginBottom: 12 }}>
              <div style={{ position: 'relative', flex: 1 }}>
                <input
                  type="text"
                  placeholder="e.g. https://youtu.be/dQw4w9WgXcQ  or  dQw4w9WgXcQ"
                  value={videoQuery}
                  onChange={(e) => setVideoQuery(e.target.value)}
                  style={{
                    width: '100%',
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid var(--border-strong)',
                    borderRadius: 8,
                    padding: '9px 12px 9px 14px',
                    color: 'var(--text-primary)',
                    fontSize: 13,
                    outline: 'none',
                  }}
                  onFocus={(e) => e.target.style.borderColor = 'var(--cx-primary)'}
                  onBlur={(e) => e.target.style.borderColor  = 'var(--border-strong)'}
                />
              </div>
              <button
                type="submit"
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  background: 'linear-gradient(135deg, var(--cx-primary), #3b82f6)',
                  color: '#000', fontWeight: 700, fontSize: 13,
                  padding: '0 20px', borderRadius: 8,
                  border: 'none', cursor: 'pointer',
                  whiteSpace: 'nowrap',
                }}
              >
                <Search size={14} />
                Analyze Video
              </button>
            </form>

            {/* Recently tracked chips */}
            {recentlyTrackedChips.length > 0 && (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', fontSize: 11 }}>
                <span style={{ color: 'var(--text-muted)', fontWeight: 600 }}>Recently tracked:</span>
                {recentlyTrackedChips.map((v) => (
                  <button
                    key={v.youtube_video_id}
                    onClick={() => handleVideoSelect(v)}
                    style={{
                      padding: '3px 9px', borderRadius: 12,
                      background: activeVideo === v.youtube_video_id ? 'rgba(6,182,212,0.25)' : 'rgba(255,255,255,0.05)',
                      border: `1px solid ${activeVideo === v.youtube_video_id ? 'var(--cx-primary)' : 'var(--border)'}`,
                      color: activeVideo === v.youtube_video_id ? 'var(--cx-primary)' : 'var(--text-secondary)',
                      fontSize: 11, cursor: 'pointer', maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                    }}
                    title={v.youtube_title || v.youtube_video_id}
                  >
                    ▶ {v.youtube_title || v.youtube_video_id}
                  </button>
                ))}
              </div>
            )}
          </div>

          {/* Right hint panel — only shown when no active video analysis */}
          {!activeVideo && (
            <div style={{
              flexShrink: 0, width: 220,
              padding: '14px 16px',
              borderRadius: 10,
              background: 'rgba(6,182,212,0.04)',
              border: '1px dashed rgba(6,182,212,0.2)',
              display: 'flex', flexDirection: 'column', gap: 10,
            }}>
              <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--cx-primary)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>
                What you'll discover
              </div>
              {[
                { icon: Layers,       label: 'Which subreddits are sharing it' },
                { icon: MessageSquare,label: 'Reddit discussion threads' },
                { icon: Scale,        label: 'YouTube vs Reddit sentiment gap' },
                { icon: Zap,          label: 'Viral propagation speed' },
                { icon: ThumbsUp,     label: 'Total upvotes & engagement' },
              ].map(({ icon: Icon, label }) => (
                <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{
                    width: 24, height: 24, borderRadius: 6, flexShrink: 0,
                    background: 'rgba(6,182,212,0.12)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                  }}>
                    <Icon size={12} color="var(--cx-primary)" />
                  </div>
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.4 }}>{label}</span>
                </div>
              ))}
            </div>
          )}
        </div>

        {/* Active Analyzed Video Detail Banner */}
        {activeVideo && currentVideoData && (
          <div style={{
            marginTop: 14,
            padding: 12,
            borderRadius: 10,
            background: 'rgba(6,182,212,0.06)',
            border: '1px solid rgba(6,182,212,0.2)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 12,
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12, minWidth: 0, flex: 1 }}>
              {currentVideoData.youtube_thumbnail_url && (
                <img
                  src={currentVideoData.youtube_thumbnail_url}
                  alt=""
                  style={{ width: 96, height: 54, borderRadius: 6, objectFit: 'cover', flexShrink: 0 }}
                />
              )}
              <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {currentVideoData.youtube_title || currentVideoData.youtube_video_id}
                  </span>
                  {currentVideoData.youtube_url && (
                    <a
                      href={currentVideoData.youtube_url}
                      target="_blank"
                      rel="noopener noreferrer"
                      style={{ color: 'var(--cx-primary)', display: 'inline-flex', alignItems: 'center' }}
                      title="Open on YouTube"
                    >
                      <ExternalLink size={12} />
                    </a>
                  )}
                  {activeVideo && (
                    <span style={{
                      display: 'inline-flex', alignItems: 'center', gap: 5,
                      fontSize: 10, fontWeight: 800,
                      padding: '2px 8px', borderRadius: 10,
                      background: 'rgba(34,197,94,0.15)',
                      border: '1px solid rgba(34,197,94,0.3)',
                      color: '#22c55e',
                    }}>
                      <span style={{
                        width: 6, height: 6, borderRadius: '50%',
                        background: '#22c55e',
                        boxShadow: '0 0 6px #22c55e',
                        animation: 'pulse 1.8s ease-in-out infinite',
                      }} />
                      LIVE ANALYSIS
                    </span>
                  )}
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  {currentVideoData.youtube_channel_title && (
                    <span>By <strong>{currentVideoData.youtube_channel_title}</strong></span>
                  )}
                  <span>• {fmt(currentVideoData.youtube_views)} views</span>
                  <span>• {fmt(currentVideoData.youtube_likes)} likes</span>
                  {currentVideoData.subreddits_list?.length > 0 && (
                    <span>• <strong style={{ color: 'var(--cx-primary)' }}>
                      Found in {currentVideoData.subreddits_list.length} subreddit{currentVideoData.subreddits_list.length !== 1 ? 's' : ''}
                    </strong></span>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── 4-card KPI Grid ────────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 16 }}>
        <StatCard
          title="Subreddits Discussing"
          value={activeVideo ? subredditsDiscussingCount : '—'}
          sub={activeVideo ? subredditsListText : 'Enter a video ID or URL above'}
          icon={Layers}
          accent="var(--cx-primary)"
          loading={videoLoading}
        />
        <StatCard
          title="Reddit Comments"
          value={redditDiscussionsValue}
          sub={redditDiscussionsSub}
          icon={MessageSquare}
          accent="var(--rd-primary)"
          loading={videoLoading}
        />
        <StatCard
          title="YouTube Reach"
          value={activeVideo ? card3Value : '—'}
          sub={activeVideo ? card3Sub : 'Enter a video ID or URL above'}
          icon={Eye}
          accent="#f59e0b"
          loading={videoLoading}
        />
        <StatCard
          title="Reddit Posts"
          value={activeVideo ? card4Value : '—'}
          sub={activeVideo ? card4Sub : 'Enter a video ID or URL above'}
          icon={Share2}
          accent="#a78bfa"
          loading={videoLoading}
        />
      </div>

      {/* ── Discussions loading skeleton ─────────────────────────────────── */}
      {activeVideo && videoLoading && (
        <div className="skeleton" style={{ height: 220, borderRadius: 12 }} />
      )}

      {/* ── Top Reddit Discussions (Post-centric) ────────────────────────── */}
      {activeVideo && !videoLoading && videoEngagement && (
        videoEngagement.discussions?.length > 0 ? (
          <div className="glass-card" style={{ padding: 20, border: '1px solid rgba(6,182,212,0.25)' }}>
            <div style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <MessageSquare size={16} color="var(--rd-primary)" />
                <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                  Top Reddit Posts About This Video ({videoEngagement.discussions.length} thread{videoEngagement.discussions.length !== 1 ? 's' : ''} across {videoEngagement.subreddits_list?.length || videoEngagement.subreddits_count || 0} subreddit{(videoEngagement.subreddits_list?.length || videoEngagement.subreddits_count || 0) !== 1 ? 's' : ''})
                </h3>
              </div>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                Reddit posts discussing this video in:{' '}
                <strong style={{ color: 'var(--cx-primary)' }}>
                  {videoEngagement.subreddits_list?.map(s => `r/${s}`).join(', ') || 'Various Subreddits'}
                </strong>
              </p>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
              {videoEngagement.discussions.map((d, i) => (
                <div
                  key={d.discussion_id || i}
                  style={{
                    borderRadius: 10,
                    background: 'rgba(255,255,255,0.02)',
                    border: '1px solid var(--border)',
                    overflow: 'hidden',
                  }}
                >
                  {/* ── Post header ── */}
                  <div style={{ padding: '12px 14px', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
                    {/* Row 1: badges + link */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6, marginBottom: 8 }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
                        <span style={{ padding: '2px 7px', borderRadius: 4, background: 'rgba(244,63,94,0.15)', color: 'var(--rd-primary)', fontWeight: 700, fontSize: 11 }}>
                          r/{d.subreddit}
                        </span>
                        {d.match_type && (
                          <span style={{
                            padding: '1px 6px', borderRadius: 4, fontSize: 10, fontWeight: 700,
                            background: d.match_type === 'url' ? 'rgba(34,197,94,0.12)' : 'rgba(99,102,241,0.12)',
                            color: d.match_type === 'url' ? '#22c55e' : 'var(--cx-primary)',
                            border: `1px solid ${d.match_type === 'url' ? 'rgba(34,197,94,0.25)' : 'rgba(99,102,241,0.25)'}`,
                          }}>
                            {d.match_type === 'url' ? '🔗 Direct Link' : '💬 Topic Match'}
                          </span>
                        )}
                        {d.sentiment_label && (
                          <span style={{
                            padding: '1px 6px', borderRadius: 10, fontSize: 10, fontWeight: 700,
                            background: d.sentiment_label === 'positive' ? 'rgba(34,197,94,0.15)' : d.sentiment_label === 'negative' ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.15)',
                            color: d.sentiment_label === 'positive' ? '#22c55e' : d.sentiment_label === 'negative' ? '#ef4444' : '#f59e0b',
                          }}>
                            {d.sentiment_label}
                          </span>
                        )}
                      </div>
                      {d.permalink && (
                        <a
                          href={normalizeRedditUrl(d.permalink)}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ color: 'var(--cx-primary)', fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4, flexShrink: 0 }}
                        >
                          View Thread <ExternalLink size={11} />
                        </a>
                      )}
                    </div>

                    {/* Row 2: post title */}
                    {d.post_title && (
                      <p style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', margin: '0 0 6px 0', lineHeight: 1.4 }}>
                        {d.post_title}
                      </p>
                    )}

                    {/* Row 3: meta stats */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 12, fontSize: 11, color: 'var(--text-muted)', flexWrap: 'wrap' }}>
                      <span>👤 u/{d.author}</span>
                      <span>▲ {fmt(d.score)} upvotes</span>
                      {d.num_comments > 0 && <span>💬 {fmt(d.num_comments)} comments</span>}
                      {d.published_at && (
                        <span title={d.published_at}>
                          🕐 {new Date(d.published_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short', year: 'numeric' })}
                        </span>
                      )}
                    </div>

                    {/* Row 4: post selftext preview (if any) */}
                    {d.post_body && d.post_body.trim() && (
                      <p style={{ fontSize: 12, color: 'var(--text-secondary)', marginTop: 8, lineHeight: 1.5, margin: '8px 0 0 0',
                        overflow: 'hidden', display: '-webkit-box', WebkitLineClamp: 2, WebkitBoxOrient: 'vertical',
                      }}>
                        {d.post_body}
                      </p>
                    )}
                  </div>

                  {/* ── Top comments from this thread ── */}
                  {d.top_comments?.length > 0 && (
                    <div style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 8, maxHeight: 260, overflowY: 'auto' }}>
                      <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 2 }}>
                        Top Comments ({d.top_comments.length})
                      </div>
                      {d.top_comments.map((c, ci) => (
                        <div
                          key={c.comment_id || ci}
                          style={{
                            padding: '8px 10px', borderRadius: 7,
                            background: 'rgba(255,255,255,0.025)', border: '1px solid rgba(255,255,255,0.06)',
                            display: 'flex', flexDirection: 'column', gap: 4,
                          }}
                        >
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <span style={{ fontSize: 11, fontWeight: 600, color: 'var(--cx-primary)' }}>u/{c.author}</span>
                              <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>▲ {c.score}</span>
                              {c.sentiment_label && (
                                <span style={{
                                  padding: '1px 5px', borderRadius: 8, fontSize: 10, fontWeight: 700,
                                  background: c.sentiment_label === 'positive' ? 'rgba(34,197,94,0.12)' : c.sentiment_label === 'negative' ? 'rgba(239,68,68,0.12)' : 'rgba(245,158,11,0.12)',
                                  color: c.sentiment_label === 'positive' ? '#22c55e' : c.sentiment_label === 'negative' ? '#ef4444' : '#f59e0b',
                                }}>
                                  {c.sentiment_label}
                                </span>
                              )}
                            </div>
                            {c.permalink && (
                              <a href={normalizeRedditUrl(c.permalink)} target="_blank" rel="noopener noreferrer"
                                style={{ color: 'var(--text-muted)', fontSize: 10, display: 'inline-flex', alignItems: 'center', gap: 3 }}>
                                <ExternalLink size={9} />
                              </a>
                            )}
                          </div>
                          <p style={{ fontSize: 12, color: 'var(--text-primary)', lineHeight: 1.5, margin: 0 }}>
                            {c.body}
                          </p>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              ))}
            </div>
          </div>
        ) : (
          <div className="glass-card" style={{ padding: 20, border: '1px solid rgba(107,114,128,0.2)' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <MessageSquare size={16} color="var(--text-muted)" />
              <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                Reddit Discussions Found Across All Subreddits (0)
              </h3>
            </div>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: 0, lineHeight: 1.5 }}>
              No Reddit posts or comments found referencing this video or creator across tracked communities.
            </p>
          </div>
        )
      )}


      {/* ── Sentiment Comparison ─────────────────────────────────────────── */}
      <div className="glass-card" style={{ padding: 20 }}>
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', borderLeft: '3px solid var(--cx-primary)', paddingLeft: 10 }}>
              Audience Sentiment: YouTube vs Reddit
            </h3>
            {activeVideo ? (
              <span style={{
                fontSize: 10, fontWeight: 800, padding: '2px 8px', borderRadius: 10,
                background: 'rgba(6,182,212,0.15)', border: '1px solid rgba(6,182,212,0.3)',
                color: 'var(--cx-primary)',
              }}>
                VIDEO {effectiveSentiment?._videoId || activeVideo}
              </span>
            ) : (
              <span style={{
                fontSize: 10, fontWeight: 800, padding: '2px 8px', borderRadius: 10,
                background: 'rgba(107,114,128,0.12)', border: '1px solid rgba(107,114,128,0.25)',
                color: 'var(--text-muted)',
              }}>
                Awaiting video
              </span>
            )}
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
            {activeVideo
              ? 'How audience reaction on YouTube differs from Reddit discussion for the analyzed video above.'
              : 'Paste a YouTube URL or video ID above and click Analyze Video to see sentiment comparison.'}
          </p>
        </div>
        <CrossSentimentChart
          data={activeVideo ? effectiveSentiment : null}
          loading={activeVideo ? sentimentLoading : false}
        />
      </div>

    </div>
  );
}
