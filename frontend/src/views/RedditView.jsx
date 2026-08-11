import { useState, useEffect } from 'react';
import { Users, Hash, MessageSquare, Flame, RefreshCw, Layers, PlusCircle } from 'lucide-react';
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
  const [newSubInput, setNewSubInput]     = useState('');
  const [inputMode, setInputMode]         = useState(false);
  const [page, setPage]                   = useState(1);
  const [sentFilter, setSentFilter]       = useState(null);
  const [ingestMsg, setIngestMsg]         = useState('');
  const [ingestLoading, setIngestLoading] = useState(false);

  // ── Subreddit list ───────────────────────────────────────────────────────
  const { data: subreddits, loading: listLoading, refetch: refetchSubreddits } = useAnalytics(
    (signal) => fetchRedditSubreddits(signal),
    []
  );

  // ── Metrics ──────────────────────────────────────────────────────────────
  const { data: metrics, loading: metricsLoading, refetch: refetchMetrics } = useAnalytics(
    (signal) => fetchRedditSubreddit(selectedSub, signal),
    [selectedSub],
    { enabled: !!selectedSub }
  );

  // ── Sentiment ────────────────────────────────────────────────────────────
  const { data: sentiment, loading: sentLoading, refetch: refetchSentiment } = useAnalytics(
    (signal) => fetchRedditSentiment(selectedSub, 200, signal),
    [selectedSub],
    { enabled: !!selectedSub }
  );

  // ── Keywords ─────────────────────────────────────────────────────────────
  const { data: keywords, loading: kwLoading, refetch: refetchKeywords } = useAnalytics(
    (signal) => fetchRedditKeywords(selectedSub, 300, 15, signal),
    [selectedSub],
    { enabled: !!selectedSub }
  );

  // ── Comments ─────────────────────────────────────────────────────────────
  const { data: comments, loading: commentsLoading, refetch: refetchComments } = useAnalytics(
    (signal) => fetchRedditComments(selectedSub, page, 20, sentFilter, signal),
    [selectedSub, page, sentFilter],
    { enabled: !!selectedSub }
  );

  // Auto-select the first subreddit when data loads if none is selected
  useEffect(() => {
    if (!selectedSub && subreddits && subreddits.length > 0) {
      setSelectedSub(subreddits[0].platform_id);
    }
  }, [subreddits, selectedSub]);

  const handleIngest = async (subName) => {
    const target = subName || selectedSub;
    if (!target) return;
    setIngestLoading(true);
    setIngestMsg('⏳ Queuing ingestion task...');
    try {
      const res = await triggerRedditIngest(target);
      setIngestMsg(`⏳ Ingestion started: ${res.message} — Updating metrics...`);

      const isNewSub = !selectedSub || selectedSub !== target;
      if (isNewSub) {
        setTimeout(() => {
          setSelectedSub(target);
          setNewSubInput('');
          setInputMode(false);
          setPage(1);
          setSentFilter(null);
        }, 1500);
      }

      // Poll multiple times because Celery tasks can take 10+ seconds
      let pollCount = 0;
      const intervalId = setInterval(() => {
        pollCount += 1;
        refetchSubreddits();
        refetchMetrics();
        refetchSentiment();
        refetchKeywords();
        refetchComments();
        
        if (pollCount >= 4) {
          clearInterval(intervalId);
          setIngestMsg('✅ Ingestion complete! Latest data & subreddit timestamp loaded.');
          setIngestLoading(false);
        }
      }, 3500);
    } catch (e) {
      setIngestMsg(`❌ ${e.message}`);
      setIngestLoading(false);
    }
    setTimeout(() => setIngestMsg(''), 15000);
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
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {!inputMode ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
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
                <button
                  onClick={() => setInputMode(true)}
                  title="Add a new subreddit"
                  style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    padding: '7px 12px', borderRadius: 10,
                    background: 'rgba(255,255,255,0.05)',
                    border: '1px solid var(--border)',
                    color: 'var(--text-muted)', fontSize: 12, fontWeight: 600,
                    cursor: 'pointer', whiteSpace: 'nowrap',
                    transition: 'all 0.2s',
                  }}
                >
                  <PlusCircle size={13} /> Add new
                </button>
              </div>
            ) : (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{
                  display: 'flex', alignItems: 'center',
                  background: 'rgba(255,255,255,0.06)',
                  border: '1px solid rgba(244,63,94,0.45)',
                  borderRadius: 10, overflow: 'hidden',
                }}>
                  <span style={{ padding: '0 10px', color: 'var(--text-muted)', fontSize: 13, fontWeight: 700, borderRight: '1px solid rgba(244,63,94,0.3)' }}>r/</span>
                  <input
                    type="text"
                    autoFocus
                    placeholder="subreddit name"
                    value={newSubInput}
                    onChange={(e) => setNewSubInput(e.target.value.replace(/^r\//, '').replace(/\s/g, ''))}
                    onKeyDown={(e) => { if (e.key === 'Enter' && newSubInput.trim()) handleIngest(newSubInput.trim()); if (e.key === 'Escape') setInputMode(false); }}
                    style={{
                      padding: '8px 12px', minWidth: 200,
                      background: 'transparent',
                      border: 'none', color: 'var(--text-primary)', fontSize: 13,
                      outline: 'none',
                    }}
                  />
                </div>
                <button
                  onClick={() => { if (newSubInput.trim()) handleIngest(newSubInput.trim()); }}
                  disabled={!newSubInput.trim() || ingestLoading}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    padding: '8px 14px', borderRadius: 10,
                    background: newSubInput.trim() ? 'rgba(244,63,94,0.2)' : 'rgba(255,255,255,0.04)',
                    border: `1px solid ${newSubInput.trim() ? 'rgba(244,63,94,0.5)' : 'var(--border)'}`,
                    color: newSubInput.trim() ? 'var(--rd-primary)' : 'var(--text-muted)',
                    fontSize: 13, fontWeight: 600, cursor: 'pointer',
                    transition: 'all 0.2s',
                  }}
                >
                  <PlusCircle size={13} /> Ingest
                </button>
                <button
                  onClick={() => { setInputMode(false); setNewSubInput(''); }}
                  style={{
                    padding: '7px 10px', borderRadius: 10,
                    background: 'transparent', border: '1px solid var(--border)',
                    color: 'var(--text-muted)', fontSize: 12, cursor: 'pointer',
                  }}
                >✕</button>
              </div>
            )}
          </div>

          {/* Ingest button — only in dropdown mode */}
          {!inputMode && (
            <button
              onClick={() => handleIngest(null)}
              disabled={!selectedSub || ingestLoading}
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
              <RefreshCw size={14} style={{ animation: ingestLoading ? 'spin 1s linear infinite' : 'none' }} />
              Re-ingest
            </button>
          )}
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
