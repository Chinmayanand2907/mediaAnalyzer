import { ExternalLink, Eye, ThumbsUp, MessageSquare, Star } from 'lucide-react';

/**
 * SharedVideosTable — lists YouTube videos found shared inside Reddit threads.
 *
 * Props:
 *   videos   SharedVideoItem[]
 *   loading  bool
 *   showTopBadge  bool — show a "Top Video" badge (for top-videos mode)
 */

function fmt(n) {
  if (n == null || n === 0) return '—';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(1)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

export default function SharedVideosTable({ videos, loading, showTopBadge = false }) {
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

  if (!videos?.length) return (
    <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
      No shared videos found. Make sure the subreddit has been ingested and contains YouTube links.
    </div>
  );

  return (
    <div style={{ overflowX: 'auto' }}>
      <table className="dash-table" style={{ tableLayout: 'fixed', width: '100%' }}>
        <thead>
          <tr>
            <th style={{ width: '44%' }}>Video</th>
            {!showTopBadge && (
              <th style={{ textAlign: 'right', width: '8%' }}>Shares</th>
            )}
            <th style={{ textAlign: 'right', width: '12%' }}>
              <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}>
                <Eye size={12} /> Views
              </span>
            </th>
            <th style={{ textAlign: 'right', width: '12%' }}>
              <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}>
                <ThumbsUp size={12} /> Likes
              </span>
            </th>
            <th style={{ textAlign: 'right', width: '12%' }}>
              <span style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 4 }}>
                <MessageSquare size={12} /> Comments
              </span>
            </th>
            {!showTopBadge && (
              <>
                <th style={{ textAlign: 'right', width: '10%' }}>Reddit ↑</th>
                <th style={{ textAlign: 'right', width: '10%' }}>Reddit 💬</th>
              </>
            )}
          </tr>
        </thead>
        <tbody>
          {videos.map((v, idx) => (
            <tr key={v.youtube_video_id} style={{ verticalAlign: 'middle' }}>
              {/* ── Video Card Cell ── */}
              <td>
                <a
                  href={v.youtube_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ display: 'flex', alignItems: 'center', gap: 10, textDecoration: 'none' }}
                >
                  {/* Thumbnail */}
                  <div style={{ flexShrink: 0, position: 'relative' }}>
                    {v.youtube_thumbnail_url ? (
                      <img
                        src={v.youtube_thumbnail_url}
                        alt={v.youtube_title || v.youtube_video_id}
                        style={{
                          width: 112,
                          height: 63,
                          objectFit: 'cover',
                          borderRadius: 6,
                          border: '1px solid var(--border)',
                          display: 'block',
                        }}
                        onError={(e) => { e.target.style.display = 'none'; }}
                      />
                    ) : (
                      <div style={{
                        width: 112, height: 63, borderRadius: 6,
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
                  </div>

                  {/* Title + Channel */}
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{
                      color: 'var(--yt-primary)',
                      fontWeight: 600,
                      fontSize: 13,
                      lineHeight: 1.35,
                      overflow: 'hidden',
                      display: '-webkit-box',
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: 'vertical',
                      marginBottom: 4,
                    }}>
                      {v.youtube_title || (
                        <span style={{ fontFamily: 'monospace', fontSize: 12, opacity: 0.7 }}>
                          {v.youtube_video_id}
                        </span>
                      )}
                    </div>
                    {v.youtube_channel_title && (
                      <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 3 }}>
                        {v.youtube_channel_title}
                      </div>
                    )}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 4 }}>
                      <ExternalLink size={10} style={{ color: 'var(--text-muted)' }} />
                      <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                        {v.youtube_video_id}
                      </span>
                    </div>
                  </div>
                </a>
              </td>

              {/* ── Reddit Shares ── */}
              {!showTopBadge && (
                <td style={{ textAlign: 'right' }}>
                  <span style={{
                    padding: '2px 8px', borderRadius: 12,
                    background: 'rgba(99,102,241,0.12)', color: 'var(--yt-primary)',
                    fontSize: 12, fontWeight: 700,
                  }}>
                    {v.total_reddit_shares}
                  </span>
                </td>
              )}

              {/* ── YT Views ── */}
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: 13, color: 'var(--text-secondary)' }}>
                {fmt(v.youtube_views)}
              </td>

              {/* ── YT Likes ── */}
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: 13, color: 'var(--text-secondary)' }}>
                {fmt(v.youtube_likes)}
              </td>

              {/* ── YT Comments ── */}
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: 13, color: 'var(--text-secondary)' }}>
                {fmt(v.youtube_comment_count)}
              </td>

              {/* ── Reddit stats (only in shared mode) ── */}
              {!showTopBadge && (
                <>
                  <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: 13, color: 'var(--text-secondary)' }}>
                    {fmt(v.reddit_total_upvotes)}
                  </td>
                  <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums', fontSize: 13, color: 'var(--text-secondary)' }}>
                    {fmt(v.reddit_total_comments)}
                  </td>
                </>
              )}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
