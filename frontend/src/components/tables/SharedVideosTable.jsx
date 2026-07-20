import { ExternalLink } from 'lucide-react';

/**
 * SharedVideosTable — lists YouTube videos found shared inside Reddit threads.
 *
 * Props:
 *   videos   SharedVideoItem[]
 *   loading  bool
 */
export default function SharedVideosTable({ videos, loading }) {
  if (loading) {
    return (
      <div style={{ padding: 20 }}>
        {Array.from({ length: 4 }).map((_, i) => (
          <div key={i} className="skeleton" style={{ height: 14, marginBottom: 14, width: `${60 + Math.random() * 35}%` }} />
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
      <table className="dash-table">
        <thead>
          <tr>
            <th>Video</th>
            <th style={{ textAlign: 'right' }}>Reddit Shares</th>
            <th style={{ textAlign: 'right' }}>YT Views</th>
            <th style={{ textAlign: 'right' }}>YT Likes</th>
            <th style={{ textAlign: 'right' }}>Reddit Upvotes</th>
            <th style={{ textAlign: 'right' }}>Reddit Comments</th>
          </tr>
        </thead>
        <tbody>
          {videos.map((v) => (
            <tr key={v.youtube_video_id}>
              <td>
                <a
                  href={v.youtube_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  style={{ display: 'flex', alignItems: 'center', gap: 6, color: 'var(--yt-primary)', fontWeight: 500, fontSize: 13 }}
                >
                  <span style={{ fontFamily: 'monospace', fontSize: 12 }}>{v.youtube_video_id}</span>
                  <ExternalLink size={12} />
                </a>
              </td>
              <td style={{ textAlign: 'right' }}>
                <span style={{
                  padding: '2px 10px', borderRadius: 12,
                  background: 'rgba(99,102,241,0.12)', color: 'var(--yt-primary)',
                  fontSize: 12, fontWeight: 700,
                }}>
                  {v.total_reddit_shares}
                </span>
              </td>
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {v.youtube_views?.toLocaleString() ?? '—'}
              </td>
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {v.youtube_likes?.toLocaleString() ?? '—'}
              </td>
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {v.reddit_total_upvotes?.toLocaleString() ?? '—'}
              </td>
              <td style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}>
                {v.reddit_total_comments?.toLocaleString() ?? '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
