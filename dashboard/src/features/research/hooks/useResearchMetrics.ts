/**
 * Main hook for all research data
 * Fetches all research metrics on mount and sets up WebSocket for real-time updates
 */

import { useEffect, useState, useRef, useCallback } from 'react';
import type {
  ProbabilitySurface,
  Signal,
  TradingOpportunity,
  LagStats,
  ObservationStatus,
} from '../types/research.types';
import { fetchResearchMetrics, ResearchWebSocket } from '../api/research-client';

export interface UseResearchMetricsReturn {
  /** Probability surface data */
  surface: ProbabilitySurface | null;
  /** Recent signals */
  signals: Signal[];
  /** Current trading opportunities */
  opportunities: TradingOpportunity[];
  /** Lag statistics */
  lagStats: LagStats | null;
  /** Current observation status */
  observationStatus: ObservationStatus | null;
  /** Whether initial data is loading */
  isLoading: boolean;
  /** Error message if any */
  error: string | null;
  /** Whether WebSocket is connected */
  isConnected: boolean;
  /** Manually refresh all data */
  refresh: () => Promise<void>;
  /** Clear all signals */
  clearSignals: () => void;
}

export function useResearchMetrics(): UseResearchMetricsReturn {
  const [surface, setSurface] = useState<ProbabilitySurface | null>(null);
  const [signals, setSignals] = useState<Signal[]>([]);
  const [opportunities, setOpportunities] = useState<TradingOpportunity[]>([]);
  const [lagStats, setLagStats] = useState<LagStats | null>(null);
  const [observationStatus, setObservationStatus] = useState<ObservationStatus | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);

  const wsRef = useRef<ResearchWebSocket | null>(null);

  const refresh = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const metrics = await fetchResearchMetrics();
      setSurface(metrics.surface);
      setSignals(metrics.signals);
      setOpportunities(metrics.opportunities);
      setLagStats(metrics.lag_stats);
      setObservationStatus(metrics.observation_status);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch research metrics');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    // Initial fetch
    refresh();

    // Set up WebSocket for live updates
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
        setSignals((prev) => [signal, ...prev].slice(0, 100)); // Keep last 100 signals
      },
      onOpportunity: (opportunity) => {
        setOpportunities((prev) => {
          // Update or add opportunity based on direction
          const existing = prev.findIndex((o) => o.direction === opportunity.direction);
          if (existing >= 0) {
            const updated = [...prev];
            updated[existing] = opportunity;
            return updated;
          }
          return [...prev, opportunity];
        });
      },
      onSurfaceUpdate: (newSurface) => {
        setSurface(newSurface);
      },
      onObservationStatus: (status) => {
        setObservationStatus(status);
      },
    });

    ws.connect();
    wsRef.current = ws;

    return () => {
      ws.disconnect();
    };
  }, [refresh]);

  const clearSignals = useCallback(() => {
    setSignals([]);
  }, []);

  return {
    surface,
    signals,
    opportunities,
    lagStats,
    observationStatus,
    isLoading,
    error,
    isConnected,
    refresh,
    clearSignals,
  };
}
