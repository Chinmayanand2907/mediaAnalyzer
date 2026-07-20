import { PieChart, Pie, Cell, Tooltip, Legend, ResponsiveContainer } from 'recharts';

const COLORS = {
  positive: '#22c55e',
  neutral:  '#f59e0b',
  negative: '#ef4444',
};

const CustomTooltip = ({ active, payload }) => {
  if (!active || !payload?.length) return null;
  const { name, value } = payload[0];
  return (
    <div className="custom-tooltip" style={{ background: '#1e1e2e', border: '1px solid var(--border-strong)', borderRadius: 8, padding: '10px 14px', fontSize: 13 }}>
      <span style={{ color: COLORS[name], fontWeight: 700, textTransform: 'capitalize' }}>{name}</span>
      <span style={{ color: 'var(--text-primary)', marginLeft: 8 }}>{(value * 100).toFixed(1)}%</span>
    </div>
  );
};

const CustomLegend = ({ payload }) => (
  <div style={{ display: 'flex', gap: 20, justifyContent: 'center', marginTop: 12 }}>
    {payload.map((entry) => (
      <div key={entry.value} style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
        <div style={{ width: 10, height: 10, borderRadius: '50%', background: entry.color }} />
        <span style={{ fontSize: 12, color: 'var(--text-secondary)', textTransform: 'capitalize' }}>{entry.value}</span>
      </div>
    ))}
  </div>
);

/**
 * SentimentPie — donut chart for positive/neutral/negative distribution.
 *
 * Props:
 *   data     { positive, neutral, negative, total_comments_analysed }
 *   loading  bool
 *   accent   string — outer ring color (platform accent)
 */
export default function SentimentPie({ data, loading, accent = 'var(--yt-primary)' }) {
  if (loading) {
    return (
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: 260 }}>
        <div className="skeleton" style={{ width: 180, height: 180, borderRadius: '50%' }} />
      </div>
    );
  }

  if (!data) return null;

  const chartData = [
    { name: 'positive', value: data.positive },
    { name: 'neutral',  value: data.neutral  },
    { name: 'negative', value: data.negative },
  ].filter((d) => d.value > 0);

  const dominant = data.dominant_label;

  return (
    <div>
      {/* Dominant label badge */}
      <div style={{ textAlign: 'center', marginBottom: 4 }}>
        <span style={{ fontSize: 11, fontWeight: 700, letterSpacing: '0.08em', textTransform: 'uppercase', color: 'var(--text-muted)' }}>
          Dominant Sentiment
        </span>
        <div style={{
          display: 'inline-block', marginLeft: 10,
          padding: '2px 10px', borderRadius: 20,
          fontSize: 12, fontWeight: 700, textTransform: 'capitalize',
          color: COLORS[dominant],
          background: `${COLORS[dominant]}18`,
          border: `1px solid ${COLORS[dominant]}30`,
        }}>
          {dominant}
        </div>
      </div>

      <ResponsiveContainer width="100%" height={240}>
        <PieChart>
          <Pie
            data={chartData}
            cx="50%" cy="50%"
            innerRadius={60} outerRadius={90}
            paddingAngle={3}
            dataKey="value"
            animationBegin={0}
            animationDuration={800}
          >
            {chartData.map((entry) => (
              <Cell key={entry.name} fill={COLORS[entry.name]} stroke="transparent" />
            ))}
          </Pie>
          <Tooltip content={<CustomTooltip />} />
          <Legend content={<CustomLegend />} />
        </PieChart>
      </ResponsiveContainer>

      <div style={{ textAlign: 'center', fontSize: 12, color: 'var(--text-muted)', marginTop: 4 }}>
        {data.total_comments_analysed?.toLocaleString()} comments analysed
      </div>
    </div>
  );
}
