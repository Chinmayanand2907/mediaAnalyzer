/**
 * useAnalytics — generic data-fetching hook with in-memory caching and stale-while-revalidate.
 *
 * Features:
 * - Global in-memory cache: metrics, charts, and tables display instantly on tab switches.
 * - Stale-while-revalidate: renders cached data immediately, revalidates in the background.
 * - Cancels in-flight requests via AbortController when deps change or component unmounts.
 * - Exposes `refetch({ force: true })` for manual refresh (e.g. after triggering ingest).
 * - Stable deps comparison prevents redundant renders.
 */

import { useState, useEffect, useCallback, useRef } from 'react';

/**
 * Global In-Memory Analytics Cache.
 * Key: string -> Value: { data: any, timestamp: number }
 */
export const analyticsMemoryCache = new Map();
const DEFAULT_TTL_MS = 10 * 60 * 1000; // 10 minutes cache TTL

/**
 * Generate a deterministic cache key based on function identifier & serialized deps.
 */
function createCacheKey(fetchFn, deps, customKey) {
  if (customKey) return `custom:${customKey}`;
  const fnId = fetchFn?.name || fetchFn?.toString()?.slice(0, 80)?.replace(/\s+/g, ' ') || 'fn';
  const depsKey = JSON.stringify(deps || []);
  return `${fnId}::${depsKey}`;
}

/**
 * Clears all or matching entries in the analytics memory cache.
 */
export function clearAnalyticsCache(pattern) {
  if (!pattern) {
    analyticsMemoryCache.clear();
    return;
  }
  for (const key of analyticsMemoryCache.keys()) {
    if (key.includes(pattern)) {
      analyticsMemoryCache.delete(key);
    }
  }
}

export function useAnalytics(
  fetchFn,
  deps = [],
  {
    enabled = true,
    initialData = null,
    cacheKey = null,
    ttl = DEFAULT_TTL_MS,
    useCache = true,
    staleWhileRevalidate = true,
  } = {}
) {
  const key = useCache && enabled ? createCacheKey(fetchFn, deps, cacheKey) : null;
  const cached = key ? analyticsMemoryCache.get(key) : null;
  const isFresh = cached != null && (Date.now() - cached.timestamp < ttl);

  const [data, setData] = useState(() => (cached != null ? cached.data : initialData));
  const [loading, setLoading] = useState(() => (cached == null && enabled));
  const [error, setError] = useState(null);
  const fetchFnRef = useRef(fetchFn);

  // Keep the ref fresh without triggering re-runs.
  useEffect(() => {
    fetchFnRef.current = fetchFn;
  });

  // ── Stable deps counter ─────────────────────────────────────────────────
  const prevDepsRef = useRef(deps);
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

  const run = useCallback((signal, { force = false } = {}) => {
    if (!enabled) return;

    const currentKey = useCache ? createCacheKey(fetchFnRef.current, deps, cacheKey) : null;
    const currentCached = currentKey ? analyticsMemoryCache.get(currentKey) : null;
    const hasCachedData = currentCached != null;
    const isCacheValid = !force && hasCachedData && (Date.now() - currentCached.timestamp < ttl);

    if (hasCachedData && !force) {
      setData(currentCached.data);
      setLoading(false);
      if (isCacheValid && !staleWhileRevalidate) {
        return;
      }
    } else {
      setLoading(true);
    }

    setError(null);
    fetchFnRef.current(signal)
      .then((result) => {
        if (currentKey && useCache && result !== undefined) {
          analyticsMemoryCache.set(currentKey, { data: result, timestamp: Date.now() });
        }
        setData(result);
        setLoading(false);
      })
      .catch((err) => {
        if (err.name === 'CanceledError' || err.name === 'AbortError') return;
        setError(err.message ?? 'Something went wrong');
        setLoading(false);
      });
  }, [enabled, depsCounter, ttl, useCache, staleWhileRevalidate, cacheKey]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const controller = new AbortController();
    run(controller.signal);
    return () => controller.abort();
  }, [run]);

  const refetch = useCallback((options = { force: true }) => {
    const controller = new AbortController();
    run(controller.signal, options);
  }, [run]);

  return { data, loading, error, refetch };
}

