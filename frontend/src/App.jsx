import Dashboard from './pages/Dashboard';
import LandingPage from './pages/LandingPage';
import { useEffect, useState } from 'react';

function App() {
  const [path, setPath] = useState(() => window.location.pathname);

  useEffect(() => {
    const handlePopState = () => setPath(window.location.pathname);
    window.addEventListener('popstate', handlePopState);
    return () => window.removeEventListener('popstate', handlePopState);
  }, []);

  if (path === '/dashboard') return <Dashboard />;
  return <LandingPage />;
}

export default App;
