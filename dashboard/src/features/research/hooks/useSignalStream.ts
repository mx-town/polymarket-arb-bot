/**
 * Hook for signal stream
 * Maintains list of recent signals with WebSocket subscription for new signals
 */

import { useEffect, useState, useRef, useCallback } from 'react';
import type { Signal } from '../types/research.types';
import { fetchSignals, ResearchWebSocket } from '../api/research-client';

export interface UseSignalStreamOptions {
  /** Maximum number of signals to keep in memory (default: 100) */
  maxSignals?: number;
  /** Whether to fetch initial signals on mount (default: true) */
  fetchInitial?: boolean;
  /** Number of initial signals to fetch (default: 50) */
  initialLimit?: number;
}

export interface UseSignalStreamReturn {
  /** List of recent signals (newest first) */
  signals: Signal[];
  /** The most recent signal */
  latestSignal: Signal | null;
  /** Clear all signals from the list */
  clearSignals: () => void;
  /** Whether WebSocket is connected */
  isConnected: boolean;
  /** Whether initial data is loading */
  isLoading: boolean;
  /** Error message if any */
  error: string | null;
}

export function useSignalStream(
  options: UseSignalStreamOptions = {}
): UseSignalStreamReturn {
  const {
    maxSignals = 100,
    fetchInitial = true,
    initialLimit = 50,
  } = options;

  const [signals, setSignals] = useState<Signal[]>([]);
  const [isConnected, setIsConnected] = useState(false);
  const [isLoading, setIsLoading] = useState(fetchInitial);
  const [error, setError] = useState<string | null>(null);

  const wsRef = useRef<ResearchWebSocket | null>(null);

  const clearSignals = useCallback(() => {
    setSignals([]);
  }, []);

  // Fetch initial signals on mount (separate from WebSocket setup)
  useEffect(() => {
    if (!fetchInitial) return;

    let cancelled = false;

    fetchSignals(initialLimit)
      .then((initialSignals) => {
        if (!cancelled) {
          setSignals(initialSignals);
          setError(null);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : 'Failed to fetch signals');
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false);
        }
      });

    return () => {
      cancelled = true;
    };
  }, [fetchInitial, initialLimit]);

  // Set up WebSocket for live signal updates (separate effect)
  useEffect(() => {

    const ws = new ResearchWebSocket({
      onOpen: () => {
        setIsConnected(true);
        setError(null);
      },
      onClose: () => {
        setIsConnected(false);
      },
      onError: (err) => {
        setError(err.message);
      },
      onSignal: (signal) => {
        setSignals((prev) => [signal, ...prev].slice(0, maxSignals));
      },
    });

    ws.connect();
    wsRef.current = ws;

    return () => {
      ws.disconnect();
    };
  }, [maxSignals]);

  const latestSignal = signals.length > 0 ? signals[0] : null;

  return {
    signals,
    latestSignal,
    clearSignals,
    isConnected,
    isLoading,
    error,
  };
}
