import React, { useState } from 'react';

/**
 * ErrorBoundary — catches render/lifecycle errors in its child tree and
 * displays a recoverable fallback instead of letting React unmount the
 * entire application (which would leave a completely blank page).
 */
class ErrorBoundaryImpl extends React.Component {
  state = { hasError: false, error: null, errorInfo: null };

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('[ErrorBoundary] caught error:', error, errorInfo);
    this.setState({ errorInfo });
  }

  reset = () => this.setState({ hasError: false, error: null, errorInfo: null });

  render() {
    if (this.state.hasError) {
      if (typeof this.props.fallback === 'function') {
        return this.props.fallback({
          error: this.state.error,
          errorInfo: this.state.errorInfo,
          reset: this.reset,
        });
      }
      const componentStack = this.state.errorInfo?.componentStack ?? '';
      return (
        <div style={{
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center',
          minHeight: '60vh', textAlign: 'center', padding: 24, color: 'var(--text-secondary)',
        }}>
          <div style={{ fontSize: 36, marginBottom: 8 }}>⚠️</div>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8, color: 'var(--text-primary)' }}>
            Something went wrong
          </div>
          <div style={{ fontSize: 13, marginBottom: 16, maxWidth: 420, lineHeight: 1.5, color: 'var(--text-muted)' }}>
            {this.state.error?.message || String(this.state.error)}
          </div>
          {componentStack && (
            <details style={{ marginBottom: 16, textAlign: 'left', width: '100%', maxWidth: 420 }}>
              <summary style={{ cursor: 'pointer', color: 'var(--text-muted)', fontSize: 11 }}>
                Show error details
              </summary>
              <pre style={{ fontSize: 10, textAlign: 'left', color: 'var(--text-muted)', overflow: 'auto' }}>{componentStack}</pre>
            </details>
          )}
          <button
            onClick={this.reset}
            style={{
              padding: '8px 16px', borderRadius: 8, border: '1px solid var(--border)',
              background: 'transparent', color: 'var(--cx-primary)', cursor: 'pointer', fontWeight: 600,
            }}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}

export default function ErrorBoundary({ children, fallback }) {
  return <ErrorBoundaryImpl fallback={fallback}>{children}</ErrorBoundaryImpl>;
}
