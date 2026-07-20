/**
 * useAnalytics — generic data-fetching hook.
 *
 * Usage:
 *   const { data, loading, error, refetch } = useAnalytics(
 *     (signal) => fetchYoutubeChannels(signal),
 *     []
 *   );
 *
 * - Cancels in-flight requests via AbortController when deps change or component unmounts.
 * - Exposes a `refetch` callback for manual refresh (e.g. after triggering an ingest).
 * - `enabled` flag lets callers gate the fetch on a condition (e.g. requires a channel ID).
 */

import { useState, useEffect, useCallback, useRef } from 'react';

export function useAnalytics(fetchFn, deps = [], { enabled = true, initialData = null } = {}) {
  const [data, setData]       = useState(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);
  const fetchFnRef            = useRef(fetchFn);

  // Keep the ref fresh without triggering re-runs
  useEffect(() => { fetchFnRef.current = fetchFn; });

  const run = useCallback((signal) => {
    if (!enabled) return;
    setLoading(true);
    setError(null);
    fetchFnRef.current(signal)
      .then((result) => { setData(result); setLoading(false); })
      .catch((err) => {
        if (err.name === 'CanceledError' || err.name === 'AbortError') return; // stale request — ignore
        setError(err.message ?? 'Something went wrong');
        setLoading(false);
      });
  }, [enabled, ...deps]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const controller = new AbortController();
    run(controller.signal);
    return () => controller.abort();
  }, [run]);

  const refetch = useCallback(() => {
    const controller = new AbortController();
    run(controller.signal);
  }, [run]);

  return { data, loading, error, refetch };
}
