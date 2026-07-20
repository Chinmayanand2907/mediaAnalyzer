import { useState } from 'react';
import { Users, Hash, MessageSquare, Flame, RefreshCw, Layers } from 'lucide-react';
import { ResponsiveContainer, BarChart, Bar, XAxis, Tooltip, Cell, YAxis } from 'recharts';

import { useAnalytics } from '../hooks/useAnalytics';
import {
  fetchRedditSubreddits,
  fetchRedditSubreddit,
  fetchRedditSentiment,
  fetchRedditComments,
  fetchRedditKeywords,
  triggerRedditIngest,
} from '../api/client';

import StatCard      from '../components/layout/StatCard';
import SentimentPie  from '../components/charts/SentimentPie';
import CommentsTable from '../components/tables/CommentsTable';

const ACCENT = 'var(--rd-primary)';

function fmt(n) {
  if (n == null) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

/**
 * Custom Tooltip for Keyword BarChart
 */
const KeywordTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const { keyword, frequency } = payload[0].payload;
  return (
    <div style={{ background: '#1e1e2e', border: '1px solid var(--border-strong)', borderRadius: 8, padding: '10px 14px', fontSize: 13 }}>
      <span style={{ color: 'var(--text-primary)', fontWeight: 700 }}>"{keyword}"</span>
      <span style={{ color: 'var(--text-muted)', marginLeft: 8 }}>{frequency} mentions</span>
    </div>
  );
};

