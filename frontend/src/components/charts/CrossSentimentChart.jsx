import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
} from 'recharts';
import { Scale } from 'lucide-react';

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{
      background: '#1e1e2e',
      border: '1px solid var(--border-strong)',
      borderRadius: 8,
      padding: '10px 14px',
      fontSize: 13,
      boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
    }}>
      <div style={{ color: 'var(--text-muted)', marginBottom: 6, fontSize: 11, fontWeight: 700 }}>
        {label} Sentiment
      </div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
          <div style={{ width: 8, height: 8, borderRadius: 2, background: p.fill }} />
          <span style={{ color: 'var(--text-secondary)' }}>{p.name}:</span>
          <span style={{ color: 'var(--text-primary)', fontWeight: 700 }}>
            {((p.value ?? 0) * 100).toFixed(1)}%
          </span>
        </div>
      ))}
    </div>
  );
};

// ── Mini 3-segment bar for stat footer ───────────────────────────────────────
function SentimentMiniBar({ positive, neutral, negative }) {
  const pos = Math.round(positive * 100);
  const neu = Math.round(neutral * 100);
  const neg = Math.round(negative * 100);
  return (
    <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', height: 5, borderRadius: 3, overflow: 'hidden', gap: 1 }}>
        <div style={{ flex: pos, background: 'var(--positive)', minWidth: pos > 0 ? 2 : 0 }} />
        <div style={{ flex: neu, background: 'var(--neutral)', minWidth: neu > 0 ? 2 : 0 }} />
        <div style={{ flex: neg, background: 'var(--negative)', minWidth: neg > 0 ? 2 : 0 }} />
      </div>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: 'var(--text-muted)' }}>
        <span style={{ color: 'var(--positive)', fontWeight: 600 }}>{pos}% pos</span>
        <span>{neu}% neu</span>
        <span style={{ color: 'var(--negative)', fontWeight: 600 }}>{neg}% neg</span>
      </div>
    </div>
  );
}

