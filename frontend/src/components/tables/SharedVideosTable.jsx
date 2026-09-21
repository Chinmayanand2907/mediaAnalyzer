import React, { useState, useMemo } from 'react';
import {
  ExternalLink, Eye, ThumbsUp, MessageSquare, Star,
  Clock, ChevronDown, ChevronUp, Layers, User, Calendar, Tag, Sparkles,
  ArrowUpDown, Filter, Search as SearchIcon, X,
} from 'lucide-react';

function fmt(n) {
  if (n == null) return '—';
  if (n === 0) return '0';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

export function normalizeRedditUrl(permalink) {
  if (!permalink) return null;
  if (/^https?:\/\//i.test(permalink)) return permalink;
  return `https://reddit.com${permalink.startsWith('/') ? '' : '/'}${permalink}`;
}

function formatDate(isoStr) {
  if (!isoStr) return null;
  const d = new Date(isoStr);
  if (Number.isNaN(d.getTime())) return null;
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

function SentimentPill({ sentiment, platform = 'yt' }) {
  if (!sentiment) return <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>;
  const label = sentiment.dominant_label || 'neutral';
  const pos = Number(sentiment.positive);
  const neg = Number(sentiment.negative);
  const posPct = Number.isFinite(pos) ? (pos * 100).toFixed(0) : '—';
  const negPct = Number.isFinite(neg) ? (neg * 100).toFixed(0) : '—';

  const colors = {
    positive: { bg: 'rgba(34, 197, 94, 0.15)', text: 'var(--positive)', border: 'rgba(34, 197, 94, 0.3)' },
    neutral:  { bg: 'rgba(245, 158, 11, 0.15)', text: 'var(--neutral)', border: 'rgba(245, 158, 11, 0.3)' },
    negative: { bg: 'rgba(239, 68, 68, 0.15)', text: 'var(--negative)', border: 'rgba(239, 68, 68, 0.3)' },
  };
  const c = colors[label] || colors.neutral;

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        padding: '2px 8px',
        borderRadius: 12,
        background: c.bg,
        border: `1px solid ${c.border}`,
        color: c.text,
        fontSize: 11,
        fontWeight: 700,
        whiteSpace: 'nowrap',
      }}
      title={`${posPct}% Positive, ${negPct}% Negative`}
    >
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: c.text }} />
      {posPct}% Pos
    </span>
  );
}

// ── Sort options ──────────────────────────────────────────────────────────────
const SORT_OPTIONS = [
  { value: 'reddit_shares',  label: 'Most Reddit Shares' },
  { value: 'views',          label: 'Most YouTube Views' },
  { value: 'propagation',    label: 'Fastest Propagation' },
  { value: 'sentiment_diff', label: 'Highest Sentiment Contrast' },
];

function sortVideos(videos, sortBy, dir) {
  return [...videos].sort((a, b) => {
    let aVal, bVal;
    switch (sortBy) {
      case 'reddit_shares':
        aVal = a.total_reddit_shares || a.reddit_discussions?.length || 0;
        bVal = b.total_reddit_shares || b.reddit_discussions?.length || 0;
        break;
      case 'views':
        aVal = a.youtube_views || 0;
        bVal = b.youtube_views || 0;
        break;
      case 'propagation':
        // Fastest = smallest hours (ascending by default)
        aVal = a.propagation_delay_hours ?? 9999;
        bVal = b.propagation_delay_hours ?? 9999;
        return dir === 'asc' ? aVal - bVal : bVal - aVal;
      case 'sentiment_diff': {
        const ytA = a.youtube_sentiment?.positive || 0;
        const rdA = a.reddit_sentiment?.positive  || 0;
        const ytB = b.youtube_sentiment?.positive || 0;
        const rdB = b.reddit_sentiment?.positive  || 0;
        aVal = Math.abs(ytA - rdA);
        bVal = Math.abs(ytB - rdB);
        break;
      }
      default:
        aVal = 0; bVal = 0;
    }
    return dir === 'desc' ? bVal - aVal : aVal - bVal;
  });
}

