import { useState } from 'react';
import { ChevronLeft, ChevronRight } from 'lucide-react';

const SENTIMENT_COLORS = { positive: 'badge-positive', neutral: 'badge-neutral', negative: 'badge-negative' };

/**
 * CommentsTable — paginated, sentiment-annotated comment list.
 *
 * Props:
 *   fetchFn      async (page, filter) => CommentSentimentItem[]
 *   comments     CommentSentimentItem[]  — current page data
 *   loading      bool
 *   page         number
 *   onPageChange (newPage: number) => void
 *   onFilter     (label: string|null) => void
 *   activeFilter string|null
 */
export default function CommentsTable({ comments, loading, page, onPageChange, onFilter, activeFilter }) {
  const FILTERS = [null, 'positive', 'neutral', 'negative'];

  return (
    <div>
      {/* Filter Pills */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 16, flexWrap: 'wrap' }}>
        {FILTERS.map((f) => (
          <button
            key={f ?? 'all'}
            onClick={() => onFilter(f)}
            style={{
              padding: '5px 14px',
              borderRadius: 20,
              fontSize: 12, fontWeight: 600,
              cursor: 'pointer',
              border: '1px solid',
              transition: 'all 0.15s',
              borderColor: activeFilter === f ? (
                f === 'positive' ? 'var(--positive)' :
                f === 'negative' ? 'var(--negative)' :
                f === 'neutral'  ? 'var(--neutral)' : 'var(--border-strong)'
              ) : 'var(--border)',
              background: activeFilter === f ? (
                f === 'positive' ? 'rgba(34,197,94,0.12)' :
                f === 'negative' ? 'rgba(239,68,68,0.12)' :
                f === 'neutral'  ? 'rgba(245,158,11,0.12)' : 'rgba(255,255,255,0.06)'
              ) : 'transparent',
              color: activeFilter === f ? (
                f === 'positive' ? 'var(--positive)' :
                f === 'negative' ? 'var(--negative)' :
                f === 'neutral'  ? 'var(--neutral)' : 'var(--text-primary)'
              ) : 'var(--text-muted)',
            }}
          >
            {f ? f.charAt(0).toUpperCase() + f.slice(1) : 'All'}
          </button>
        ))}
      </div>

      {/* Table */}
      <div style={{ overflowX: 'auto', borderRadius: 10, border: '1px solid var(--border)' }}>
        {loading ? (
          <div style={{ padding: 20 }}>
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="skeleton" style={{ height: 14, marginBottom: 12, width: `${70 + Math.random() * 25}%` }} />
            ))}
          </div>
        ) : !comments?.length ? (
          <div style={{ padding: 32, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
            No comments found{activeFilter ? ` with sentiment: ${activeFilter}` : ''}.
          </div>
        ) : (
          <table className="dash-table">
            <thead>
              <tr>
                <th>Author</th>
                <th>Comment</th>
                <th>Sentiment</th>
                <th>Score</th>
                <th>Engine</th>
              </tr>
            </thead>
            <tbody>
              {comments.map((c) => (
                <tr key={c.comment_id}>
                  <td style={{ color: 'var(--text-primary)', fontWeight: 500, whiteSpace: 'nowrap' }}>
                    {c.author}
                  </td>
                  <td style={{ maxWidth: 380, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.body}
                  </td>
                  <td>
                    <span className={`${SENTIMENT_COLORS[c.sentiment_label] ?? ''}`} style={{
                      padding: '3px 10px', borderRadius: 12, fontSize: 11, fontWeight: 700,
                      textTransform: 'capitalize',
                    }}>
                      {c.sentiment_label}
                    </span>
                  </td>
                  <td style={{ fontVariantNumeric: 'tabular-nums', color: 'var(--text-secondary)' }}>
                    {c.sentiment_score?.toFixed(3)}
                  </td>
                  <td style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'monospace' }}>
                    {c.engine}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Pagination */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: 8, marginTop: 12 }}>
        <button
          onClick={() => onPageChange(page - 1)}
          disabled={page <= 1}
          style={{
            padding: '6px 10px', borderRadius: 8,
            border: '1px solid var(--border)', background: 'transparent',
            color: page <= 1 ? 'var(--text-muted)' : 'var(--text-primary)',
            cursor: page <= 1 ? 'not-allowed' : 'pointer',
          }}
        >
          <ChevronLeft size={14} />
        </button>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Page {page}</span>
        <button
          onClick={() => onPageChange(page + 1)}
          disabled={!comments?.length || comments.length < 20}
          style={{
            padding: '6px 10px', borderRadius: 8,
            border: '1px solid var(--border)', background: 'transparent',
            color: (!comments?.length || comments.length < 20) ? 'var(--text-muted)' : 'var(--text-primary)',
            cursor: (!comments?.length || comments.length < 20) ? 'not-allowed' : 'pointer',
          }}
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}
