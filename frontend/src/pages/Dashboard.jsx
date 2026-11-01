import { useState, useCallback } from 'react';
import Navbar from '../components/layout/Navbar';
import YoutubeView from '../views/YoutubeView';
import RedditView from '../views/RedditView';
import CrossPlatformView from '../views/CrossPlatformView';
import ChatBotPanel from '../components/ChatBotPanel';
import { useSessionState } from '../hooks/useSessionState';
import ErrorBoundary from '../components/ErrorBoundary';

const VALID_PLATFORMS = ['youtube', 'reddit', 'cross-platform'];

export default function Dashboard() {
  // Persist the active platform tab across reloads (sessionStorage, so fresh on new tab)
  const [rawPlatform, setPlatform] = useSessionState('dashboard:platform', 'youtube');
  // Guard against a stale/corrupted sessionStorage value hiding every view.
  const platform = VALID_PLATFORMS.includes(rawPlatform) ? rawPlatform : 'youtube';
  const [activeItems, setActiveItems] = useState({ youtube: null, reddit: null, 'cross-platform': null });

  const activeItem = activeItems[platform] || null;

  // Stable callbacks that bail out if the value hasn't changed to prevent infinite re-render loops
  const handleYoutubeActiveChange = useCallback((item) => {
    setActiveItems((prev) => (prev.youtube === item ? prev : { ...prev, youtube: item }));
  }, []);

  const handleRedditActiveChange = useCallback((item) => {
    setActiveItems((prev) => (prev.reddit === item ? prev : { ...prev, reddit: item }));
  }, []);

  const handleCrossPlatformActiveChange = useCallback((item) => {
    setActiveItems((prev) => (prev['cross-platform'] === item ? prev : { ...prev, 'cross-platform': item }));
  }, []);

  const handlePlatformChange = (p) => {
    setPlatform(p);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      {/* ── Global Top Navigation ── */}
      <Navbar platform={platform} onPlatformChange={handlePlatformChange} />

      {/* ── Main Content Area ── */}
      <main style={{ flex: 1, padding: '32px 24px', maxWidth: 1280, margin: '0 auto', width: '100%' }}>
        {/*
          All three views stay mounted in the DOM and are toggled via display:block/none.
          This ensures that switching between dashboards retains all analyzed data,
          active inputs, pagination, and scroll positions without reloading.
          Each view is wrapped in an ErrorBoundary to prevent any crash from blanking the page.
        */}
        <div style={{ display: platform === 'youtube' ? 'block' : 'none' }}>
          <ErrorBoundary>
            <YoutubeView onActiveChange={handleYoutubeActiveChange} />
          </ErrorBoundary>
        </div>
        <div style={{ display: platform === 'reddit' ? 'block' : 'none' }}>
          <ErrorBoundary>
            <RedditView onActiveChange={handleRedditActiveChange} />
          </ErrorBoundary>
        </div>
        <div style={{ display: platform === 'cross-platform' ? 'block' : 'none' }}>
          <ErrorBoundary>
            <CrossPlatformView onActiveChange={handleCrossPlatformActiveChange} />
          </ErrorBoundary>
        </div>
      </main>

      {/* ── Footer ── */}
      <footer style={{ 
        borderTop: '1px solid var(--border)', 
        padding: '24px', 
        textAlign: 'center',
        color: 'var(--text-muted)',
        fontSize: 12,
        background: 'var(--bg-surface)'
      }}>
        EngageIQ Analytics Dashboard &copy; {new Date().getFullYear()}
      </footer>

      {/* ── Floating AI Chatbot Panel ── */}
      <ChatBotPanel platform={platform} activeItem={activeItem} />
    </div>
  );
}
