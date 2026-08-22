import React, { useState } from 'react';
import {
  ExternalLink, Eye, ThumbsUp, MessageSquare, Star,
  Clock, ChevronDown, ChevronUp, Layers, User, Calendar, Tag,
} from 'lucide-react';

function fmt(n) {
  if (n == null || n === 0) return '—';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

function formatDate(isoStr) {
  if (!isoStr) return null;
  try {
    const d = new Date(isoStr);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch {
    return null;
  }
}

function SentimentPill({ sentiment, platform = 'yt' }) {
  if (!sentiment) return <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>;
  const label = sentiment.dominant_label || 'neutral';
  const posPct = (sentiment.positive * 100).toFixed(0);

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
      title={`${posPct}% Positive, ${(sentiment.negative * 100).toFixed(0)}% Negative`}
    >
      <span style={{ width: 5, height: 5, borderRadius: '50%', background: c.text }} />
      {posPct}% Pos
    </span>
  );
}

export default function SharedVideosTable({ videos, loading, showTopBadge = false }) {
  const [expandedId, setExpandedId] = useState(null);

  const toggleExpand = (vidId) => {
    setExpandedId(prev => (prev === vidId ? null : vidId));
  };

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
    <div style={{ overflowX: 'auto' }}>
      <table className="dash-table" style={{ width: '100%', minWidth: 800 }}>
        <thead>
          <tr>
            <th style={{ width: '38%' }}>YouTube Video</th>
            <th style={{ textAlign: 'right', width: '10%' }}>
              <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}>
                <Eye size={12} /> Views
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
                <th style={{ textAlign: 'center', width: '11%' }}>Propagation</th>
                <th style={{ textAlign: 'right', width: '10%' }}>Discussions</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {videos.map((v, idx) => {
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
                        </div>

                        {/* Topic Tags */}
                        {v.topics?.length > 0 && (
                          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 2 }}>
                            {v.topics.slice(0, 3).map((t, i) => (
                              <span
                                key={i}
                                style={{
                                  fontSize: 10,
                                  color: 'var(--text-muted)',
                                  background: 'rgba(255,255,255,0.04)',
                                  padding: '1px 6px',
                                  borderRadius: 4,
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
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: 4,
                            padding: '2px 8px',
                            borderRadius: 10,
                            background: v.propagation_delay_hours <= 6 ? 'rgba(34, 197, 94, 0.12)' : 'rgba(6, 182, 212, 0.12)',
                            color: v.propagation_delay_hours <= 6 ? 'var(--positive)' : 'var(--cx-primary)',
                            fontSize: 11,
                            fontWeight: 700,
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
                          display: 'inline-flex',
                          alignItems: 'center',
                          gap: 6,
                          padding: '6px 12px',
                          borderRadius: 8,
                          background: isExpanded ? 'rgba(6,182,212,0.2)' : 'rgba(255,255,255,0.05)',
                          border: `1px solid ${isExpanded ? 'rgba(6,182,212,0.4)' : 'var(--border)'}`,
                          color: isExpanded ? 'var(--cx-primary)' : 'var(--text-primary)',
                          fontSize: 12,
                          fontWeight: 600,
                          cursor: 'pointer',
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
                                  padding: '12px 16px',
                                  borderRadius: 8,
                                  background: 'rgba(255,255,255,0.03)',
                                  border: '1px solid var(--border)',
                                  display: 'flex',
                                  flexDirection: 'column',
                                  gap: 6,
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
                                  </div>

                                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                                    {/* Sentiment badge */}
                                    <span style={{
                                      padding: '2px 8px', borderRadius: 10,
                                      fontSize: 10, fontWeight: 700,
                                      textTransform: 'capitalize',
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
                                        href={`https://reddit.com${d.permalink}`}
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
  );
}
