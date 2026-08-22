import { Hash, Sparkles, Video, Layers } from 'lucide-react';

export default function TopicComparison({ data, loading }) {
  if (loading) {
    return (
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <div className="skeleton" style={{ height: 180, borderRadius: 12 }} />
        <div className="skeleton" style={{ height: 180, borderRadius: 12 }} />
      </div>
    );
  }

  const shared = data?.shared_topics || [];
  const ytTopics = data?.youtube_topics || [];
  const rdTopics = data?.reddit_topics || [];
  const correlations = data?.top_correlations || [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Shared Topics Banner */}
      {shared.length > 0 && (
        <div style={{
          padding: '16px 20px',
          borderRadius: 10,
          background: 'rgba(6,182,212,0.06)',
          border: '1px solid rgba(6,182,212,0.25)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <Sparkles size={16} color="var(--cx-primary)" />
            <h4 style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
              Cross-Platform Shared Topics & Themes
            </h4>
            <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>
              High-virality bridge themes
            </span>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {shared.map((topic, i) => (
              <span
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 6,
                  padding: '5px 12px',
                  borderRadius: 20,
                  background: 'linear-gradient(135deg, rgba(6,182,212,0.2), rgba(99,102,241,0.2))',
                  border: '1px solid rgba(6,182,212,0.4)',
                  color: 'var(--text-primary)',
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                <Hash size={12} color="var(--cx-primary)" />
                {topic}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* Platform Topic Columns */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        {/* YouTube Video Themes */}
        <div style={{
          padding: '16px',
          borderRadius: 10,
          background: 'rgba(255,255,255,0.02)',
          border: '1px solid var(--border)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <Video size={16} color="var(--yt-primary)" />
            <h4 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
              YouTube Content Keywords
            </h4>
          </div>

          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {ytTopics.length > 0 ? (
              ytTopics.map((t, i) => (
                <span
                  key={i}
                  style={{
                    padding: '4px 10px',
                    borderRadius: 16,
                    background: 'rgba(99,102,241,0.1)',
                    border: '1px solid rgba(99,102,241,0.2)',
                    color: 'var(--yt-primary)',
                    fontSize: 12,
                  }}
                >
                  {t}
                </span>
              ))
            ) : (
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>No YouTube topics extracted yet</span>
            )}
          </div>
        </div>

        {/* Reddit Discussion Themes */}
        <div style={{
          padding: '16px',
          borderRadius: 10,
          background: 'rgba(255,255,255,0.02)',
          border: '1px solid var(--border)',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
            <Layers size={16} color="var(--rd-primary)" />
            <h4 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
              Reddit Community Discussion Themes
            </h4>
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
            {rdTopics.length > 0 ? (
              rdTopics.map((t, i) => (
                <span
                  key={i}
                  style={{
                    padding: '4px 10px',
                    borderRadius: 16,
                    background: 'rgba(244,63,94,0.1)',
                    border: '1px solid rgba(244,63,94,0.2)',
                    color: 'var(--rd-primary)',
                    fontSize: 12,
                  }}
                >
                  {t}
                </span>
              ))
            ) : (
              <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>No Reddit discussion topics extracted yet</span>
            )}
          </div>
        </div>
      </div>

      {/* Topic Correlation Strength Matrix */}
      {correlations.length > 0 && (
        <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
          <div style={{
            padding: '10px 16px',
            background: 'rgba(255,255,255,0.03)',
            borderBottom: '1px solid var(--border)',
            fontSize: 12,
            fontWeight: 700,
            color: 'var(--text-secondary)',
          }}>
            Cross-Platform Topic Relevance Matrix
          </div>
          <table className="dash-table">
            <thead>
              <tr>
                <th>Topic / Keyword</th>
                <th style={{ textAlign: 'center' }}>YouTube Video Focus</th>
                <th style={{ textAlign: 'center' }}>Reddit Discussion Volume</th>
              </tr>
            </thead>
            <tbody>
              {correlations.map((row, i) => (
                <tr key={i}>
                  <td style={{ fontWeight: 600, color: 'var(--text-primary)' }}>
                    #{row.topic}
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <span style={{
                      padding: '2px 8px',
                      borderRadius: 10,
                      background: row.youtube_relevance === 'High' ? 'rgba(99,102,241,0.15)' : 'rgba(255,255,255,0.04)',
                      color: row.youtube_relevance === 'High' ? 'var(--yt-primary)' : 'var(--text-muted)',
                      fontSize: 11,
                      fontWeight: 600,
                    }}>
                      {row.youtube_relevance}
                    </span>
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    <span style={{
                      padding: '2px 8px',
                      borderRadius: 10,
                      background: row.reddit_discussion_volume === 'High' ? 'rgba(244,63,94,0.15)' : 'rgba(255,255,255,0.04)',
                      color: row.reddit_discussion_volume === 'High' ? 'var(--rd-primary)' : 'var(--text-muted)',
                      fontSize: 11,
                      fontWeight: 600,
                    }}>
                      {row.reddit_discussion_volume}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
