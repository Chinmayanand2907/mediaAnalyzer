import { TrendingUp, TrendingDown, Minus } from 'lucide-react';

/**
 * StatCard — reusable metric card.
 *
 * Props:
 *   title    string       — label above the value
 *   value    string|num   — primary display value
 *   sub      string       — secondary line (e.g. "last 7 days")
 *   icon     LucideIcon   — icon component
 *   accent   string       — CSS color string for icon + glow
 *   trend    number|null  — positive = up, negative = down, 0 = flat
 *   loading  bool
 */
export default function StatCard({ title, value, sub, icon: Icon, accent = 'var(--yt-primary)', trend = null, loading = false }) {
  const TrendIcon = trend > 0 ? TrendingUp : trend < 0 ? TrendingDown : Minus;
  const trendColor = trend > 0 ? 'var(--positive)' : trend < 0 ? 'var(--negative)' : 'var(--text-muted)';

  if (loading) {
    return (
      <div className="glass-card" style={{ padding: 20 }}>
        <div className="skeleton" style={{ height: 12, width: '50%', marginBottom: 12 }} />
        <div className="skeleton" style={{ height: 28, width: '70%', marginBottom: 8 }} />
        <div className="skeleton" style={{ height: 10, width: '40%' }} />
      </div>
    );
  }

  return (
    <div
      className="glass-card fade-up"
      style={{ padding: 20, position: 'relative', overflow: 'hidden' }}
    >
      {/* Subtle corner glow */}
      <div style={{
        position: 'absolute', top: -30, right: -30,
        width: 100, height: 100, borderRadius: '50%',
        background: accent, opacity: 0.07, filter: 'blur(24px)',
        pointerEvents: 'none',
      }} />

      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.07em' }}>
          {title}
        </span>
        {Icon && (
          <div style={{
            width: 32, height: 32, borderRadius: 8,
            background: `${accent}18`,
            display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            <Icon size={16} color={accent} />
          </div>
        )}
      </div>

      {/* Primary value */}
      <div style={{ fontSize: 26, fontWeight: 800, color: 'var(--text-primary)', letterSpacing: '-0.03em', lineHeight: 1.1, marginBottom: 6 }}>
        {value ?? '—'}
      </div>

      {/* Sub + trend */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        {sub && <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{sub}</span>}
        {trend !== null && (
          <span style={{ display: 'flex', alignItems: 'center', gap: 3, fontSize: 12, fontWeight: 600, color: trendColor }}>
            <TrendIcon size={12} />
            {Math.abs(trend)}%
          </span>
        )}
      </div>
    </div>
  );
}