export default function CrossSentimentChart({ data, loading }) {
  if (loading) {
    return (
      <div className="skeleton" style={{ height: 280, borderRadius: 12 }} />
    );
  }

  const yt = data?.youtube_sentiment || { positive: 0, neutral: 0, negative: 0, sample_size: 0 };
  const rd = data?.reddit_sentiment  || { positive: 0, neutral: 0, negative: 0, sample_size: 0 };
  const gap     = data?.sentiment_gap ?? (yt.positive - rd.positive);
  const absGap  = Math.abs(gap);
  const summary = data?.audience_response_summary || (
    yt.sample_size === 0 && rd.sample_size === 0
      ? 'No audience comment sentiment recorded yet for this topic. Ingest or search comments to see live contrast.'
      : 'Audience response comparison across YouTube and Reddit community discussions.'
  );

  const hasData = (yt.sample_size || 0) > 0 || (rd.sample_size || 0) > 0 || yt.positive > 0 || rd.positive > 0;

  // ── Divergence classification ─────────────────────────────────────────────
  const divergence = absGap < 0.05
    ? { label: '✓ Highly Aligned',       bg: 'rgba(34,197,94,0.14)',  border: 'rgba(34,197,94,0.3)',  color: '#22c55e' }
    : absGap < 0.20
    ? { label: '~ Moderately Divergent', bg: 'rgba(245,158,11,0.14)', border: 'rgba(245,158,11,0.3)', color: '#f59e0b' }
    : { label: '⚠ Strongly Polarized',  bg: 'rgba(239,68,68,0.14)',  border: 'rgba(239,68,68,0.3)',  color: '#ef4444' };

  const chartData = [
    { category: 'Positive', youtube: yt.positive || 0, reddit: rd.positive || 0 },
    { category: 'Neutral',  youtube: yt.neutral  || 0, reddit: rd.neutral  || 0 },
    { category: 'Negative', youtube: yt.negative || 0, reddit: rd.negative || 0 },
  ];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>

      {/* ── Disparity Insight Banner ── */}
      <div style={{
        padding: '14px 18px',
        borderRadius: 10,
        background: 'rgba(6,182,212,0.06)',
        border: '1px solid rgba(6,182,212,0.2)',
        display: 'flex',
        alignItems: 'flex-start',
        gap: 12,
      }}>
        <Scale size={20} color="var(--cx-primary)" style={{ flexShrink: 0, marginTop: 2 }} />
        <div style={{ flex: 1 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
              Audience Response Contrast
            </span>

            {/* P1: Sentiment gap badge (original) */}
            {hasData && (
              <span style={{
                fontSize: 11, fontWeight: 800,
                padding: '2px 8px', borderRadius: 12,
                background: gap > 0 ? 'rgba(99,102,241,0.18)' : gap < 0 ? 'rgba(244,63,94,0.18)' : 'rgba(255,255,255,0.08)',
                color:      gap > 0 ? 'var(--yt-primary)'     : gap < 0 ? 'var(--rd-primary)'     : 'var(--text-secondary)',
              }}>
                {gap > 0
                  ? `+${(gap * 100).toFixed(0)}% YouTube Positive Lead`
                  : gap < 0
                  ? `+${(absGap * 100).toFixed(0)}% Reddit Sentiment Lead`
                  : '0% Sentiment Gap'}
              </span>
            )}

            {/* P1: Divergence score badge */}
            {hasData && (
              <span style={{
                fontSize: 11, fontWeight: 800,
                padding: '2px 10px', borderRadius: 12,
                background: divergence.bg,
                border: `1px solid ${divergence.border}`,
                color: divergence.color,
                letterSpacing: '0.02em',
              }}>
                {divergence.label}
              </span>
            )}
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.45 }}>
            {summary}
          </p>
        </div>
      </div>

      {/* ── Chart or Empty State ── */}
      {hasData ? (
        <div style={{ height: 260, width: '100%' }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 10, right: 10, left: -15, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
              <XAxis
                dataKey="category"
                tick={{ fill: 'var(--text-muted)', fontSize: 12 }}
                axisLine={false}
                tickLine={false}
              />
              <YAxis
                tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
                axisLine={false}
                tickLine={false}
                tickFormatter={(v) => `${(v * 100).toFixed(0)}%`}
                domain={[0, 'auto']}
              />
              <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
              <Legend
                formatter={(value) => (
                  <span style={{ fontSize: 12, color: 'var(--text-secondary)', marginRight: 14 }}>
                    {value}
                  </span>
                )}
              />
              <Bar dataKey="youtube" name="YouTube Audience"  fill="#6366f1" radius={[4, 4, 0, 0]} maxBarSize={36} />
              <Bar dataKey="reddit"  name="Reddit Community"  fill="#f43f5e" radius={[4, 4, 0, 0]} maxBarSize={36} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      ) : (
        /* P0: Polished empty state — replaces ghost chart */
        <div style={{
          height: 220,
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          borderRadius: 10,
          background: 'rgba(255,255,255,0.02)',
          border: '1px dashed rgba(255,255,255,0.08)',
        }}>
          <Scale size={36} color="rgba(6,182,212,0.25)" />
          <div style={{ textAlign: 'center' }}>
            <div style={{ fontSize: 14, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 6 }}>
              No Sentiment Data Yet
            </div>
            <div style={{ fontSize: 12, color: 'var(--text-muted)', maxWidth: 340, lineHeight: 1.6 }}>
              Scan a subreddit or analyze a specific video above to see how YouTube audiences and Reddit communities emotionally respond to the same content.
            </div>
          </div>
        </div>
      )}

      {/* ── Quick Stats Footer ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        {/* YouTube */}
        <div style={{
          padding: '12px 16px', borderRadius: 8,
          background: 'rgba(99,102,241,0.08)', border: '1px solid rgba(99,102,241,0.2)',
        }}>
          <div style={{ fontSize: 11, color: 'var(--yt-primary)', fontWeight: 600, marginBottom: 2 }}>YouTube Audience</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-primary)' }}>
            {(yt.positive * 100).toFixed(0)}% Positive
          </div>
          <SentimentMiniBar positive={yt.positive} neutral={yt.neutral} negative={yt.negative} />
        </div>

        {/* Reddit */}
        <div style={{
          padding: '12px 16px', borderRadius: 8,
          background: 'rgba(244,63,94,0.08)', border: '1px solid rgba(244,63,94,0.2)',
        }}>
          <div style={{ fontSize: 11, color: 'var(--rd-primary)', fontWeight: 600, marginBottom: 2 }}>Reddit Community</div>
          <div style={{ fontSize: 18, fontWeight: 800, color: 'var(--text-primary)' }}>
            {(rd.positive * 100).toFixed(0)}% Positive
          </div>
          <SentimentMiniBar positive={rd.positive} neutral={rd.neutral} negative={rd.negative} />
        </div>
      </div>
    </div>
  );
}
