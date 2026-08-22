import { useState, useMemo } from 'react';
import {
  Search, Link as LinkIcon,
  Clock, Scale, MessageSquare, Sparkles, TrendingUp,
  Video, Layers, Eye, ThumbsUp, ExternalLink, Share2, X, CheckCircle2,
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

function fmt(n) {
  if (n == null || n === 0) return '0';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

export default function CrossPlatformView() {
  const [subQuery, setSubQuery]     = useState('gaming');
  const [activeSub, setActiveSub]   = useState('gaming');

  // ── YouTube Video search / selection state ────────────────────────────
  const [videoQuery, setVideoQuery] = useState('');
  const [activeVideo, setActiveVideo] = useState('');

  // ── Tracked subreddits for quick-select chips ─────────────────────────
  const { data: subreddits } = useAnalytics(
    (signal) => fetchRedditSubreddits(signal),
    []
  );

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

  // ── Sentiment Comparison ──────────────────────────────────────────────
  const { data: sentimentComp, loading: sentLoading } = useAnalytics(
    (signal) => fetchCrossPlatformSentiment(activeSub, signal),
    [activeSub],
    { enabled: !!activeSub }
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

  // ── Dynamic Effective Sentiment (Video-specific or Subreddit-specific) ──
  const effectiveSentiment = useMemo(() => {
    if (activeVideo && videoEngagement && (videoEngagement.youtube_sentiment || videoEngagement.reddit_sentiment)) {
      const yt = videoEngagement.youtube_sentiment || { positive: 0, neutral: 0, negative: 0, sample_size: 0 };
      const rd = videoEngagement.reddit_sentiment || { positive: 0, neutral: 0, negative: 0, sample_size: 0 };
      const gap = Number(((yt.positive || 0) - (rd.positive || 0)).toFixed(3));
      return {
        youtube_sentiment: yt,
        reddit_sentiment: rd,
        sentiment_gap: gap,
        audience_response_summary: videoEngagement.sentiment_disparity_note || (
          gap > 0.1
            ? `YouTube reception is notably more positive (${Math.round((yt.positive || 0) * 100)}%) than Reddit community discussion (${Math.round((rd.positive || 0) * 100)}%).`
            : gap < -0.1
            ? `Reddit discussion is more positive (${Math.round((rd.positive || 0) * 100)}%) than YouTube audience.`
            : `Audience response is closely aligned between YouTube and Reddit community discussions.`
        ),
      };
    }
    return sentimentComp;
  }, [activeVideo, videoEngagement, sentimentComp]);

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

  // ── Video engagement fallback from active video or first shared video ──
  const currentVideoData = useMemo(() => {
    if (videoEngagement) return videoEngagement;
    if (shared && shared.length > 0) {
      const top = shared[0];
      return {
        youtube_video_id: top.youtube_video_id,
        youtube_url: top.youtube_url,
        youtube_title: top.youtube_title,
        youtube_channel_title: top.youtube_channel_title,
        youtube_thumbnail_url: top.youtube_thumbnail_url,
        youtube_views: top.youtube_views,
        youtube_likes: top.youtube_likes,
        youtube_comment_count: top.youtube_comment_count,
        subreddits_count: top.reddit_subreddits?.length || (top.reddit_discussions?.length ? 1 : 0),
        subreddits_list: top.reddit_subreddits || (activeSub ? [activeSub] : []),
        total_reddit_discussions: top.reddit_discussions?.length || top.total_reddit_shares || 0,
        reddit_total_upvotes: top.reddit_total_upvotes || 0,
        propagation_delay_hours: top.propagation_delay_hours,
        propagation_speed: top.propagation_speed,
      };
    }
    return null;
  }, [videoEngagement, shared, activeSub]);

  // ── Computed KPI Values ────────────────────────────────────────────────
  // 1. Subreddits Discussing count (how many subreddits our video is discussed in)
  const subredditsDiscussingCount = currentVideoData
    ? currentVideoData.subreddits_count
    : (shared?.length ? 1 : 0);

  const subredditsListText = currentVideoData?.subreddits_list?.length > 0
    ? `r/${currentVideoData.subreddits_list.slice(0, 3).join(', r/')}${currentVideoData.subreddits_list.length > 3 ? ` +${currentVideoData.subreddits_list.length - 3} more` : ''}`
    : `Found in r/${activeSub}`;

  // 2. Reddit Discussions citing the video
  const totalRedditDiscussions = currentVideoData
    ? currentVideoData.total_reddit_discussions
    : (shared
        ? shared.reduce((acc, v) => acc + (v.reddit_discussions?.length || 0), 0)
        : (summaryData?.correlation_summary?.total_discussions_linked || 0));

  const redditDiscussionsSub = currentVideoData?.reddit_total_upvotes
    ? `${fmt(currentVideoData.reddit_total_upvotes)} total upvotes across Reddit`
    : 'Comments citing this video';

  // 3. Video Views & Likes (Engagement of that video)
  const videoViewsValue = currentVideoData?.youtube_views != null
    ? fmt(currentVideoData.youtube_views)
    : (summaryData?.correlation_summary?.avg_propagation_lag_hours
        ? `${summaryData.correlation_summary.avg_propagation_lag_hours.toFixed(1)} hrs`
        : '< 6 hrs');

  const videoEngagementSub = currentVideoData?.youtube_likes != null
    ? `${fmt(currentVideoData.youtube_likes)} likes • ${currentVideoData.propagation_speed || 'Active'}`
    : 'YouTube video engagement';

  const availableSubs = subreddits?.length > 0
    ? Array.from(new Set([...subreddits.map(s => s.subreddit_name), ...PRESET_SUBREDDITS]))
    : PRESET_SUBREDDITS;

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

      {/* ── YouTube Video Input & Analyzer Bar ──────────────────────────── */}
      <div className="glass-card" style={{ padding: 20, border: '1px solid rgba(6,182,212,0.25)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <Video size={16} color="var(--cx-primary)" />
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
              Analyze a YouTube Video across Reddit
            </h3>
          </div>
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
              <X size={12} /> Clear video filter
            </button>
          )}
        </div>

        <form onSubmit={handleVideoSearch} style={{ display: 'flex', gap: 10, maxWidth: 640, marginBottom: 12 }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <input
              type="text"
              placeholder="Paste YouTube video URL or ID (e.g. https://youtu.be/dQw4w9WgXcQ or dQw4w9WgXcQ)…"
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
              onBlur={(e) => e.target.style.borderColor = 'var(--border-strong)'}
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

        {/* Quick select video suggestions from current subreddit / shared videos */}
        {shared && shared.length > 0 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', fontSize: 11 }}>
            <span style={{ color: 'var(--text-muted)', fontWeight: 600 }}>Detected in DB:</span>
            {shared.slice(0, 3).map((v) => (
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

        {/* Active Analyzed Video Detail Banner */}
        {currentVideoData && (
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
                  style={{ width: 64, height: 38, borderRadius: 6, objectFit: 'cover', flexShrink: 0 }}
                />
              )}
              <div style={{ minWidth: 0 }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
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
                </div>
                <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2, display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                  {currentVideoData.youtube_channel_title && (
                    <span>By <strong>{currentVideoData.youtube_channel_title}</strong></span>
                  )}
                  <span>• {fmt(currentVideoData.youtube_views)} views</span>
                  <span>• {fmt(currentVideoData.youtube_likes)} likes</span>
                  {currentVideoData.subreddits_list?.length > 0 && (
                    <span>• Discussed in: <strong style={{ color: 'var(--cx-primary)' }}>r/{currentVideoData.subreddits_list.join(', r/')}</strong></span>
                  )}
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── Updated KPI Cards ───────────────────────────────────────────── */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 16 }}>
        <StatCard
          title="Subreddits Discussing"
          value={subredditsDiscussingCount}
          sub={subredditsListText}
          icon={Layers}
          accent="var(--cx-primary)"
          loading={sharedLoading || videoLoading}
        />
        <StatCard
          title="Reddit Discussions"
          value={totalRedditDiscussions}
          sub={redditDiscussionsSub}
          icon={MessageSquare}
          accent="var(--rd-primary)"
          loading={sharedLoading || videoLoading}
        />
        <StatCard
          title="Video Views & Likes"
          value={videoViewsValue}
          sub={videoEngagementSub}
          icon={Eye}
          accent="#f59e0b"
          loading={sharedLoading || videoLoading || summaryLoading}
        />
      </div>

      {/* ── Active Video Live Discussions Across All of Reddit ── */}
      {activeVideo && videoEngagement && videoEngagement.discussions?.length > 0 && (
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
                {videoEngagement.subreddits_list.map(s => `r/${s}`).join(', ')}
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
                      href={d.permalink}
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
      )}

      {/* ── Subreddit Scanner ───────────────────────────────────────────── */}
      <div className="glass-card" style={{ padding: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12, flexWrap: 'wrap', gap: 8 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
            Scan a Subreddit
          </h3>
          <div style={{
            display: 'flex', alignItems: 'center', gap: 5,
            padding: '3px 10px', borderRadius: 16,
            background: 'rgba(6,182,212,0.1)', border: '1px solid rgba(6,182,212,0.25)',
            fontSize: 11, color: 'var(--cx-primary)', fontWeight: 600,
          }}>
            <Sparkles size={12} />
            r/{activeSub}
          </div>
        </div>

        <form onSubmit={handleSubSearch} style={{ display: 'flex', gap: 10, maxWidth: 420, marginBottom: 10 }}>
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
              onFocus={(e) => e.target.style.borderColor = 'var(--cx-primary)'}
              onBlur={(e) => e.target.style.borderColor = 'var(--border-strong)'}
            />
          </div>
          <button
            type="submit"
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              background: 'var(--cx-primary)',
              color: '#000', fontWeight: 700, fontSize: 13,
              padding: '0 18px', borderRadius: 8,
              border: 'none', cursor: 'pointer',
            }}
          >
            <Search size={14} />
            Scan
          </button>
        </form>

        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
          {availableSubs.map((sub) => (
            <button
              key={sub}
              onClick={() => handleSubChipClick(sub)}
              style={{
                padding: '3px 10px', borderRadius: 14,
                background: activeSub === sub ? 'rgba(6,182,212,0.25)' : 'rgba(255,255,255,0.05)',
                border: `1px solid ${activeSub === sub ? 'var(--cx-primary)' : 'var(--border)'}`,
                color: activeSub === sub ? 'var(--cx-primary)' : 'var(--text-secondary)',
                fontSize: 11, fontWeight: 600, cursor: 'pointer',
              }}
            >
              r/{sub}
            </button>
          ))}
        </div>
      </div>

      {/* ── Shared Videos Table (with expandable discussion drawer) ────── */}
      <div className="glass-card" style={{ padding: 20 }}>
        <div style={{ marginBottom: 14 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
            YouTube Videos Shared in r/{activeSub}
          </h3>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
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

      {/* ── Sentiment Comparison ─────────────────────────────────────────── */}
      <div className="glass-card" style={{ padding: 20 }}>
        <div style={{ marginBottom: 14 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
            Audience Sentiment: YouTube vs Reddit
          </h3>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
            How audience reaction on YouTube differs from the Reddit discussion for the same content.
          </p>
        </div>
        <CrossSentimentChart data={effectiveSentiment} loading={sentLoading || (Boolean(activeVideo) && videoLoading)} />
      </div>

      {/* ── Top YouTube Videos for Topic ──────────────────────────────────── */}
      <div className="glass-card" style={{ padding: 20 }}>
        <div style={{ marginBottom: 14 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <TrendingUp size={18} color="var(--cx-primary)" />
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)' }}>
              Top YouTube Videos for "{activeSub}"
            </h3>
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-muted)', marginTop: 2 }}>
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

    </div>
  );
}

