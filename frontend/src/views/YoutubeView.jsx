import { useState, useEffect } from 'react';
import { Users, Eye, ThumbsUp, Video, RefreshCw, Play, PlusCircle } from 'lucide-react';

import { useAnalytics } from '../hooks/useAnalytics';
import {
  fetchYoutubeChannels,
  fetchYoutubeChannel,
  fetchYoutubeSentiment,
  fetchYoutubeComments,
  triggerYoutubeIngest,
} from '../api/client';

import StatCard      from '../components/layout/StatCard';
import SentimentPie  from '../components/charts/SentimentPie';
import CommentsTable from '../components/tables/CommentsTable';

const ACCENT = 'var(--yt-primary)';

function fmt(n) {
  if (n == null) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000)     return `${(n / 1_000).toFixed(1)}K`;
  return n.toLocaleString();
}

export default function YoutubeView() {
  const [selectedChannel, setSelectedChannel] = useState(null);
  const [newChannelInput, setNewChannelInput] = useState('');
  const [inputMode, setInputMode] = useState(false); // toggle between dropdown and text input
  const [page, setPage]                       = useState(1);
  const [sentFilter, setSentFilter]           = useState(null);
  const [ingestMsg, setIngestMsg]             = useState('');
  const [ingestLoading, setIngestLoading]     = useState(false);  // ── Channel list ─────────────────────────────────────────────────────────
  const { data: channels, loading: channelsLoading, refetch: refetchChannels } = useAnalytics(
    (signal) => fetchYoutubeChannels(signal),
    []
  );

  // ── Channel metrics ──────────────────────────────────────────────────────
  const { data: metrics, loading: metricsLoading, refetch: refetchMetrics } = useAnalytics(
    (signal) => fetchYoutubeChannel(selectedChannel, signal),
    [selectedChannel],
    { enabled: !!selectedChannel }
  );

  // ── Sentiment ────────────────────────────────────────────────────────────
  const { data: sentiment, loading: sentLoading, refetch: refetchSentiment } = useAnalytics(
    (signal) => fetchYoutubeSentiment(selectedChannel, 200, signal),
    [selectedChannel],
    { enabled: !!selectedChannel }
  );

  // ── Comments ─────────────────────────────────────────────────────────────
  const { data: comments, loading: commentsLoading, refetch: refetchComments } = useAnalytics(
    (signal) => fetchYoutubeComments(selectedChannel, page, 20, sentFilter, signal),
    [selectedChannel, page, sentFilter],
    { enabled: !!selectedChannel }
  );

  // Auto-select the first channel when data loads if none is selected
  useEffect(() => {
    if (!selectedChannel && channels && channels.length > 0) {
      setSelectedChannel(channels[0].channel_id);
    }
  }, [channels, selectedChannel]);

  const handleIngest = async (channelId) => {
    const target = channelId || selectedChannel;
    if (!target) return;
    setIngestLoading(true);
    setIngestMsg('⏳ Queuing ingestion task...');
    try {
      const res = await triggerYoutubeIngest(target);
      setIngestMsg(`⏳ Ingestion started: ${res.message} — Updating metrics...`);
      
      const isNewChannel = !selectedChannel || selectedChannel !== target;
      if (isNewChannel) {
        setTimeout(() => {
          setSelectedChannel(target);
          setNewChannelInput('');
          setInputMode(false);
          setPage(1);
          setSentFilter(null);
        }, 1500);
      }

      // Poll multiple times because Celery tasks can take 10+ seconds
      let pollCount = 0;
      const intervalId = setInterval(() => {
        pollCount += 1;
        refetchChannels();
        refetchMetrics();
        refetchSentiment();
        refetchComments();
        
        if (pollCount >= 4) {
          clearInterval(intervalId);
          setIngestMsg('✅ Ingestion complete! Latest data & channel timestamp loaded.');
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
          <h2 className="gradient-text-yt" style={{ fontSize: 22, fontWeight: 800, letterSpacing: '-0.03em' }}>
            YouTube Analytics
          </h2>
          <p style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 2 }}>
            Sentiment intelligence across your tracked channels
          </p>
        </div>

        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          {/* Channel selector */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {!inputMode ? (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ position: 'relative' }}>
                  <select
                    className="platform-select"
                    value={selectedChannel ?? ''}
                    onChange={(e) => { setSelectedChannel(e.target.value || null); setPage(1); setSentFilter(null); }}
                    style={{ minWidth: 200 }}
                  >
                    <option value="">— Select a channel —</option>
                    {(channels ?? []).map((ch) => (
                      <option key={ch.channel_id} value={ch.channel_id}>
                        {ch.display_name || ch.channel_id}
                      </option>
                    ))}
                  </select>
                  {channelsLoading && (
                    <span style={{ position: 'absolute', right: 36, top: '50%', transform: 'translateY(-50%)', fontSize: 11, color: 'var(--text-muted)' }}>
                      Loading…
                    </span>
                  )}
                </div>
                <button
                  onClick={() => setInputMode(true)}
                  title="Add a new channel by ID"
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
                <input
                  type="text"
                  autoFocus
                  placeholder="Enter YouTube Channel ID (e.g. UCxxxxxx)"
                  value={newChannelInput}
                  onChange={(e) => setNewChannelInput(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter' && newChannelInput.trim()) handleIngest(newChannelInput.trim()); if (e.key === 'Escape') setInputMode(false); }}
                  style={{
                    minWidth: 280, padding: '8px 12px', borderRadius: 10,
                    background: 'rgba(255,255,255,0.06)',
                    border: '1px solid rgba(99,102,241,0.45)',
                    color: 'var(--text-primary)', fontSize: 13,
                    outline: 'none',
                  }}
                />
                <button
                  onClick={() => { if (newChannelInput.trim()) handleIngest(newChannelInput.trim()); }}
                  disabled={!newChannelInput.trim() || ingestLoading}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 5,
                    padding: '8px 14px', borderRadius: 10,
                    background: newChannelInput.trim() ? 'rgba(99,102,241,0.2)' : 'rgba(255,255,255,0.04)',
                    border: `1px solid ${newChannelInput.trim() ? 'rgba(99,102,241,0.5)' : 'var(--border)'}`,
                    color: newChannelInput.trim() ? 'var(--yt-primary)' : 'var(--text-muted)',
                    fontSize: 13, fontWeight: 600, cursor: 'pointer',
                    transition: 'all 0.2s',
                  }}
                >
                  <PlusCircle size={13} /> Ingest
                </button>
                <button
                  onClick={() => { setInputMode(false); setNewChannelInput(''); }}
                  style={{
                    padding: '7px 10px', borderRadius: 10,
                    background: 'transparent', border: '1px solid var(--border)',
                    color: 'var(--text-muted)', fontSize: 12, cursor: 'pointer',
                  }}
                >✕</button>
              </div>
            )}
          </div>

          {/* Ingest button — only show when a channel is selected from dropdown */}
          {!inputMode && (
            <button
              onClick={() => handleIngest(null)}
              disabled={!selectedChannel || ingestLoading}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '8px 14px', borderRadius: 10,
                background: selectedChannel ? 'rgba(99,102,241,0.15)' : 'rgba(255,255,255,0.04)',
                border: `1px solid ${selectedChannel ? 'rgba(99,102,241,0.4)' : 'var(--border)'}`,
                color: selectedChannel ? 'var(--yt-primary)' : 'var(--text-muted)',
                fontSize: 13, fontWeight: 600,
                cursor: selectedChannel ? 'pointer' : 'not-allowed',
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
        <div style={{ padding: '10px 16px', borderRadius: 8, background: 'rgba(99,102,241,0.1)', border: '1px solid rgba(99,102,241,0.25)', fontSize: 13, color: 'var(--text-secondary)' }}>
          {ingestMsg}
        </div>
      )}

      {!selectedChannel ? (
        /* Empty state */
        <div style={{ textAlign: 'center', padding: '80px 0' }}>
          <Play size={48} color="var(--yt-primary)" style={{ opacity: 0.3, marginBottom: 16 }} />
          <p style={{ color: 'var(--text-muted)', fontSize: 14 }}>
            Select a YouTube channel above — or trigger an ingestion to add one.
          </p>
        </div>
      ) : (
        <>
          {/* ── Stat Cards ──────────────────────────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 14 }}>
            <StatCard title="Subscribers"  value={fmt(metrics?.subscriber_count)} icon={Users}   accent={ACCENT} loading={metricsLoading} />
            <StatCard title="Total Views"  value={fmt(metrics?.total_views)}       icon={Eye}     accent={ACCENT} loading={metricsLoading} />
            <StatCard title="Total Likes"  value={fmt(metrics?.total_likes)}       icon={ThumbsUp} accent={ACCENT} loading={metricsLoading} />
            <StatCard title="Total Videos" value={fmt(metrics?.total_videos)}      icon={Video}   accent={ACCENT} loading={metricsLoading} />
          </div>

          {/* ── Sentiment + Description ─────────────────────────────────── */}
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
            <div className="glass-card" style={{ padding: 20 }}>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 16 }}>
                Comment Sentiment Distribution
              </h3>
              <SentimentPie data={sentiment} loading={sentLoading} accent={ACCENT} />
            </div>

            <div className="glass-card" style={{ padding: 20 }}>
              <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 12 }}>
                Channel Info
              </h3>
              {metricsLoading ? (
                <>
                  <div className="skeleton" style={{ height: 12, width: '80%', marginBottom: 10 }} />
                  <div className="skeleton" style={{ height: 12, width: '60%', marginBottom: 10 }} />
                  <div className="skeleton" style={{ height: 12, width: '70%' }} />
                </>
              ) : (
                <>
                  <div style={{ marginBottom: 12 }}>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em', fontWeight: 600 }}>Channel ID</span>
                    <p style={{ fontSize: 13, color: 'var(--text-secondary)', fontFamily: 'monospace', marginTop: 4 }}>{metrics?.channel_id}</p>
                  </div>
                  <div style={{ marginBottom: 12 }}>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em', fontWeight: 600 }}>Last Ingested</span>
                    <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4 }}>
                      {metrics?.last_ingested_at ? new Date(metrics.last_ingested_at).toLocaleString() : '—'}
                    </p>
                  </div>
                  {metrics?.description && (
                    <div>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em', fontWeight: 600 }}>Description</span>
                      <p style={{ fontSize: 13, color: 'var(--text-secondary)', marginTop: 4, lineHeight: 1.5 }}>
                        {metrics.description.slice(0, 200)}{metrics.description.length > 200 ? '…' : ''}
                      </p>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>

          {/* ── Comments Table ───────────────────────────────────────────── */}
          <div className="glass-card" style={{ padding: 20 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', marginBottom: 16 }}>
              Recent Comments
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
