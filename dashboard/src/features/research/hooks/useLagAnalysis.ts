/**
 * Hook for lag statistics between Binance and Polymarket
 */

import { useEffect, useState, useCallback } from 'react';
import type { LagStats } from '../types/research.types';
import { fetchLagStats } from '../api/research-client';

export interface UseLagAnalysisReturn {
  /** Lag statistics data */
  lagStats: LagStats | null;
  /** Whether data is loading */
  isLoading: boolean;
  /** Error message if any */
  error: string | null;
  /** Refetch lag statistics */
  refetch: () => Promise<void>;
}

export function useLagAnalysis(): UseLagAnalysisReturn {
  const [lagStats, setLagStats] = useState<LagStats | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refetch = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await fetchLagStats();
      setLagStats(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch lag statistics');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  return {
    lagStats,
    isLoading,
    error,
    refetch,
  };
}
