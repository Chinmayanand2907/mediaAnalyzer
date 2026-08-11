import { Video, MessageCircle, BarChart3, ChevronDown, Zap } from 'lucide-react';
import { useState, useRef, useEffect } from 'react';

const PLATFORMS = [
  { value: 'youtube',        label: 'YouTube Analytics', icon: Video,  accent: 'var(--yt-primary)', color: 'yt' },
  { value: 'reddit',         label: 'Reddit Insights',   icon: MessageCircle,   accent: 'var(--rd-primary)', color: 'rd' },
  { value: 'cross-platform', label: 'Cross-Platform',    icon: BarChart3, accent: 'var(--cx-primary)', color: 'cx' },
];

export default function Navbar({ platform, onPlatformChange }) {
  const [open, setOpen] = useState(false);
  const dropRef = useRef(null);
  const active  = PLATFORMS.find((p) => p.value === platform) ?? PLATFORMS[0];
  const Icon    = active.icon;

  useEffect(() => {
    const handler = (e) => { if (!dropRef.current?.contains(e.target)) setOpen(false); };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, []);

  return (
    <nav
      style={{
        background: 'rgba(8,8,15,0.85)',
        borderBottom: '1px solid var(--border)',
        backdropFilter: 'blur(20px)',
        position: 'sticky',
        top: 0,
        zIndex: 50,
      }}
    >
      <div style={{ maxWidth: 1280, margin: '0 auto', padding: '0 24px', height: 64, display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>

        {/* ── Brand ─────────────────────────────────────────────────────── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{
            width: 34, height: 34, borderRadius: 10,
            background: 'linear-gradient(135deg, #6366f1, #06b6d4)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            boxShadow: '0 0 16px rgba(99,102,241,0.4)',
          }}>
            <Zap size={18} color="#fff" strokeWidth={2.5} />
          </div>
          <div>
            <span style={{ fontSize: 15, fontWeight: 700, color: 'var(--text-primary)', letterSpacing: '-0.02em' }}>
              EngageIQ
            </span>
            <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 6, fontWeight: 500 }}>
              Analytics
            </span>
          </div>
        </div>

        {/* ── Center Title ──────────────────────────────────────────────── */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <Icon size={16} color={active.accent} />
          <span style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-secondary)' }}>
            {active.label}
          </span>
        </div>

        {/* ── Platform Dropdown ─────────────────────────────────────────── */}
        <div ref={dropRef} style={{ position: 'relative' }}>
          <button
            onClick={() => setOpen((o) => !o)}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '8px 14px',
              background: 'rgba(255,255,255,0.05)',
              border: `1px solid ${open ? active.accent : 'var(--border-strong)'}`,
              borderRadius: 10,
              color: 'var(--text-primary)',
              fontSize: 13, fontWeight: 600,
              cursor: 'pointer',
              transition: 'all 0.2s',
              boxShadow: open ? `0 0 0 3px ${active.accent}28` : 'none',
            }}
          >
            <Icon size={15} color={active.accent} />
            <span>{active.label}</span>
            <ChevronDown
              size={14}
              color="var(--text-muted)"
              style={{ transform: open ? 'rotate(180deg)' : 'none', transition: 'transform 0.2s' }}
            />
          </button>

          {open && (
            <div style={{
              position: 'absolute', right: 0, top: 'calc(100% + 8px)',
              minWidth: 230,
              background: '#12121f',
              border: '1px solid var(--border-strong)',
              borderRadius: 12,
              boxShadow: '0 20px 48px rgba(0,0,0,0.6)',
              overflow: 'hidden',
              animation: 'fadeUp 0.15s ease',
              zIndex: 100,
            }}>
              {PLATFORMS.map((p) => {
                const PIcon = p.icon;
                const isActive = p.value === platform;
                return (
                  <button
                    key={p.value}
                    onClick={() => { onPlatformChange(p.value); setOpen(false); }}
                    style={{
                      width: '100%', textAlign: 'left',
                      display: 'flex', alignItems: 'center', gap: 12,
                      padding: '12px 16px',
                      background: isActive ? `${p.accent}18` : 'transparent',
                      border: 'none',
                      borderLeft: isActive ? `3px solid ${p.accent}` : '3px solid transparent',
                      color: isActive ? p.accent : 'var(--text-secondary)',
                      fontSize: 13, fontWeight: isActive ? 600 : 400,
                      cursor: 'pointer',
                      transition: 'all 0.15s',
                    }}
                    onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'rgba(255,255,255,0.04)'; }}
                    onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                  >
                    <PIcon size={16} color={p.accent} />
                    {p.label}
                  </button>
                );
              })}
            </div>
          )}
        </div>

      </div>
    </nav>
  );
}
