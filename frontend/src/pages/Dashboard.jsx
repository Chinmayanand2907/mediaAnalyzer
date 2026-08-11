import { useState } from 'react';
import Navbar from '../components/layout/Navbar';
import YoutubeView from '../views/YoutubeView';
import RedditView from '../views/RedditView';
import CrossPlatformView from '../views/CrossPlatformView';
import ChatBotPanel from '../components/ChatBotPanel';

export default function Dashboard() {
  // Global platform state: 'youtube' | 'reddit' | 'cross-platform'
  const [platform, setPlatform] = useState('youtube');

  return (
    <div style={{ display: 'flex', flexDirection: 'column', minHeight: '100vh' }}>
      {/* ── Global Top Navigation ── */}
      <Navbar platform={platform} onPlatformChange={setPlatform} />

      {/* ── Main Content Area ── */}
      <main style={{ flex: 1, padding: '32px 24px', maxWidth: 1280, margin: '0 auto', width: '100%' }}>
        <div style={{ display: platform === 'youtube' ? 'block' : 'none' }}>
          <YoutubeView />
        </div>
        <div style={{ display: platform === 'reddit' ? 'block' : 'none' }}>
          <RedditView />
        </div>
        <div style={{ display: platform === 'cross-platform' ? 'block' : 'none' }}>
          <CrossPlatformView />
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
      <ChatBotPanel platform={platform} />
    </div>
  );
}
