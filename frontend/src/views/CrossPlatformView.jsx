import { useState } from 'react';
import { Search, Link as LinkIcon, Activity } from 'lucide-react';

import { useAnalytics } from '../hooks/useAnalytics';
import { fetchEngagementComparison, fetchSharedVideos } from '../api/client';

import EngagementBar     from '../components/charts/EngagementBar';
import TimelineChart     from '../components/charts/TimelineChart';
import SharedVideosTable from '../components/tables/SharedVideosTable';

export default function CrossPlatformView() {
  const [subQuery, setSubQuery] = useState('');
  const [activeSub, setActiveSub] = useState(null);

  // ── Global Engagement (Dual-axis Bar) ────────────────────────────────────
  const { data: comparison, loading: compLoading } = useAnalytics(
    (signal) => fetchEngagementComparison(signal),
    []
  );

  // ── Shared Videos (Timeline & Table) ─────────────────────────────────────
  const { data: shared, loading: sharedLoading } = useAnalytics(
    (signal) => fetchSharedVideos(activeSub, 500, signal),
    [activeSub],
    { enabled: !!activeSub }
  );

  const handleSearch = (e) => {
    e.preventDefault();
    if (subQuery.trim()) {
      // Remove 'r/' if user typed it
      setActiveSub(subQuery.replace(/^r\//i, '').trim());
    }
  };

  // Convert shared payload into TimelineChart format (ordered chronologically or simply mapping top N)
  // For demonstration, we just reverse the top shared videos so the line chart looks chronological/progression-like
  const timelineData = (shared || []).slice(0, 15).reverse().map(v => ({
    label: v.youtube_video_id,
    youtube_views: v.youtube_views || 0,
    reddit_comments: v.reddit_total_comments || 0,
  }));

  return (
    <div className="fade-up" style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      
      {/* ── Header row ──────────────────────────────────────────────────── */}
      <div>
        <h2 className="gradient-text-cx" style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-0.03em' }}>
          Cross-Platform Correlation
        </h2>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 2 }}>
          Discover how content propagates between YouTube and Reddit
        </p>
      </div>

      {/* ── Top Level Comparison ────────────────────────────────────────── */}
      <div className="glass-card" style={{ padding: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 20 }}>
          <Activity size={18} color="var(--cx-primary)" />
          <h3 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
            Global Engagement Index
          </h3>
          <span style={{ marginLeft: 'auto', fontSize: 12, color: 'var(--text-muted)' }}>
            Normalised to 0–100 scale
          </span>
        </div>
        <EngagementBar data={comparison} loading={compLoading} />
      </div>

      {/* ── Subreddit Search Bar ────────────────────────────────────────── */}
      <div className="glass-card" style={{ padding: 24 }}>
        <h3 style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 8 }}>
          Content Propagation Tracker
        </h3>
        <p style={{ fontSize: 13, color: 'var(--text-muted)', marginBottom: 20, maxWidth: 600 }}>
          Scan a specific subreddit's comment corpus to discover YouTube videos shared within its threads. 
          Correlates YouTube views against Reddit discussion volume.
        </p>

        <form onSubmit={handleSearch} style={{ display: 'flex', gap: 10, maxWidth: 400, marginBottom: 24 }}>
          <div style={{ position: 'relative', flex: 1 }}>
            <span style={{ position: 'absolute', left: 14, top: '50%', transform: 'translateY(-50%)', color: 'var(--text-muted)' }}>
              r/
            </span>
            <input
              type="text"
              placeholder="e.g. learnprogramming"
              value={subQuery}
              onChange={(e) => setSubQuery(e.target.value)}
              style={{
                width: '100%',
                background: 'rgba(255,255,255,0.04)',
                border: '1px solid var(--border-strong)',
                borderRadius: 8,
                padding: '10px 14px 10px 34px',
                color: 'var(--text-primary)',
                fontSize: 14,
                outline: 'none',
                transition: 'border-color 0.2s',
              }}
              onFocus={(e) => e.target.style.borderColor = 'var(--cx-primary)'}
              onBlur={(e) => e.target.style.borderColor = 'var(--border-strong)'}
            />
          </div>
          <button
            type="submit"
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              background: 'var(--cx-primary)',
              color: '#000', fontWeight: 600, fontSize: 13,
              padding: '0 20px', borderRadius: 8,
              border: 'none', cursor: 'pointer',
              transition: 'opacity 0.2s',
            }}
            onMouseEnter={(e) => e.target.style.opacity = 0.9}
            onMouseLeave={(e) => e.target.style.opacity = 1}
          >
            <Search size={16} />
            Scan
          </button>
        </form>

        {activeSub && (
          <div style={{ display: 'grid', gridTemplateColumns: '1fr', gap: 24 }}>
            {/* Timeline Overlay */}
            <div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12 }}>
                <LinkIcon size={16} color="var(--text-muted)" />
                <h4 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
                  Engagement Overlay: YouTube Views vs Reddit Comments
                </h4>
              </div>
              <TimelineChart data={timelineData} loading={sharedLoading} />
            </div>

            {/* Detailed Table */}
            <div>
              <h4 style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', marginBottom: 12 }}>
                Discovered Videos Table
              </h4>
              <div style={{ border: '1px solid var(--border)', borderRadius: 10, overflow: 'hidden' }}>
                <SharedVideosTable videos={shared} loading={sharedLoading} />
              </div>
            </div>
          </div>
        )}
      </div>

    </div>
  );
}