export default function RedditView() {
  const [selectedSub, setSelectedSub]     = useState(null);
  const [page, setPage]                   = useState(1);
  const [sentFilter, setSentFilter]       = useState(null);
  const [ingestMsg, setIngestMsg]         = useState('');

  // ── Subreddit list ───────────────────────────────────────────────────────
  const { data: subreddits, loading: listLoading } = useAnalytics(
    (signal) => fetchRedditSubreddits(signal),
    []
  );

  // ── Metrics ──────────────────────────────────────────────────────────────
  const { data: metrics, loading: metricsLoading } = useAnalytics(
    (signal) => fetchRedditSubreddit(selectedSub, signal),
    [selectedSub],
    { enabled: !!selectedSub }
  );

  // ── Sentiment ────────────────────────────────────────────────────────────
  const { data: sentiment, loading: sentLoading } = useAnalytics(
    (signal) => fetchRedditSentiment(selectedSub, 200, signal),
    [selectedSub],
    { enabled: !!selectedSub }
  );

  // ── Keywords ─────────────────────────────────────────────────────────────
  const { data: keywords, loading: kwLoading } = useAnalytics(
    (signal) => fetchRedditKeywords(selectedSub, 300, 15, signal),
    [selectedSub],
    { enabled: !!selectedSub }
  );

  // ── Comments ─────────────────────────────────────────────────────────────
  const { data: comments, loading: commentsLoading } = useAnalytics(
    (signal) => fetchRedditComments(selectedSub, page, 20, sentFilter, signal),
    [selectedSub, page, sentFilter],
    { enabled: !!selectedSub }
  );

  const handleIngest = async () => {
    if (!selectedSub) return;
    setIngestMsg('Queuing ingestion…');
    try {
      const res = await triggerRedditIngest(selectedSub);
      setIngestMsg(`✅ ${res.message}`);
    } catch (e) {
      setIngestMsg(`❌ ${e.message}`);
    }
    setTimeout(() => setIngestMsg(''), 6000);
  };

  return (
    <div className="fade-up" style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
      
      {/* ── Header row ──────────────────────────────────────────────────── */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
        <div>
          <h2 className="gradient-text-rd" style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-0.03em' }}>
            Reddit Insights
          </h2>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 2 }}>
            Community engagement and keyword trends
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* Subreddit selector */}
          <div style={{ position: 'relative' }}>
            <select
              className="platform-select"
              value={selectedSub ?? ''}
              onChange={(e) => { setSelectedSub(e.target.value || null); setPage(1); setSentFilter(null); }}
              style={{ minWidth: 200 }}
            >
              <option value="">— Select a subreddit —</option>
              {(subreddits ?? []).map((sub) => (
                <option key={sub.subreddit_name} value={sub.subreddit_name}>
                  r/{sub.subreddit_name}
                </option>
              ))}
            </select>
            {listLoading && (
              <span style={{ position: 'absolute', right: 36, top: '50%', transform: 'translateY(-50%)', fontSize: 11, color: 'var(--text-muted)' }}>
                Loading…
              </span>
            )}
          </div>

          {/* Ingest button */}
          <button
            onClick={handleIngest}
            disabled={!selectedSub}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '8px 14px', borderRadius: 10,
              background: selectedSub ? 'rgba(244,63,94,0.15)' : 'rgba(255,255,255,0.04)',
              border: `1px solid ${selectedSub ? 'rgba(244,63,94,0.4)' : 'var(--border)'}`,
              color: selectedSub ? 'var(--rd-primary)' : 'var(--text-muted)',
              fontSize: 13, fontWeight: 600,
              cursor: selectedSub ? 'pointer' : 'not-allowed',
              transition: 'all 0.2s',
            }}
          >
            <RefreshCw size={14} />
            Re-ingest
          </button>
        </div>
      </div>

      {ingestMsg && (
        <div style={{ padding: '10px 16px', borderRadius: 8, background: 'rgba(244,63,94,0.1)', border: '1px solid rgba(244,63,94,0.25)', fontSize: 13, color: 'var(--text-secondary)' }}>
          {ingestMsg}
        </div>
      )}

      {!selectedSub ? (
        /* Empty state */
        <div style={{ textAlign: 'center', padding: '80px 0' }}>
          <Layers size={48} color="var(--rd-primary)" style={{ opacity: 0.3, marginBottom: 16 }} />
          <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>
            Select a subreddit above — or trigger an ingestion to add one.
          </p>
        </div>
      ) : (
        <>
          {/* ── Stat Cards ──────────────────────────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))', gap: 14 }}>
            <StatCard title="Members"          value={fmt(metrics?.member_count)} icon={Users}         accent={ACCENT} loading={metricsLoading} />
            <StatCard title="Active Discussions" value={fmt(sentiment?.total_comments_analysed)} sub="recent comments" icon={MessageSquare} accent={ACCENT} loading={sentLoading} />
            <StatCard title="Trending Topic"   value={keywords?.[0]?.keyword || '—'} sub="top keyword" icon={Flame} accent={ACCENT} loading={kwLoading} />
          </div>

          {/* ── Charts Row (Sentiment + Keywords) ───────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div className="glass-card" style={{ padding: 20 }}>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 16 }}>
                Community Sentiment
              </h3>
              <SentimentPie data={sentiment} loading={sentLoading} accent={ACCENT} />
            </div>

            <div className="glass-card" style={{ padding: 20 }}>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 16, display: 'flex', alignItems: 'center', gap: 6 }}>
                <Hash size={16} color={ACCENT} />
                Trending Keywords
              </h3>
              {kwLoading ? (
                <div style={{ display: 'flex', gap: 4, alignItems: 'flex-end', height: 240 }}>
                  {Array.from({ length: 15 }).map((_, i) => (
                    <div key={i} className="skeleton" style={{ flex: 1, height: `${20 + Math.random() * 80}%`, borderRadius: '4px 4px 0 0' }} />
                  ))}
                </div>
              ) : !keywords?.length ? (
                <div style={{ height: 240, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
                  Not enough text to extract keywords.
                </div>
              ) : (
                <div style={{ height: 240 }}>
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={keywords} margin={{ top: 10, right: 0, left: -20, bottom: 0 }}>
                      <XAxis
                        dataKey="keyword"
                        tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
                        interval={0}
                        axisLine={false} tickLine={false}
                        angle={-45} textAnchor="end" height={60}
                      />
                      <YAxis
                        tick={{ fill: 'var(--text-muted)', fontSize: 10 }}
                        axisLine={false} tickLine={false}
                      />
                      <Tooltip cursor={{ fill: 'rgba(255,255,255,0.04)' }} content={<KeywordTooltip />} />
                      <Bar dataKey="frequency" radius={[4, 4, 0, 0]}>
                        {keywords.map((entry, index) => (
                          <Cell key={`cell-${index}`} fill={`rgba(244, 63, 94, ${0.4 + (index / keywords.length) * 0.6})`} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>

          {/* ── Comments Table ───────────────────────────────────────────── */}
          <div className="glass-card" style={{ padding: 20 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 16 }}>
              Live Discussions
            </h3>
            <CommentsTable
              comments={comments}
              loading={commentsLoading}
              page={page}
              onPageChange={(p) => setPage(p)}
              onFilter={(f) => { setSentFilter(f); setPage(1); }}
              activeFilter={sentFilter}
            />
          </div>
        </>
      )}
    </div>
  );
}
