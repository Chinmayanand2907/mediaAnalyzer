import { useState, useRef, useEffect } from 'react';
import { MessageSquare, X, Send, Bot, User, Loader2, Sparkles } from 'lucide-react';

const CONTEXT_META = {
  youtube: {
    label: 'YouTube Analyst',
    accent: 'var(--yt-primary)',
    glow: 'rgba(99,102,241,0.35)',
    placeholder: 'Ask about views, sentiment, subscribers…',
    emoji: '📺',
  },
  reddit: {
    label: 'Reddit Specialist',
    accent: 'var(--rd-primary)',
    glow: 'rgba(244,63,94,0.35)',
    placeholder: 'Ask about upvotes, keywords, community trends…',
    emoji: '🔥',
  },
  'cross-platform': {
    label: 'Cross-Channel Strategist',
    accent: 'var(--cx-primary)',
    glow: 'rgba(6,182,212,0.35)',
    placeholder: 'Ask about content propagation, dual-platform strategy…',
    emoji: '🔗',
  },
};

function MessageBubble({ msg }) {
  const isUser = msg.role === 'user';
  return (
    <div
      style={{
        display: 'flex',
        flexDirection: isUser ? 'row-reverse' : 'row',
        alignItems: 'flex-start',
        gap: 8,
        marginBottom: 12,
        animation: 'fadeUp 0.25s ease',
      }}
    >
      {/* Avatar */}
      <div
        style={{
          flexShrink: 0,
          width: 28,
          height: 28,
          borderRadius: '50%',
          background: isUser
            ? 'rgba(255,255,255,0.08)'
            : 'linear-gradient(135deg, #6366f1, #06b6d4)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: isUser ? 'none' : '0 0 12px rgba(99,102,241,0.4)',
        }}
      >
        {isUser ? (
          <User size={13} color="var(--text-muted)" />
        ) : (
          <Bot size={13} color="#fff" />
        )}
      </div>

      {/* Bubble */}
      <div
        style={{
          maxWidth: '80%',
          padding: '10px 13px',
          borderRadius: isUser ? '14px 4px 14px 14px' : '4px 14px 14px 14px',
          background: isUser
            ? 'rgba(255,255,255,0.07)'
            : 'rgba(99,102,241,0.12)',
          border: `1px solid ${isUser ? 'rgba(255,255,255,0.08)' : 'rgba(99,102,241,0.22)'}`,
          fontSize: 13,
          lineHeight: 1.6,
          color: 'var(--text-primary)',
          whiteSpace: 'pre-wrap',
          wordBreak: 'break-word',
        }}
      >
        {msg.content}
      </div>
    </div>
  );
}

function TypingIndicator() {
  return (
    <div style={{ display: 'flex', alignItems: 'flex-start', gap: 8, marginBottom: 12 }}>
      <div style={{
        flexShrink: 0, width: 28, height: 28, borderRadius: '50%',
        background: 'linear-gradient(135deg, #6366f1, #06b6d4)',
        display: 'flex', alignItems: 'center', justifyContent: 'center',
      }}>
        <Bot size={13} color="#fff" />
      </div>
      <div style={{
        padding: '10px 14px',
        borderRadius: '4px 14px 14px 14px',
        background: 'rgba(99,102,241,0.12)',
        border: '1px solid rgba(99,102,241,0.22)',
        display: 'flex', alignItems: 'center', gap: 4,
      }}>
        {[0, 1, 2].map((i) => (
          <div key={i} style={{
            width: 6, height: 6, borderRadius: '50%',
            background: 'var(--yt-primary)',
            animation: `bounce 1.2s ${i * 0.2}s infinite ease-in-out`,
          }} />
        ))}
      </div>
    </div>
  );
}

