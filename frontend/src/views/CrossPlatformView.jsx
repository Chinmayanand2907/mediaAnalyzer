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
  fetchTopVideos,
  fetchCrossPlatformSentiment,
  fetchCorrelationSummary,
  fetchRedditSubreddits,
  fetchVideoCrossPlatformEngagement,
} from '../api/client';

import StatCard            from '../components/layout/StatCard';
import CrossSentimentChart from '../components/charts/CrossSentimentChart';
import SharedVideosTable   from '../components/tables/SharedVideosTable';

const PRESET_SUBREDDITS = ['gaming', 'askreddit', 'gtaonline', 'technology', 'python'];

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

export default function CrossPlatformView() {
  const [subQuery, setSubQuery]     = useState('');
  const [activeSub, setActiveSub]   = useState('');

  // ── YouTube Video search / selection state ────────────────────────────
  const [videoQuery, setVideoQuery] = useState('');
  const [activeVideo, setActiveVideo] = useState('');

  // ── P1: Unified search mode tab ───────────────────────────────────────
  const [mode, setMode] = useState('video'); // 'video' | 'subreddit'

  // ── Tracked subreddits for quick-select chips ─────────────────────────
  const { data: subreddits } = useAnalytics(
    (signal) => fetchRedditSubreddits(signal),
    []
  );

  // ── Global "Recently Tracked" videos — all DB-tracked videos, no subreddit filter ──
  // Fetches the 50 most recently ingested tracked videos globally (backend sorts by ingested_at desc).
  // Used to fill the "Recently tracked" chips when session history is sparse.
  const { data: globalTracked } = useAnalytics(
    (signal) => fetchSharedVideos(null, 50, signal),
    [],
    { cacheKey: 'global:recently-tracked' }
  );

  // ── Session-analyzed videos: persisted in localStorage ───────────────
  // Every time the user successfully analyzes a video (videoEngagement resolves),
  // we record it so the chips reflect what *this user* has actually analyzed.
  const [sessionVideos, setSessionVideos] = useState(() => {
    try {
      return JSON.parse(localStorage.getItem('cx_recently_analyzed') || '[]');
    } catch { return []; }
  });

  // ── Correlation Summary ───────────────────────────────────────────────
  const { data: summaryData, loading: summaryLoading } = useAnalytics(
    (signal) => fetchCorrelationSummary(activeSub, 500, signal),
    [activeSub],
    { enabled: !!activeSub }
  );

  // ── Shared Videos (table + discussion drill-down) ─────────────────────
  const { data: shared, loading: sharedLoading } = useAnalytics(
    (signal) => fetchSharedVideos(activeSub, 500, signal),
    [activeSub],
    { enabled: !!activeSub }
  );

  // ── Sentiment Comparison (video-aware) ─────────────────────────────────
  // When a video is being analyzed, scope sentiment to that video across ALL
  // subreddits (matching the video-wide KPIs/discussions above) — never
  // silently show subreddit-wide data as video data.
  const sentimentSub = activeVideo ? null : activeSub;
  const { data: sentimentComp, loading: sentLoading } = useAnalytics(
    (signal) => fetchCrossPlatformSentiment(sentimentSub, signal, activeVideo || null),
    [sentimentSub, activeVideo],
    { enabled: !!activeSub || !!activeVideo, cacheKey: `sentiment:${sentimentSub || 'all'}:${activeVideo || 'sub'}` }
  );

  // ── Top YouTube Videos for the subreddit topic ────────────────────────
  const { data: topVideos, loading: topLoading } = useAnalytics(
    (signal) => fetchTopVideos(activeSub, 8, signal),
    [activeSub],
    { enabled: !!activeSub }
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

  // ── Dynamic Effective Sentiment (Video-specific or Subreddit-specific) ──
  // Integrity rule: when activeVideo is set, NEVER fall back to subreddit-wide
  // sentiment. Show video-scoped data (videoEngagement first, then the
  // video-filtered sentiment-comparison), or an explicit empty state.
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
      // Fall back to the video-filtered sentiment-comparison (same video scope).
      if (sentimentComp && hasSamples(sentimentComp)) {
        return { ...sentimentComp, _scope: 'video', _videoId: activeVideo };
      }
      // Explicit empty video scope — do NOT show subreddit data as video data.
      return {
        youtube_sentiment: { positive: 0, neutral: 0, negative: 0, sample_size: 0 },
        reddit_sentiment: { positive: 0, neutral: 0, negative: 0, sample_size: 0 },
        sentiment_gap: 0,
        audience_response_summary: 'No sentiment comments found for this video yet. Try a video with tracked discussions or ingest fresh data.',
        _scope: 'video',
        _videoId: activeVideo,
      };
    }
    return sentimentComp ? { ...sentimentComp, _scope: 'subreddit' } : sentimentComp;
  }, [activeVideo, videoEngagement, sentimentComp]);

  const sentimentScope = effectiveSentiment?._scope || (activeVideo ? 'video' : 'subreddit');
  const isVideoSentiment = sentimentScope === 'video';
  const sentimentLoading = isVideoSentiment
    ? (videoLoading || sentLoading)
    : sentLoading;

  const handleSubSearch = (e) => {
    e.preventDefault();
    if (subQuery.trim()) {
      setActiveSub(subQuery.replace(/^r\//i, '').trim().toLowerCase());
    }
  };

  const handleSubChipClick = (sub) => {
    setSubQuery(sub);
    setActiveSub(sub);
  };

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

  // ── Video engagement data — only populated when user has submitted a video ID ──
  // The shared[] fallback is intentionally removed: showing shared[0] when no
  // video has been entered misleads the user with stale/unrelated DB data.
  const currentVideoData = useMemo(() => {
    if (!activeVideo) return null;          // no input → nothing to show
    if (videoEngagement) return videoEngagement;
    // activeVideo is set but videoEngagement hasn't resolved yet — find it in
    // the already-fetched shared list so the banner is not blank while loading.
    if (shared && shared.length > 0) {
      const match = shared.find(
        (v) => v.youtube_video_id === activeVideo ||
               (v.youtube_url || '').includes(activeVideo)
      );
      if (match) {
        return {
          youtube_video_id: match.youtube_video_id,
          youtube_url: match.youtube_url,
          youtube_title: match.youtube_title,
          youtube_channel_title: match.youtube_channel_title,
          youtube_thumbnail_url: match.youtube_thumbnail_url,
          youtube_views: match.youtube_views,
          youtube_likes: match.youtube_likes,
          youtube_comment_count: match.youtube_comment_count,
          subreddits_count: match.reddit_subreddits?.length || (match.reddit_discussions?.length ? 1 : 0),
          subreddits_list: match.reddit_subreddits || (activeSub ? [activeSub] : []),
          total_reddit_discussions: match.reddit_discussions?.length || match.total_reddit_shares || 0,
          reddit_total_upvotes: match.reddit_total_upvotes || 0,
          propagation_delay_hours: match.propagation_delay_hours,
          propagation_speed: match.propagation_speed,
        };
      }
    }
    return null;
  }, [activeVideo, videoEngagement, shared, activeSub]);

  // ── Computed KPI Values ────────────────────────────────────────────────
  const subredditsDiscussingCount = currentVideoData
    ? currentVideoData.subreddits_count
    : (shared?.length ? 1 : 0);

  const subredditsListText = currentVideoData?.subreddits_list?.length > 0
    ? `r/${currentVideoData.subreddits_list.slice(0, 3).join(', r/')}${currentVideoData.subreddits_list.length > 3 ? ` +${currentVideoData.subreddits_list.length - 3} more` : ''}`
    : `Found in r/${activeSub}`;

  const totalRedditDiscussions = currentVideoData
    ? currentVideoData.total_reddit_discussions
    : (shared
        ? shared.reduce((acc, v) => acc + (v.reddit_discussions?.length || 0), 0)
        : (summaryData?.correlation_summary?.total_discussions_linked || 0));

  const redditDiscussionsSub = currentVideoData?.reddit_total_upvotes
    ? `${fmt(currentVideoData.reddit_total_upvotes)} total upvotes across Reddit`
    : 'Comments citing this video';

  // P2: Separate YouTube Reach (card 3) and Viral Latency (card 4) — always visible
  const hasVideoViews = currentVideoData?.youtube_views != null;

  // Card 3 — YouTube Reach
  const card3Value = hasVideoViews ? fmt(currentVideoData.youtube_views) : '—';
  const card3Sub   = hasVideoViews
    ? `${fmt(currentVideoData.youtube_likes)} likes · ${currentVideoData.propagation_speed || 'Active'}`
    : 'Select a video above to see reach';

  // Card 4 — Viral Latency
  const rawPropHours = currentVideoData?.propagation_delay_hours
    ?? summaryData?.correlation_summary?.avg_propagation_lag_hours;
  const card4Value = rawPropHours != null
    ? `${Number(rawPropHours).toFixed(rawPropHours < 10 ? 1 : 0)} hrs`
    : '—';
  const card4Sub = currentVideoData?.propagation_delay_hours != null
    ? 'YouTube → Reddit for this video'
    : rawPropHours != null
      ? 'Avg across all tracked videos'
      : 'No propagation data yet';

  const availableSubs = subreddits?.length > 0
    ? Array.from(new Set([...subreddits.map(s => s.subreddit_name), ...PRESET_SUBREDDITS]))
    : PRESET_SUBREDDITS;

  // DB subreddits set for live-dot indicator
  const dbSubSet = new Set(subreddits?.map(s => s.subreddit_name) || []);

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

      {/* ── P1: Unified Tabbed Search Control ───────────────────────────── */}
      <div className="glass-card" style={{ padding: 20, border: '1px solid rgba(6,182,212,0.2)' }}>

        {/* Tab bar */}
        <div style={{
          display: 'flex', gap: 4, marginBottom: 18,
          background: 'rgba(255,255,255,0.04)',
          borderRadius: 10, padding: 4,
        }}>
          <button
            onClick={() => setMode('video')}
            style={{
              flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              padding: '9px 16px', borderRadius: 8, border: 'none', cursor: 'pointer',
              fontWeight: 700, fontSize: 13,
              transition: 'all 0.2s ease',
              background: mode === 'video'
                ? 'linear-gradient(135deg, rgba(6,182,212,0.22), rgba(99,102,241,0.18))'
                : 'transparent',
              color: mode === 'video' ? 'var(--cx-primary)' : 'var(--text-muted)',
              boxShadow: mode === 'video' ? '0 2px 14px rgba(6,182,212,0.15)' : 'none',
            }}
          >
            <Video size={14} />
            Analyze a Video
          </button>
          <button
            onClick={() => setMode('subreddit')}
            style={{
              flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
              padding: '9px 16px', borderRadius: 8, border: 'none', cursor: 'pointer',
              fontWeight: 700, fontSize: 13,
              transition: 'all 0.2s ease',
              background: mode === 'subreddit'
                ? 'linear-gradient(135deg, rgba(244,63,94,0.18), rgba(251,146,60,0.12))'
                : 'transparent',
              color: mode === 'subreddit' ? 'var(--rd-primary)' : 'var(--text-muted)',
              boxShadow: mode === 'subreddit' ? '0 2px 14px rgba(244,63,94,0.12)' : 'none',
            }}
          >
            <Search size={14} />
            Explore Subreddits
          </button>
        </div>

        {/* ── Video Analysis Mode ── */}
        {mode === 'video' && (
          <div>
            {/* P2: Two-column layout — form left, hints right (collapses when video active) */}
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

                {/* Recently tracked chips — accurate: session-analyzed + global DB videos */}
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

              {/* P2: Right hint panel — only shown when no active video analysis */}
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

            {/* Active Analyzed Video Detail Banner — only when user has submitted a video ID */}
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
        )}

        {/* ── Subreddit Explore Mode ── */}
        {mode === 'subreddit' && (
          <div>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
              <p style={{ fontSize: 12, color: 'var(--text-muted)' }}>
                Enter a subreddit to discover which YouTube videos its community is sharing and discussing
              </p>
              {activeSub ? (
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 5,
                  padding: '3px 10px', borderRadius: 16,
                  background: 'rgba(244,63,94,0.1)', border: '1px solid rgba(244,63,94,0.25)',
                  fontSize: 11, color: 'var(--rd-primary)', fontWeight: 600,
                }}>
                  <Sparkles size={12} />
                  r/{activeSub}
                </div>
              ) : (
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 5,
                  padding: '3px 10px', borderRadius: 16,
                  background: 'rgba(107,114,128,0.08)', border: '1px solid rgba(107,114,128,0.2)',
                  fontSize: 11, color: 'var(--text-muted)', fontWeight: 600,
                }}>
                  <Search size={12} />
                  No subreddit selected
                </div>
              )}
            </div>

            <form onSubmit={handleSubSearch} style={{ display: 'flex', gap: 10, maxWidth: 420, marginBottom: 12 }}>
              <div style={{ position: 'relative', flex: 1 }}>
                <span style={{ position: 'absolute', left: 12, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)', fontWeight: 600, fontSize: 13 }}>
                  r/
                </span>
                <input
                  type="text"
                  placeholder="gaming, askreddit, technology…"
                  value={subQuery}
                  onChange={(e) => setSubQuery(e.target.value)}
                  style={{
                    width: '100%',
                    background: 'rgba(255,255,255,0.04)',
                    border: '1px solid var(--border-strong)',
                    borderRadius: 8,
                    padding: '9px 12px 9px 30px',
                    color: 'var(--text-primary)',
                    fontSize: 13,
                    outline: 'none',
                  }}
                  onFocus={(e) => e.target.style.borderColor = 'var(--rd-primary)'}
                  onBlur={(e) => e.target.style.borderColor  = 'var(--border-strong)'}
                />
              </div>
              <button
                type="submit"
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  background: 'var(--rd-primary)',
                  color: '#fff', fontWeight: 700, fontSize: 13,
                  padding: '0 18px', borderRadius: 8,
                  border: 'none', cursor: 'pointer',
                }}
              >
                <Search size={14} />
                Scan
              </button>
            </form>

            {/* Subreddit chips with live indicator */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
              {availableSubs.map((sub) => {
                const isActive = activeSub === sub;
                const isLive   = dbSubSet.has(sub);
                return (
                  <button
                    key={sub}
                    onClick={() => handleSubChipClick(sub)}
                    style={{
                      padding: '4px 10px', borderRadius: 14,
                      background: isActive
                        ? 'linear-gradient(135deg, rgba(244,63,94,0.3), rgba(251,146,60,0.2))'
                        : 'rgba(255,255,255,0.05)',
                      border: `1px solid ${isActive ? 'var(--rd-primary)' : 'var(--border)'}`,
                      color: isActive ? 'var(--rd-primary)' : 'var(--text-secondary)',
                      fontSize: 11, fontWeight: 600, cursor: 'pointer',
                      boxShadow: isActive ? '0 0 12px rgba(244,63,94,0.2)' : 'none',
                      transition: 'all 0.15s ease',
                      display: 'flex', alignItems: 'center', gap: 5,
                    }}
                    onMouseEnter={(e) => !isActive && (e.currentTarget.style.borderColor = 'var(--border-strong)')}
                    onMouseLeave={(e) => !isActive && (e.currentTarget.style.borderColor = 'var(--border)')}
                  >
                    {isLive && (
                      <span style={{
                        width: 5, height: 5, borderRadius: '50%',
                        background: isActive ? 'var(--rd-primary)' : '#22c55e',
                        flexShrink: 0,
                      }} />
                    )}
                    r/{sub}
                  </button>
                );
              })}
            </div>

            {/* Empty-state: prompt user to enter a subreddit */}
            {!activeSub && (
              <div style={{
                marginTop: 20,
                padding: '28px 20px',
                borderRadius: 12,
                background: 'rgba(244,63,94,0.04)',
                border: '1px dashed rgba(244,63,94,0.2)',
                textAlign: 'center',
              }}>
                <Search size={28} color="rgba(244,63,94,0.4)" style={{ marginBottom: 10 }} />
                <p style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 6 }}>
                  Enter a subreddit to begin
                </p>
                <p style={{ fontSize: 12, color: 'var(--text-muted)', maxWidth: 380, margin: '0 auto' }}>
                  Type a subreddit name above and click <strong>Scan</strong>, or pick one of the quick-select chips to discover which YouTube videos its community is sharing.
                </p>
              </div>
            )}
          </div>
        )}
      </div>

      {/* ── P2: 4-card KPI Grid — only in Analyze a Video mode ── */}
      {mode === 'video' && (
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
            title="Reddit Discussions"
            value={activeVideo ? totalRedditDiscussions : '—'}
            sub={activeVideo ? redditDiscussionsSub : 'Enter a video ID or URL above'}
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
            title="Viral Latency"
            value={activeVideo ? card4Value : '—'}
            sub={activeVideo ? card4Sub : 'Enter a video ID or URL above'}
            icon={Zap}
            accent="#a78bfa"
            loading={videoLoading || summaryLoading}
          />
        </div>
      )}

      {/* ── Active Video Live Discussions Across All of Reddit — only in Analyze a Video mode ── */}
      {/* ── Active Video Live Discussions Across All of Reddit — only in Analyze a Video mode ── */}
      {mode === 'video' && activeVideo && videoLoading && (
        <div className="skeleton" style={{ height: 220, borderRadius: 12 }} />
      )}

      {mode === 'video' && activeVideo && !videoLoading && videoEngagement && (
        videoEngagement.discussions?.length > 0 ? (
          <div className="glass-card" style={{ padding: 20, border: '1px solid rgba(6,182,212,0.25)' }}>
            <div style={{ marginBottom: 14 }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <MessageSquare size={16} color="var(--rd-primary)" />
                <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
                  Reddit Discussions Found Across All Subreddits ({videoEngagement.discussions.length})
                </h3>
              </div>
              <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
                Discussions and comments referencing this video across communities:{' '}
                <strong style={{ color: 'var(--cx-primary)' }}>
                  {videoEngagement.subreddits_list?.map(s => `r/${s}`).join(', ') || 'Various Subreddits'}
                </strong>
              </p>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10, maxHeight: 380, overflowY: 'auto' }}>
              {videoEngagement.discussions.map((d, i) => (
                <div
                  key={d.discussion_id || i}
                  style={{
                    padding: 12, borderRadius: 8,
                    background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border)',
                    display: 'flex', flexDirection: 'column', gap: 6,
                  }}
                >
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 6 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12 }}>
                      <span style={{ padding: '2px 7px', borderRadius: 4, background: 'rgba(244,63,94,0.15)', color: 'var(--rd-primary)', fontWeight: 700, fontSize: 11 }}>
                        r/{d.subreddit}
                      </span>
                      <span style={{ color: 'var(--text-secondary)', fontWeight: 600 }}>u/{d.author}</span>
                      <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>▲ {d.score} upvotes</span>
                      {d.match_type && (
                        <span style={{
                          padding: '1px 6px', borderRadius: 4, fontSize: 10, fontWeight: 700,
                          background: d.match_type === 'url' ? 'rgba(34,197,94,0.12)' : 'rgba(99,102,241,0.12)',
                          color: d.match_type === 'url' ? '#22c55e' : 'var(--cx-primary)',
                          border: `1px solid ${d.match_type === 'url' ? 'rgba(34,197,94,0.25)' : 'rgba(99,102,241,0.25)'}`,
                        }}>
                          {d.match_type === 'url' ? 'Direct Link' : 'Topic Debate'}
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
                        style={{ color: 'var(--cx-primary)', fontSize: 11, display: 'inline-flex', alignItems: 'center', gap: 4 }}
                      >
                        View on Reddit <ExternalLink size={11} />
                      </a>
                    )}
                  </div>
                  <p style={{ fontSize: 12, color: 'var(--text-primary)', lineHeight: 1.5, margin: 0 }}>
                    {d.body}
                  </p>
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

      {/* ── Shared Videos Table — only in Explore Subreddits mode ────── */}
      {mode === 'subreddit' && (
        <div className="glass-card" style={{ padding: 20 }}>
          <div style={{ marginBottom: 14 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', borderLeft: '3px solid var(--rd-primary)', paddingLeft: 10 }}>
              YouTube Videos Shared in r/{activeSub || '…'}
            </h3>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
              Click the discussion button on any row to see the Reddit comments that linked the video.
            </p>
          </div>
          <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
            <SharedVideosTable
              videos={shared}
              loading={sharedLoading}
              showTopBadge={false}
            />
          </div>
        </div>
      )}

      {/* ── Sentiment Comparison — only in Analyze a Video mode ─────────── */}
      {mode === 'video' && (
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
      )}

      {/* ── Top YouTube Videos for Topic — only in Explore Subreddits mode ── */}
      {mode === 'subreddit' && (
        <div className="glass-card" style={{ padding: 20 }}>
          <div style={{ marginBottom: 14 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <TrendingUp size={18} color="var(--cx-primary)" />
              <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', borderLeft: '3px solid var(--cx-primary)', paddingLeft: 10 }}>
                Top YouTube Videos for "{activeSub || '…'}"
              </h3>
            </div>
            <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
              Most viewed YouTube videos related to this subreddit topic, fetched live from YouTube.
            </p>
          </div>
          <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
            <SharedVideosTable
              videos={topVideos}
              loading={topLoading}
              showTopBadge={true}
            />
          </div>
        </div>
      )}

    </div>
  );
}
