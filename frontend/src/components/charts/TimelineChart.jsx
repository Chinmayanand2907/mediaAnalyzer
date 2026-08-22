import {
  LineChart, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer,
} from 'recharts';
import { Clock, Zap } from 'lucide-react';

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  const extra = payload[0]?.payload;
  return (
    <div style={{
      background: '#1e1e2e',
      border: '1px solid var(--border-strong)',
      borderRadius: 8,
      padding: '10px 14px',
      fontSize: 13,
      boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
    }}>
      <div style={{ color: 'var(--text-primary)', fontWeight: 700, marginBottom: 6, fontSize: 12 }}>
        {extra?.fullTitle || label}
      </div>
      {extra?.delay != null && (
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: 6,
          fontSize: 11,
          color: 'var(--cx-primary)',
          fontWeight: 600,
          marginBottom: 8,
          padding: '2px 6px',
          background: 'rgba(6,182,212,0.12)',
          borderRadius: 4,
          width: 'fit-content',
        }}>
          <Clock size={11} />
          {extra.delay > 0 ? `Propagation Lag: ${extra.delay}h` : 'Instant / Same-Day'}
          {extra.speed ? ` (${extra.speed})` : ''}
        </div>
      )}
      {payload.map((p) => (
        <div key={p.dataKey} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
          <div style={{ width: 8, height: 8, borderRadius: 2, background: p.color }} />
          <span style={{ color: 'var(--text-secondary)' }}>{p.name}:</span>
          <span style={{ color: 'var(--text-primary)', fontWeight: 700 }}>
            {p.value?.toLocaleString()}
          </span>
        </div>
      ))}
      {extra?.firstShared && (
        <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6, borderTop: '1px solid var(--border)', paddingTop: 4 }}>
          Reddit First Shared: {new Date(extra.firstShared).toLocaleDateString()}
        </div>
      )}
    </div>
  );
};

/**
 * TimelineChart — dual-axis LineChart mapping YouTube views against Reddit comment counts with propagation metrics.
 */
export default function TimelineChart({ data, loading }) {
  if (loading) {
    return (
      <div className="skeleton" style={{ height: 280, borderRadius: 12 }} />
    );
  }

  if (!data?.length) {
    return (
      <div style={{ height: 280, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
        Enter a subreddit name above to scan and load cross-platform timeline.
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
          <XAxis
            dataKey="label"
            tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            interval="preserveStartEnd"
            tickFormatter={(v) => (v && v.length > 14 ? v.slice(0, 14) + '…' : v)}
          />
          {/* Left Y-axis — YouTube views */}
          <YAxis
            yAxisId="yt"
            orientation="left"
            tick={{ fill: '#6366f1', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
            tickFormatter={(v) => (v >= 1000 ? `${(v / 1000).toFixed(0)}K` : v)}
          />
          {/* Right Y-axis — Reddit comments */}
          <YAxis
            yAxisId="rd"
            orientation="right"
            tick={{ fill: '#f43f5e', fontSize: 11 }}
            axisLine={false}
            tickLine={false}
          />
          <Tooltip content={<CustomTooltip />} />
          <Legend
            formatter={(value) => <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{value}</span>}
          />
          <Line
            yAxisId="yt"
            type="monotone"
            dataKey="youtube_views"
            name="YouTube Views"
            stroke="#6366f1"
            strokeWidth={2.5}
            dot={{ r: 4, fill: '#6366f1', stroke: '#08080f', strokeWidth: 2 }}
            activeDot={{ r: 6 }}
            animationDuration={800}
          />
          <Line
            yAxisId="rd"
            type="monotone"
            dataKey="reddit_comments"
            name="Reddit Discussion Comments"
            stroke="#f43f5e"
            strokeWidth={2.5}
            dot={{ r: 4, fill: '#f43f5e', stroke: '#08080f', strokeWidth: 2 }}
            activeDot={{ r: 6 }}
            animationDuration={800}
            animationBegin={200}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