export default function ChatBotPanel({ platform }) {
  const [open, setOpen] = useState(false);
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const bottomRef = useRef(null);
  const inputRef = useRef(null);

  const meta = CONTEXT_META[platform] ?? CONTEXT_META['youtube'];

  // Clear chat when platform switches
  useEffect(() => {
    setMessages([]);
    setError('');
  }, [platform]);

  // Auto-scroll to latest message
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, loading]);

  // Focus input when panel opens
  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 100);
  }, [open]);

  const sendMessage = async () => {
    const question = input.trim();
    if (!question || loading) return;

    setInput('');
    setError('');
    setMessages((prev) => [...prev, { role: 'user', content: question }]);
    setLoading(true);

    try {
      const res = await fetch('/api/v1/chatbot/query', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question, context: platform }),
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.detail || `Server error ${res.status}`);
      }

      const data = await res.json();
      setMessages((prev) => [...prev, { role: 'assistant', content: data.answer }]);
    } catch (err) {
      setError(err.message || 'Failed to reach the chatbot. Is the backend running?');
    } finally {
      setLoading(false);
    }
  };

  const handleKey = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendMessage();
    }
  };

  return (
    <>
      {/* ── Bounce animation keyframes ── */}
      <style>{`
        @keyframes bounce {
          0%, 80%, 100% { transform: translateY(0); }
          40%            { transform: translateY(-6px); }
        }
        @keyframes panelSlide {
          from { opacity: 0; transform: translateY(20px) scale(0.97); }
          to   { opacity: 1; transform: translateY(0)   scale(1);    }
        }
      `}</style>

      {/* ── Floating Chat Panel ── */}
      {open && (
        <div
          style={{
            position: 'fixed',
            bottom: 90,
            right: 24,
            width: 380,
            height: 560,
            display: 'flex',
            flexDirection: 'column',
            background: '#0e0e1c',
            border: '1px solid var(--border-strong)',
            borderRadius: 20,
            boxShadow: `0 24px 64px rgba(0,0,0,0.7), 0 0 0 1px rgba(255,255,255,0.04), 0 0 48px ${meta.glow}`,
            zIndex: 1000,
            overflow: 'hidden',
            animation: 'panelSlide 0.25s ease',
          }}
        >
          {/* Header */}
          <div style={{
            display: 'flex', alignItems: 'center', gap: 10,
            padding: '14px 16px',
            borderBottom: '1px solid var(--border)',
            background: 'rgba(255,255,255,0.02)',
            flexShrink: 0,
          }}>
            <div style={{
              width: 34, height: 34, borderRadius: 10,
              background: 'linear-gradient(135deg, #6366f1, #06b6d4)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              boxShadow: `0 0 16px ${meta.glow}`,
            }}>
              <Sparkles size={16} color="#fff" />
            </div>
            <div style={{ flex: 1, minWidth: 0 }}>
              <div style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
                AI Analyst
                <span style={{
                  fontSize: 9, fontWeight: 700, letterSpacing: '0.05em',
                  padding: '2px 6px', borderRadius: 5,
                  background: 'rgba(34,197,94,0.15)',
                  border: '1px solid rgba(34,197,94,0.35)',
                  color: '#22c55e',
                }}>LIVE DATA</span>
              </div>
              <div style={{
                fontSize: 11, color: meta.accent, fontWeight: 600,
                display: 'flex', alignItems: 'center', gap: 4,
              }}>
                <span style={{
                  width: 6, height: 6, borderRadius: '50%',
                  background: meta.accent, display: 'inline-block',
                  boxShadow: `0 0 6px ${meta.accent}`,
                }} />
                {meta.emoji} {meta.label}
              </div>
            </div>
            <button
              onClick={() => setOpen(false)}
              style={{
                background: 'rgba(255,255,255,0.05)',
                border: '1px solid var(--border)',
                borderRadius: 8,
                padding: 6,
                cursor: 'pointer',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: 'var(--text-muted)',
                transition: 'all 0.15s',
              }}
              onMouseEnter={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.1)'}
              onMouseLeave={(e) => e.currentTarget.style.background = 'rgba(255,255,255,0.05)'}
            >
              <X size={15} />
            </button>
          </div>

          {/* Message Area */}
          <div style={{ flex: 1, overflowY: 'auto', padding: '16px 14px' }}>
            {messages.length === 0 && (
              <div style={{
                height: '100%', display: 'flex', flexDirection: 'column',
                alignItems: 'center', justifyContent: 'center',
                color: 'var(--text-muted)', textAlign: 'center',
                gap: 12, padding: '0 20px',
              }}>
                <div style={{ fontSize: 36 }}>{meta.emoji}</div>
                <div style={{ fontSize: 14, fontWeight: 600, color: 'var(--text-secondary)' }}>
                  {meta.label}
                </div>
                <div style={{ fontSize: 12, lineHeight: 1.6 }}>
                  Ask me anything about your {platform === 'cross-platform' ? 'cross-platform' : platform} data.
                  I'll give you strategic, data-informed insights.
                </div>
              </div>
            )}
            {messages.map((msg, i) => (
              <MessageBubble key={i} msg={msg} />
            ))}
            {loading && <TypingIndicator />}
            {error && (
              <div style={{
                padding: '10px 13px', borderRadius: 10, marginBottom: 10,
                background: 'rgba(239,68,68,0.1)', border: '1px solid rgba(239,68,68,0.25)',
                fontSize: 12, color: '#ef4444', lineHeight: 1.5,
              }}>
                ⚠️ {error}
              </div>
            )}
            <div ref={bottomRef} />
          </div>

          {/* Input Area */}
          <div style={{
            padding: '12px 12px 14px',
            borderTop: '1px solid var(--border)',
            background: 'rgba(255,255,255,0.02)',
            flexShrink: 0,
          }}>
            <div style={{
              display: 'flex', gap: 8,
              background: 'rgba(255,255,255,0.05)',
              border: `1px solid ${input ? meta.accent + '55' : 'var(--border-strong)'}`,
              borderRadius: 12,
              padding: '8px 8px 8px 12px',
              transition: 'border-color 0.2s',
            }}>
              <textarea
                ref={inputRef}
                rows={1}
                value={input}
                onChange={(e) => {
                  setInput(e.target.value);
                  // Auto-resize
                  e.target.style.height = 'auto';
                  e.target.style.height = Math.min(e.target.scrollHeight, 80) + 'px';
                }}
                onKeyDown={handleKey}
                placeholder={meta.placeholder}
                disabled={loading}
                style={{
                  flex: 1,
                  background: 'transparent',
                  border: 'none',
                  outline: 'none',
                  resize: 'none',
                  color: 'var(--text-primary)',
                  fontSize: 13,
                  lineHeight: 1.5,
                  fontFamily: 'inherit',
                  overflowY: 'hidden',
                }}
              />
              <button
                onClick={sendMessage}
                disabled={!input.trim() || loading}
                style={{
                  flexShrink: 0,
                  alignSelf: 'flex-end',
                  width: 32, height: 32,
                  borderRadius: 9,
                  background: !input.trim() || loading
                    ? 'rgba(255,255,255,0.05)'
                    : `linear-gradient(135deg, ${meta.accent}, #06b6d4)`,
                  border: 'none',
                  cursor: !input.trim() || loading ? 'not-allowed' : 'pointer',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  transition: 'all 0.2s',
                  boxShadow: !input.trim() || loading ? 'none' : `0 0 12px ${meta.glow}`,
                }}
              >
                {loading
                  ? <Loader2 size={14} color="var(--text-muted)" style={{ animation: 'spin 1s linear infinite' }} />
                  : <Send size={14} color={!input.trim() ? 'var(--text-muted)' : '#fff'} />
                }
              </button>
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 6, textAlign: 'center' }}>
            <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
              <span style={{ width: 5, height: 5, borderRadius: '50%', background: '#22c55e', boxShadow: '0 0 4px #22c55e', display: 'inline-block' }} />
              Live DB data · Groq LLaMA 3.3 70B · Enter to send
            </span>
            </div>
          </div>
        </div>
      )}

      {/* ── Toggle FAB Button ── */}
      <button
        onClick={() => setOpen((o) => !o)}
        title="Open AI Analyst"
        style={{
          position: 'fixed',
          bottom: 24,
          right: 24,
          width: 56,
          height: 56,
          borderRadius: '50%',
          background: open
            ? 'rgba(255,255,255,0.08)'
            : 'linear-gradient(135deg, #6366f1, #06b6d4)',
          border: open ? '1px solid var(--border-strong)' : 'none',
          cursor: 'pointer',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          boxShadow: open
            ? 'none'
            : '0 4px 24px rgba(99,102,241,0.5), 0 0 0 0 rgba(99,102,241,0)',
          zIndex: 1001,
          transition: 'all 0.3s cubic-bezier(0.34, 1.56, 0.64, 1)',
          transform: open ? 'rotate(0deg)' : 'rotate(0deg)',
        }}
        onMouseEnter={(e) => { if (!open) e.currentTarget.style.transform = 'scale(1.1)'; }}
        onMouseLeave={(e) => { e.currentTarget.style.transform = 'scale(1)'; }}
      >
        {open
          ? <X size={22} color="var(--text-primary)" />
          : <MessageSquare size={22} color="#fff" />
        }
      </button>

      {/* Unread dot when closed */}
      {!open && messages.length > 0 && (
        <div style={{
          position: 'fixed', bottom: 70, right: 20,
          width: 10, height: 10, borderRadius: '50%',
          background: meta.accent,
          border: '2px solid #0e0e1c',
          zIndex: 1002,
          boxShadow: `0 0 8px ${meta.accent}`,
        }} />
      )}
    </>
  );
}
