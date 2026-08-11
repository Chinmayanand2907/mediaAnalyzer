import {
  ComposedChart, Bar, Line, XAxis, YAxis, CartesianGrid,
  Tooltip, Legend, ResponsiveContainer, Cell,
} from 'recharts';

const PLATFORM_COLORS = { youtube: '#6366f1', reddit: '#f43f5e' };

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div style={{ background: '#1e1e2e', border: '1px solid var(--border-strong)', borderRadius: 8, padding: '10px 14px', fontSize: 13 }}>
      <div style={{ color: 'var(--text-muted)', marginBottom: 6, fontSize: 11 }}>{label}</div>
      {payload.map((p) => (
        <div key={p.dataKey} style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
          <div style={{ width: 8, height: 8, borderRadius: '50%', background: p.color }} />
          <span style={{ color: 'var(--text-secondary)', textTransform: 'capitalize' }}>{p.name}</span>
          <span style={{ color: 'var(--text-primary)', fontWeight: 700 }}>{(+(p.value ?? 0)).toFixed(1)}</span>
        </div>
      ))}
    </div>
  );
};

/**
 * EngagementBar — dual-axis ComposedChart comparing YouTube vs Reddit engagement scores.
 *
 * Props:
 *   data     PlatformEngagementComparison[]  — from /cross-platform/engagement-comparison
 *   loading  bool
 */
export default function EngagementBar({ data, loading }) {
  if (loading) {
    return (
      <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end', height: 260, padding: '0 10px' }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="skeleton" style={{ flex: 1, height: `${40 + Math.random() * 60}%`, borderRadius: '4px 4px 0 0' }} />
        ))}
      </div>
    );
  }

  if (!data?.length) return (
    <div style={{ height: 260, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
      No engagement data — run ingestion first.
    </div>
  );

  // Build chart-friendly data: one entry per tracked account
  const chartData = data.map((item) => ({
    name: item.raw_engagement?.display_name ?? item.raw_engagement?.account_id ?? 'Unknown',
    score: item.normalised_score,
    platform: item.platform,
  }));

  return (
    <ResponsiveContainer width="100%" height={260}>
      <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 0 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.05)" vertical={false} />
        <XAxis
          dataKey="name"
          tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
          axisLine={false} tickLine={false}
          interval={0}
          tickFormatter={(v) => v.length > 12 ? v.slice(0, 12) + '…' : v}
        />
        <YAxis
          tick={{ fill: 'var(--text-muted)', fontSize: 11 }}
          axisLine={false} tickLine={false}
          domain={[0, 100]}
          tickFormatter={(v) => `${v}`}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(255,255,255,0.04)' }} />
        <Legend
          formatter={(value) => <span style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{value}</span>}
        />
        <Bar dataKey="score" name="Engagement Score" radius={[4, 4, 0, 0]} maxBarSize={40}>
          {chartData.map((entry, i) => (
            <Cell key={i} fill={PLATFORM_COLORS[entry.platform] ?? '#6366f1'} />
          ))}
        </Bar>
        <Line
          dataKey="score"
          name="Trend"
          type="monotone"
          stroke="#06b6d4"
          strokeWidth={2}
          dot={false}
          strokeDasharray="4 2"
        />
      </ComposedChart>
    </ResponsiveContainer>
  );
}
