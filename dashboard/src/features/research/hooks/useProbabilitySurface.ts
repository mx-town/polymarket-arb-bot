/**
 * Hook specifically for probability surface data
 * Supports filtering by volatility regime and trading session
 */

import { useEffect, useState, useCallback, useMemo } from 'react';
import type {
  ProbabilitySurface,
  ProbabilityBucket,
  VolatilityRegime,
  TradingSession,
} from '../types/research.types';
import { fetchProbabilitySurface } from '../api/research-client';

export interface SurfaceFilters {
  /** Filter by volatility regime */
  volRegime?: VolatilityRegime | null;
  /** Filter by trading session */
  session?: TradingSession | null;
}

export interface UseProbabilitySurfaceReturn {
  /** Full probability surface data */
  surface: ProbabilitySurface | null;
  /** Filtered buckets based on current filters */
  filteredBuckets: ProbabilityBucket[];
  /** Whether data is loading */
  isLoading: boolean;
  /** Error message if any */
  error: string | null;
  /** Refetch surface data */
  refetch: () => Promise<void>;
  /** Current filters */
  filters: SurfaceFilters;
  /** Update filters */
  setFilters: (filters: SurfaceFilters) => void;
}

export function useProbabilitySurface(
  initialFilters: SurfaceFilters = {}
): UseProbabilitySurfaceReturn {
  const [surface, setSurface] = useState<ProbabilitySurface | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<SurfaceFilters>(initialFilters);

  const refetch = useCallback(async () => {
    try {
      setIsLoading(true);
      setError(null);
      const data = await fetchProbabilitySurface();
      setSurface(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch probability surface');
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    refetch();
  }, [refetch]);

  const filteredBuckets = useMemo(() => {
    if (!surface?.buckets) {
      return [];
    }

    return surface.buckets.filter((bucket) => {
      // Filter by volatility regime if specified
      if (filters.volRegime && bucket.vol_regime !== filters.volRegime) {
        return false;
      }
      // Filter by trading session if specified
      if (filters.session && bucket.session !== filters.session) {
        return false;
      }
      return true;
    });
  }, [surface, filters]);

  return {
    surface,
    filteredBuckets,
    isLoading,
    error,
    refetch,
    filters,
    setFilters,
  };
}
