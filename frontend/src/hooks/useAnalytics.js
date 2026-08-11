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
 *
 * Stability note
 * --------------
 * Callers often pass inline array literals as deps (e.g. [selectedSub]).  Spreading
 * those directly into useCallback's dependency array would cause a new array reference
 * on every render, regenerating the callback and triggering a redundant network request
 * each time.  Instead we compare the dep values by value via a ref and only increment a
 * stable integer counter when something actually changes.  useCallback depends on that
 * counter, so it stays stable across renders where the dep values are the same.
 */

import { useState, useEffect, useCallback, useRef } from 'react';

export function useAnalytics(fetchFn, deps = [], { enabled = true, initialData = null } = {}) {
  const [data, setData]       = useState(initialData);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState(null);
  const fetchFnRef            = useRef(fetchFn);

  // Keep the ref fresh without triggering re-runs.
  useEffect(() => { fetchFnRef.current = fetchFn; });

  // ── Stable deps counter ─────────────────────────────────────────────────
  // Compare the deps array element-by-element on every render.  Only when a
  // value actually changes do we bump the counter, which is the sole primitive
  // that useCallback depends on (together with `enabled`).  This means callers
  // can safely pass inline array literals without causing extra fetches.
  const prevDepsRef    = useRef(deps);
  const depsCounterRef = useRef(0);

  const prevDeps = prevDepsRef.current;
  if (
    prevDeps.length !== deps.length ||
    deps.some((dep, i) => !Object.is(dep, prevDeps[i]))
  ) {
    prevDepsRef.current = deps;
    depsCounterRef.current += 1;
  }
  const depsCounter = depsCounterRef.current;
  // ───────────────────────────────────────────────────────────────────────

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
  }, [enabled, depsCounter]); // eslint-disable-line react-hooks/exhaustive-deps

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
