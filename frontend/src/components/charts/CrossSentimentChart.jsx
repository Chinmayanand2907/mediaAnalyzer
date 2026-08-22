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
import { MessageSquare, ThumbsUp, Scale, AlertCircle } from 'lucide-react';

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

export default function CrossSentimentChart({ data, loading }) {
  if (loading) {
    return (
      <div className="skeleton" style={{ height: 280, borderRadius: 12 }} />
    );
  }

  const yt = data?.youtube_sentiment || { positive: 0, neutral: 0, negative: 0, sample_size: 0 };
  const rd = data?.reddit_sentiment || { positive: 0, neutral: 0, negative: 0, sample_size: 0 };
  const gap = data?.sentiment_gap ?? (yt.positive - rd.positive);
  const summary = data?.audience_response_summary || (
    yt.sample_size === 0 && rd.sample_size === 0
      ? 'No audience comment sentiment recorded yet for this topic. Ingest or search comments to see live contrast.'
      : 'Audience response comparison across YouTube and Reddit community discussions.'
  );

  const hasData = (yt.sample_size || 0) > 0 || (rd.sample_size || 0) > 0 || yt.positive > 0 || rd.positive > 0;

  const chartData = [
    {
      category: 'Positive',
      youtube: yt.positive || 0,
      reddit: rd.positive || 0,
    },
    {
      category: 'Neutral',
      youtube: yt.neutral || 0,
      reddit: rd.neutral || 0,
    },
    {
      category: 'Negative',
      youtube: yt.negative || 0,
      reddit: rd.negative || 0,
    },
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
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>
              Audience Response Contrast
            </span>
            {hasData && (
              <span style={{
                fontSize: 11,
                fontWeight: 800,
                padding: '2px 8px',
                borderRadius: 12,
                background: gap > 0 ? 'rgba(99,102,241,0.18)' : gap < 0 ? 'rgba(244,63,94,0.18)' : 'rgba(255,255,255,0.08)',
                color: gap > 0 ? 'var(--yt-primary)' : gap < 0 ? 'var(--rd-primary)' : 'var(--text-secondary)',
              }}>
                {gap > 0 ? `+${(gap * 100).toFixed(0)}% YouTube Positive Lead` : gap < 0 ? `+${(Math.abs(gap) * 100).toFixed(0)}% Reddit Sentiment Lead` : '0% Sentiment Gap'}
              </span>
            )}
          </div>
          <p style={{ fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.45 }}>
            {summary}
          </p>
        </div>
      </div>

      {/* ── Comparative Bar Chart ── */}
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
              domain={[0, 1]}
            />
            <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
            <Legend
              formatter={(value) => (
                <span style={{ fontSize: 12, color: 'var(--text-secondary)', marginRight: 14 }}>
                  {value}
                </span>
              )}
            />
            <Bar
              dataKey="youtube"
              name="YouTube Audience Sentiment"
              fill="#6366f1"
              radius={[4, 4, 0, 0]}
              maxBarSize={36}
            />
            <Bar
              dataKey="reddit"
              name="Reddit Community Sentiment"
              fill="#f43f5e"
              radius={[4, 4, 0, 0]}
              maxBarSize={36}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>

      {/* ── Quick Stats Footer ── */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
        <div style={{
          padding: '10px 14px',
          borderRadius: 8,
          background: 'rgba(99,102,241,0.08)',
          border: '1px solid rgba(99,102,241,0.2)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--yt-primary)', fontWeight: 600 }}>YouTube Audience</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text-primary)' }}>
              {(yt.positive * 100).toFixed(0)}% Positive
            </div>
          </div>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {(yt.negative * 100).toFixed(0)}% Neg
          </span>
        </div>

        <div style={{
          padding: '10px 14px',
          borderRadius: 8,
          background: 'rgba(244,63,94,0.08)',
          border: '1px solid rgba(244,63,94,0.2)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}>
          <div>
            <div style={{ fontSize: 11, color: 'var(--rd-primary)', fontWeight: 600 }}>Reddit Community</div>
            <div style={{ fontSize: 16, fontWeight: 800, color: 'var(--text-primary)' }}>
              {(rd.positive * 100).toFixed(0)}% Positive
            </div>
          </div>
          <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>
            {(rd.negative * 100).toFixed(0)}% Neg
          </span>
        </div>
      </div>
    </div>
  );
}