export default function SharedVideosTable({ videos, loading, showTopBadge = false }) {
  const [expandedId,    setExpandedId]    = useState(null);
  // P3: Sort / filter state
  const [sortBy,        setSortBy]        = useState('reddit_shares');
  const [sortDir,       setSortDir]       = useState('desc');
  const [filterSemantic,setFilterSemantic]= useState(false);
  const [filterQuery,   setFilterQuery]   = useState('');

  const toggleExpand = (vidId) => {
    setExpandedId(prev => (prev === vidId ? null : vidId));
  };

  const toggleSort = (field) => {
    if (sortBy === field) {
      setSortDir(d => d === 'desc' ? 'asc' : 'desc');
    } else {
      setSortBy(field);
      setSortDir(field === 'propagation' ? 'asc' : 'desc');
    }
  };

  // ── Processed (filtered + sorted) videos ─────────────────────────────────
  const processedVideos = useMemo(() => {
    if (!videos) return [];
    let result = [...videos];

    // Filter: semantic/hybrid matches only
    if (filterSemantic) {
      result = result.filter(v => v.match_type === 'semantic' || v.match_type === 'hybrid');
    }

    // Filter: title search
    if (filterQuery.trim()) {
      const q = filterQuery.toLowerCase();
      result = result.filter(v =>
        (v.youtube_title || '').toLowerCase().includes(q) ||
        (v.youtube_channel_title || '').toLowerCase().includes(q)
      );
    }

    // Sort (skip for showTopBadge — server order is rank order)
    if (!showTopBadge) {
      result = sortVideos(result, sortBy, sortDir);
    }

    return result;
  }, [videos, sortBy, sortDir, filterSemantic, filterQuery, showTopBadge]);

  if (loading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 12, padding: 16 }}>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} style={{ display: 'flex', gap: 12, alignItems: 'center' }}>
            <div className="skeleton" style={{ width: 120, height: 68, borderRadius: 8, flexShrink: 0 }} />
            <div style={{ flex: 1, display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div className="skeleton" style={{ height: 13, width: '70%' }} />
              <div className="skeleton" style={{ height: 11, width: '40%' }} />
              <div className="skeleton" style={{ height: 11, width: '55%' }} />
            </div>
          </div>
        ))}
      </div>
    );
  }

  if (!videos?.length) {
    return (
      <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
        No linked YouTube videos found in this subreddit scan. Try another subreddit (e.g. <code>gaming</code> or <code>askreddit</code>).
      </div>
    );
  }

  return (
    <div>
      {/* P3: Sort & Filter Control Bar */}
      {!showTopBadge && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
          padding: '10px 14px',
          borderBottom: '1px solid var(--border)',
          background: 'rgba(255,255,255,0.015)',
        }}>
          {/* Sort dropdown */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexShrink: 0 }}>
            <ArrowUpDown size={13} color="var(--text-muted)" />
            <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600 }}>Sort:</span>
            <select
              value={sortBy}
              onChange={(e) => { setSortBy(e.target.value); setSortDir(e.target.value === 'propagation' ? 'asc' : 'desc'); }}
              style={{
                appearance: 'none',
                background: 'rgba(255,255,255,0.06)',
                border: '1px solid var(--border-strong)',
                borderRadius: 6,
                color: 'var(--text-primary)',
                fontSize: 12,
                fontWeight: 600,
                padding: '4px 28px 4px 9px',
                cursor: 'pointer',
                outline: 'none',
                backgroundImage: `url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='10' height='6' fill='none'%3E%3Cpath d='M1 1l4 4 4-4' stroke='%2394a3b8' stroke-width='1.5' stroke-linecap='round'/%3E%3C/svg%3E")`,
                backgroundRepeat: 'no-repeat',
                backgroundPosition: 'right 8px center',
              }}
            >
              {SORT_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
            {/* Asc/Desc toggle */}
            <button
              onClick={() => setSortDir(d => d === 'desc' ? 'asc' : 'desc')}
              title={sortDir === 'desc' ? 'Descending — click for ascending' : 'Ascending — click for descending'}
              style={{
                display: 'flex', alignItems: 'center', gap: 3,
                padding: '4px 8px', borderRadius: 6,
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid var(--border)',
                color: 'var(--text-secondary)',
                fontSize: 11, fontWeight: 600, cursor: 'pointer',
              }}
            >
              {sortDir === 'desc' ? <ChevronDown size={12} /> : <ChevronUp size={12} />}
              {sortDir === 'desc' ? 'Desc' : 'Asc'}
            </button>
          </div>

          {/* Divider */}
          <div style={{ width: 1, height: 18, background: 'var(--border)', flexShrink: 0 }} />

          {/* Semantic filter toggle */}
          <button
            onClick={() => setFilterSemantic(f => !f)}
            style={{
              display: 'flex', alignItems: 'center', gap: 5,
              padding: '4px 10px', borderRadius: 6,
              background: filterSemantic ? 'rgba(192,132,252,0.18)' : 'rgba(255,255,255,0.04)',
              border: `1px solid ${filterSemantic ? 'rgba(192,132,252,0.45)' : 'var(--border)'}`,
              color: filterSemantic ? '#c084fc' : 'var(--text-muted)',
              fontSize: 11, fontWeight: 700, cursor: 'pointer',
              transition: 'all 0.15s ease',
            }}
          >
            <Sparkles size={11} />
            Semantic Only
          </button>

          {/* Title search */}
          <div style={{ position: 'relative', flex: 1, minWidth: 140 }}>
            <SearchIcon size={12} color="var(--text-muted)" style={{ position: 'absolute', left: 9, top: '50%', transform: 'translateY(-50%)', pointerEvents: 'none' }} />
            <input
              type="text"
              placeholder="Filter by title or channel…"
              value={filterQuery}
              onChange={(e) => setFilterQuery(e.target.value)}
              style={{
                width: '100%',
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid var(--border-strong)',
                borderRadius: 6,
                padding: '5px 28px 5px 28px',
                color: 'var(--text-primary)',
                fontSize: 12,
                outline: 'none',
              }}
              onFocus={(e) => e.target.style.borderColor = 'var(--cx-primary)'}
              onBlur={(e) => e.target.style.borderColor = 'var(--border-strong)'}
            />
            {filterQuery && (
              <button
                onClick={() => setFilterQuery('')}
                style={{ position: 'absolute', right: 7, top: '50%', transform: 'translateY(-50%)', background: 'none', border: 'none', cursor: 'pointer', color: 'var(--text-muted)', display: 'flex' }}
              >
                <X size={12} />
              </button>
            )}
          </div>

          {/* Result count badge */}
          <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 600, flexShrink: 0 }}>
            {processedVideos.length} of {videos.length}
          </span>
        </div>
      )}

      {/* No results after filter */}
      {processedVideos.length === 0 && (
        <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
          No videos match the current filters.{' '}
          <button
            onClick={() => { setFilterQuery(''); setFilterSemantic(false); }}
            style={{ background: 'none', border: 'none', color: 'var(--cx-primary)', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}
          >
            Clear filters
          </button>
        </div>
      )}

      <div style={{ overflowX: 'auto' }}>
        <table className="dash-table" style={{ width: '100%', minWidth: 800 }}>
          <thead>
            <tr>
              <th style={{ width: '38%' }}>YouTube Video</th>
              <th
                style={{ textAlign: 'right', width: '10%', cursor: !showTopBadge ? 'pointer' : 'default' }}
                onClick={() => !showTopBadge && toggleSort('views')}
                title="Sort by views"
              >
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}>
                  <Eye size={12} /> Views
                  {!showTopBadge && sortBy === 'views' && (sortDir === 'desc' ? <ChevronDown size={11} /> : <ChevronUp size={11} />)}
                </span>
              </th>
              <th style={{ textAlign: 'right', width: '9%' }}>
                <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}>
                  <ThumbsUp size={12} /> Likes
                </span>
              </th>
              <th style={{ textAlign: 'center', width: '11%' }}>YT Sentiment</th>
              {!showTopBadge && (
                <>
                  <th style={{ textAlign: 'center', width: '11%' }}>Reddit Sentiment</th>
                  <th
                    style={{ textAlign: 'center', width: '11%', cursor: 'pointer' }}
                    onClick={() => toggleSort('propagation')}
                    title="Sort by propagation speed"
                  >
                    <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 4 }}>
                      Propagation
                      {sortBy === 'propagation' && (sortDir === 'asc' ? <ChevronUp size={11} /> : <ChevronDown size={11} />)}
                    </span>
                  </th>
                  <th
                    style={{ textAlign: 'right', width: '10%', cursor: 'pointer' }}
                    onClick={() => toggleSort('reddit_shares')}
                    title="Sort by Reddit shares"
                  >
                    <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}>
                      Discussions
                      {sortBy === 'reddit_shares' && (sortDir === 'desc' ? <ChevronDown size={11} /> : <ChevronUp size={11} />)}
                    </span>
                  </th>
                </>
              )}
            </tr>
          </thead>
          <tbody>
            {processedVideos.map((v, idx) => {
              const isExpanded = expandedId === v.youtube_video_id;
              const discussions = v.reddit_discussions || [];
              const pubDate = formatDate(v.youtube_published_at);

              return (
                <React.Fragment key={v.youtube_video_id}>
                  <tr style={{ verticalAlign: 'middle' }}>
                    {/* ── Video Card Cell ── */}
                    <td>
                      <div style={{ display: 'flex', alignItems: 'flex-start', gap: 12 }}>
                        {/* Thumbnail */}
                        <a
                          href={v.youtube_url}
                          target="_blank"
                          rel="noopener noreferrer"
                          style={{ flexShrink: 0, position: 'relative', display: 'block' }}
                        >
                          {v.youtube_thumbnail_url ? (
                            <img
                              src={v.youtube_thumbnail_url}
                              alt={v.youtube_title || v.youtube_video_id}
                              style={{
                                width: 110,
                                height: 62,
                                objectFit: 'cover',
                                borderRadius: 6,
                                border: '1px solid var(--border)',
                                display: 'block',
                              }}
                              onError={(e) => { e.target.style.display = 'none'; }}
                            />
                          ) : (
                            <div style={{
                              width: 110, height: 62, borderRadius: 6,
                              background: 'rgba(255,255,255,0.04)',
                              border: '1px solid var(--border)',
                              display: 'flex', alignItems: 'center', justifyContent: 'center',
                            }}>
                              <svg width="24" height="24" viewBox="0 0 24 24" fill="none">
                                <path d="M19.615 3.184c-3.604-.246-11.631-.245-15.23 0-3.897.266-4.356 2.62-4.385 8.816.029 6.185.484 8.549 4.385 8.816 3.6.245 11.626.246 15.23 0 3.897-.266 4.356-2.62 4.385-8.816-.029-6.185-.484-8.549-4.385-8.816zm-10.615 12.816v-8l8 3.993-8 4.007z" fill="rgba(255,255,255,0.2)"/>
                              </svg>
                            </div>
                          )}
                          {showTopBadge && idx < 3 && (
                            <div style={{
                              position: 'absolute', top: 4, left: 4,
                              background: idx === 0 ? '#f59e0b' : idx === 1 ? '#94a3b8' : '#b45309',
                              borderRadius: 4, padding: '1px 5px',
                              fontSize: 10, fontWeight: 800, color: '#000',
                            }}>
                              #{idx + 1}
                            </div>
                          )}
                        </a>

                        {/* Title + Channel + Topics */}
                        <div style={{ flex: 1, minWidth: 0 }}>
                          <a
                            href={v.youtube_url}
                            target="_blank"
                            rel="noopener noreferrer"
                            style={{
                              color: 'var(--text-primary)',
                              fontWeight: 600,
                              fontSize: 13,
                              lineHeight: 1.35,
                              textDecoration: 'none',
                              overflow: 'hidden',
                              display: '-webkit-box',
                              WebkitLineClamp: 2,
                              WebkitBoxOrient: 'vertical',
                              marginBottom: 4,
                            }}
                            onMouseEnter={(e) => e.target.style.color = 'var(--yt-primary)'}
                            onMouseLeave={(e) => e.target.style.color = 'var(--text-primary)'}
                          >
                            {v.youtube_title || (
                              <span style={{ fontFamily: 'monospace', fontSize: 12 }}>
                                {v.youtube_video_id}
                              </span>
                            )}
                          </a>

                          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', marginBottom: 4 }}>
                            {v.youtube_channel_title && (
                              <span style={{ fontSize: 11, color: 'var(--text-secondary)', fontWeight: 500 }}>
                                {v.youtube_channel_title}
                              </span>
                            )}
                            {pubDate && (
                              <span style={{ fontSize: 11, color: 'var(--text-muted)', display: 'flex', alignItems: 'center', gap: 3 }}>
                                <Calendar size={11} /> {pubDate}
                              </span>
                            )}
                            {v.match_type === 'semantic' && (
                              <span
                                style={{
                                  display: 'inline-flex', alignItems: 'center', gap: 3,
                                  fontSize: 10, fontWeight: 700, color: '#c084fc',
                                  background: 'rgba(192, 132, 252, 0.12)',
                                  border: '1px solid rgba(192, 132, 252, 0.3)',
                                  padding: '1px 6px', borderRadius: 4,
                                }}
                                title={v.similarity_score ? `Semantic Similarity: ${Math.round(v.similarity_score * 100)}%` : 'Semantic Match'}
                              >
                                <Sparkles size={10} /> Semantic {v.similarity_score ? `${Math.round(v.similarity_score * 100)}%` : ''}
                              </span>
                            )}
                            {v.match_type === 'hybrid' && (
                              <span
                                style={{
                                  display: 'inline-flex', alignItems: 'center', gap: 3,
                                  fontSize: 10, fontWeight: 700, color: '#38bdf8',
                                  background: 'rgba(56, 189, 248, 0.12)',
                                  border: '1px solid rgba(56, 189, 248, 0.3)',
                                  padding: '1px 6px', borderRadius: 4,
                                }}
                                title="Matched via both Direct URL and Semantic Content"
                              >
                                <Sparkles size={10} /> Hybrid
                              </span>
                            )}
                          </div>

                          {/* Topic Tags */}
                          {v.topics?.length > 0 && (
                            <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 2 }}>
                              {v.topics.slice(0, 3).map((t, i) => (
                                <span
                                  key={i}
                                  style={{
                                    fontSize: 10, color: 'var(--text-muted)',
                                    background: 'rgba(255,255,255,0.04)',
                                    padding: '1px 6px', borderRadius: 4,
                                  }}
                                >
                                  #{t}
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                    </td>

                    {/* ── YT Views ── */}
                    <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: 13, color: 'var(--text-secondary)' }}>
                      {fmt(v.youtube_views)}
                    </td>

                    {/* ── YT Likes ── */}
                    <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: 13, color: 'var(--text-secondary)' }}>
                      {fmt(v.youtube_likes)}
                    </td>

                    {/* ── YT Sentiment ── */}
                    <td style={{ textAlign: 'center' }}>
                      <SentimentPill sentiment={v.youtube_sentiment} platform="yt" />
                    </td>

                    {/* ── Reddit Sentiment ── */}
                    {!showTopBadge && (
                      <td style={{ textAlign: 'center' }}>
                        <SentimentPill sentiment={v.reddit_sentiment} platform="rd" />
                      </td>
                    )}

                    {/* ── Propagation Lag ── */}
                    {!showTopBadge && (
                      <td style={{ textAlign: 'center' }}>
                        {v.propagation_delay_hours != null ? (
                          <span
                            style={{
                              display: 'inline-flex', alignItems: 'center', gap: 4,
                              padding: '2px 8px', borderRadius: 10,
                              background: v.propagation_delay_hours <= 6 ? 'rgba(34, 197, 94, 0.12)' : 'rgba(6, 182, 212, 0.12)',
                              color: v.propagation_delay_hours <= 6 ? 'var(--positive)' : 'var(--cx-primary)',
                              fontSize: 11, fontWeight: 700,
                            }}
                            title={`Published on YouTube, shared to Reddit in ${v.propagation_delay_hours} hours`}
                          >
                            <Clock size={11} />
                            {v.propagation_delay_hours <= 0 ? 'Same-Day' : `${v.propagation_delay_hours}h`}
                          </span>
                        ) : (
                          <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>
                            {v.propagation_speed || 'Community Share'}
                          </span>
                        )}
                      </td>
                    )}

                    {/* ── Discussions Toggle Button ── */}
                    {!showTopBadge && (
                      <td style={{ textAlign: 'right' }}>
                        <button
                          onClick={() => toggleExpand(v.youtube_video_id)}
                          style={{
                            display: 'inline-flex', alignItems: 'center', gap: 6,
                            padding: '6px 12px', borderRadius: 8,
                            background: isExpanded ? 'rgba(6,182,212,0.2)' : 'rgba(255,255,255,0.05)',
                            border: `1px solid ${isExpanded ? 'rgba(6,182,212,0.4)' : 'var(--border)'}`,
                            color: isExpanded ? 'var(--cx-primary)' : 'var(--text-primary)',
                            fontSize: 12, fontWeight: 600, cursor: 'pointer',
                            transition: 'all 0.2s',
                          }}
                        >
                          <MessageSquare size={13} />
                          <span>{v.total_reddit_shares}</span>
                          {isExpanded ? <ChevronUp size={13} /> : <ChevronDown size={13} />}
                        </button>
                      </td>
                    )}
                  </tr>

                  {/* ── Expandable Discussion Activity Thread Drawer ── */}
                  {isExpanded && !showTopBadge && (
                    <tr>
                      <td colSpan={7} style={{ background: 'rgba(6,182,212,0.02)', padding: '16px 20px', borderBottom: '1px solid var(--border-strong)' }}>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                          {/* Drawer Header & Sentiment Disparity */}
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 10 }}>
                            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                              <Layers size={16} color="var(--cx-primary)" />
                              <h4 style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
                                Reddit Discussion Activity ({discussions.length} threads / mentions)
                              </h4>
                            </div>
                            {v.sentiment_disparity_note && (
                              <span style={{ fontSize: 11, color: 'var(--text-secondary)', background: 'rgba(255,255,255,0.04)', padding: '3px 10px', borderRadius: 12 }}>
                                💡 {v.sentiment_disparity_note}
                              </span>
                            )}
                          </div>

                          {/* Discussion List */}
                          {discussions.length > 0 ? (
                            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
                              {discussions.map((d, dIdx) => (
                                <div
                                  key={dIdx}
                                  style={{
                                    padding: '12px 16px', borderRadius: 8,
                                    background: 'rgba(255,255,255,0.03)',
                                    border: '1px solid var(--border)',
                                    display: 'flex', flexDirection: 'column', gap: 6,
                                  }}
                                >
                                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 10 }}>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                      <span style={{
                                        padding: '2px 8px', borderRadius: 4,
                                        background: 'rgba(244,63,94,0.15)', color: 'var(--rd-primary)',
                                        fontSize: 11, fontWeight: 700,
                                      }}>
                                        r/{d.subreddit || 'reddit'}
                                      </span>
                                      <span style={{ fontSize: 12, color: 'var(--text-secondary)', display: 'flex', alignItems: 'center', gap: 4 }}>
                                        <User size={11} /> u/{d.author}
                                      </span>
                                        {d.published_at && (
                                          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
                                            • {formatDate(d.published_at)}
                                          </span>
                                        )}
                                        {d.match_type === 'semantic' && (
                                          <span
                                            style={{
                                              padding: '1px 6px', borderRadius: 4,
                                              fontSize: 10, fontWeight: 700,
                                              background: 'rgba(192, 132, 252, 0.15)',
                                              color: '#c084fc',
                                              display: 'inline-flex', alignItems: 'center', gap: 3,
                                            }}
                                            title={d.similarity_score ? `Similarity: ${Math.round(d.similarity_score * 100)}%` : 'Semantic Match'}
                                          >
                                            <Sparkles size={9} /> Semantic {d.similarity_score ? `${Math.round(d.similarity_score * 100)}%` : ''}
                                          </span>
                                        )}
                                      </div>

                                    <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                      {/* Sentiment badge */}
                                      <span style={{
                                        padding: '2px 8px', borderRadius: 10,
                                        fontSize: 10, fontWeight: 700, textTransform: 'capitalize',
                                        background: d.sentiment_label === 'positive' ? 'rgba(34,197,94,0.15)' : d.sentiment_label === 'negative' ? 'rgba(239,68,68,0.15)' : 'rgba(245,158,11,0.15)',
                                        color: d.sentiment_label === 'positive' ? 'var(--positive)' : d.sentiment_label === 'negative' ? 'var(--negative)' : 'var(--neutral)',
                                      }}>
                                        {d.sentiment_label || 'neutral'}
                                      </span>

                                      {/* Score */}
                                      <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>
                                        ↑ {d.score || 0}
                                      </span>

                                      {/* Link to reddit */}
                                      {d.permalink && (
                                        <a
                                          href={normalizeRedditUrl(d.permalink)}
                                          target="_blank"
                                          rel="noopener noreferrer"
                                          style={{ color: 'var(--text-muted)', display: 'flex', alignItems: 'center' }}
                                          title="Open Reddit thread in new tab"
                                        >
                                          <ExternalLink size={13} />
                                        </a>
                                      )}
                                    </div>
                                  </div>

                                  <p style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.45, whiteSpace: 'pre-wrap' }}>
                                    {d.body}
                                  </p>
                                </div>
                              ))}
                            </div>
                          ) : (
                            <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: 10 }}>
                              No individual comment snippets available for this video.
                            </div>
                          )}
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
