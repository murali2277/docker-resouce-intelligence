import { useState, useEffect, useCallback, useRef } from 'react';

interface UsePollingOptions {
  intervalMs?: number;
  enabled?: boolean;
}

interface UsePollingResult<T> {
  data: T | null;
  loading: boolean;
  error: string | null;
  lastUpdated: Date | null;
  refetch: () => Promise<void>;
}

export function usePolling<T>(
  url: string,
  options: UsePollingOptions = {}
): UsePollingResult<T> {
  const { intervalMs = 5000, enabled = true } = options;
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState<boolean>(true);
  const [error, setError] = useState<string | null>(null);
  const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

  // Keep ref to avoid stale closures in interval
  const isFirstFetch = useRef<boolean>(true);

  const fetchData = useCallback(async () => {
    if (isFirstFetch.current) {
      setLoading(true);
    }

    try {
      const response = await fetch(url, {
        headers: {
          'Accept': 'application/json',
        },
      });

      if (!response.ok) {
        throw new Error(`HTTP error ${response.status}: ${response.statusText}`);
      }

      const result: T = await response.json();
      setData(result);
      setError(null);
      setLastUpdated(new Date());
    } catch (err) {
      const message = err instanceof Error ? err.message : 'An unknown error occurred';
      setError(message);
    } finally {
      if (isFirstFetch.current) {
        setLoading(false);
        isFirstFetch.current = false;
      }
    }
  }, [url]);

  useEffect(() => {
    if (!enabled) return;

    // Reset initial loading state when URL changes
    isFirstFetch.current = true;

    // Initial fetch
    fetchData();

    // Setup polling timer
    const intervalId = setInterval(() => {
      fetchData();
    }, intervalMs);

    return () => {
      clearInterval(intervalId);
    };
  }, [url, intervalMs, enabled, fetchData]);

  return {
    data,
    loading,
    error,
    lastUpdated,
    refetch: fetchData,
  };
}
