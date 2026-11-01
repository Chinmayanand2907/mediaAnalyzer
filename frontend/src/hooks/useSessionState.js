/**
 * useSessionState — drop-in replacement for useState that persists its value
 * in sessionStorage.
 *
 * Behaviour:
 *  • Same tab, page reload  → value is restored from sessionStorage (survives).
 *  • New tab / new window   → sessionStorage is isolated per tab, starts empty (fresh).
 *  • Tab closed & reopened  → sessionStorage is cleared by the browser (fresh).
 *
 * Usage:
 *   const [selectedChannel, setSelectedChannel] = useSessionState('yt:selectedChannel', null);
 *
 * The key should be globally unique across the app. Use a short namespaced string
 * like 'yt:selectedChannel', 'rd:selectedSub', 'cx:activeVideo', etc.
 */

import { useState, useEffect, useRef } from 'react';

export function useSessionState(storageKey, defaultValue) {
  const [value, setValue] = useState(() => {
    try {
      const raw = sessionStorage.getItem(storageKey);
      if (raw === null) return defaultValue;
      return JSON.parse(raw);
    } catch {
      return defaultValue;
    }
  });

  // Skip the initial write so we don't overwrite a just-restored value
  const isFirstRender = useRef(true);

  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    try {
      if (value === null || value === undefined || value === '') {
        sessionStorage.removeItem(storageKey);
      } else {
        sessionStorage.setItem(storageKey, JSON.stringify(value));
      }
    } catch { /* quota exceeded — silently ignore */ }
  }, [storageKey, value]);

  return [value, setValue];
}

