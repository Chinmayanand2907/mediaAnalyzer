/**
 * useAnalytics — generic data-fetching hook with in-memory caching and stale-while-revalidate.
 *
 * Features:
 * - Global in-memory cache: metrics, charts, and tables display instantly on tab switches.
 * - Stale-while-revalidate: renders cached data immediately, revalidates in the background.
 * - Cancels in-flight requests via AbortController when deps change or component unmounts.
 * - Exposes `refetch({ force: true })` for manual refresh (e.g. after triggering ingest).
 * - Stable deps comparison prevents redundant renders.
 * - Session-scoped persistence: cache is written to sessionStorage so data survives a page
 *   refresh within the same browser tab, but a brand-new tab always starts completely fresh.
 */

import { useState, useEffect, useCallback, useRef } from 'react';

const SESSION_CACHE_KEY = 'engageiq:analytics_cache';
const DEFAULT_TTL_MS = 10 * 60 * 1000; // 10 minutes cache TTL

/**
 * Global In-Memory Analytics Cache.
 * Key: string -> Value: { data: any, timestamp: number }
 *
 * Rehydrated from sessionStorage on module load so that a page refresh within
 * the same tab restores previously fetched data instantly.  A new tab (fresh
 * sessionStorage) always begins with an empty cache, satisfying the
 * "start fresh on new tab" requirement.
 */
export const analyticsMemoryCache = (() => {
  const map = new Map();
  try {
    const stored = sessionStorage.getItem(SESSION_CACHE_KEY);
    if (stored) {
      const parsed = JSON.parse(stored);
      for (const [k, v] of Object.entries(parsed)) {
        map.set(k, v);
      }
    }
  } catch { /* sessionStorage unavailable or corrupt — start fresh */ }
  return map;
})();

/** Persist the current in-memory cache snapshot to sessionStorage. */
function persistCacheToSession() {
  try {
    const obj = {};
    for (const [k, v] of analyticsMemoryCache.entries()) {
      obj[k] = v;
    }
    sessionStorage.setItem(SESSION_CACHE_KEY, JSON.stringify(obj));
  } catch { /* quota exceeded or unavailable — silently skip */ }
}

/**
 * Generate a deterministic cache key based on function identifier & serialized deps.
 * Pass an explicit `customKey` whenever the fetcher is an inline closure —
 * anonymous closures have empty .name and minified source collides.
 */
function createCacheKey(fetchFn, deps, customKey) {
  if (customKey) return `custom:${customKey}`;
  const fnId = fetchFn?.name || 'fn';
  const fnSrc = (fetchFn?.toString?.() || '').slice(0, 500).replace(/\s+/g, ' ');
  const depsKey = JSON.stringify(deps || []);
  return `${fnId}::${fnSrc}::${depsKey}`;
}

/**
 * Clears all or matching entries in the analytics memory cache and
 * synchronises the removal to sessionStorage.
 */
export function clearAnalyticsCache(pattern) {
  if (!pattern) {
    analyticsMemoryCache.clear();
  } else {
    for (const key of analyticsMemoryCache.keys()) {
      if (key.includes(pattern)) {
        analyticsMemoryCache.delete(key);
      }
    }
  }
  persistCacheToSession();
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

  // Reset stale data/error when disabled (e.g. filter cleared) so old
  // channel/video metrics are not shown as current.
  const wasEnabledRef = useRef(enabled);
  useEffect(() => {
    if (wasEnabledRef.current && !enabled) {
      setData(initialData);
      setError(null);
      setLoading(false);
    }
    wasEnabledRef.current = enabled;
  }, [enabled, initialData]);

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
          persistCacheToSession();
        }
        setData(result);
        setLoading(false);
      })
      .catch((err) => {
        if (err?.name === 'CanceledError' || err?.name === 'AbortError' || err?.code === 'ERR_CANCELED') return;
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

