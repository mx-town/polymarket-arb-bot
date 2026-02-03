import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import type { LagStats } from '../../types/research.types';
import { LatencyHistogram } from './LatencyHistogram';
import { LagTimeSeries } from './LagTimeSeries';

interface LagAnalysisProps {
  /** Lag statistics from the research API */
  lagStats: LagStats | null;
  /** Raw lag measurements for histogram (optional, derived from snapshots) */
  lagMeasurements?: number[];
  /** Time series data for lag over time (optional) */
  lagTimeSeries?: Array<{ timestamp: number; lag_ms: number }>;
  /** Whether data is currently loading */
  isLoading?: boolean;
}

/**
 * Stat box component for displaying a single metric
 */
function StatBox({
  label,
  value,
  unit,
  color,
}: {
  label: string;
  value: string | number;
  unit: string;
  color?: string;
}) {
  return (
    <div className="flex flex-col items-center justify-center p-4 rounded-lg border bg-card">
      <span className="text-[10px] uppercase tracking-wider text-muted-foreground font-medium mb-1">
        {label}
      </span>
      <span
        className="text-2xl font-bold font-mono"
        style={{ color: color || 'hsl(var(--foreground))' }}
      >
        {value}
      </span>
      <span className="text-xs text-muted-foreground">{unit}</span>
    </div>
  );
}

/**
 * Loading skeleton for the stats row
 */
function StatsLoading() {
  return (
    <div className="grid grid-cols-4 gap-4 mb-6">
      {[...Array(4)].map((_, i) => (
        <div
          key={i}
          className="flex flex-col items-center justify-center p-4 rounded-lg border bg-card animate-pulse"
        >
          <div className="h-3 w-12 bg-muted rounded mb-2" />
          <div className="h-8 w-20 bg-muted rounded mb-1" />
          <div className="h-3 w-8 bg-muted rounded" />
        </div>
      ))}
    </div>
  );
}

/**
 * Loading skeleton for charts
 */
function ChartLoading() {
  return (
    <div className="rounded-lg border bg-card">
      <div className="flex items-center gap-2 border-b px-4 py-3 bg-muted/30">
        <div className="h-3 w-32 bg-muted rounded animate-pulse" />
      </div>
      <div className="p-4 h-[280px] flex items-center justify-center">
        <div className="text-muted-foreground text-sm">Loading chart data...</div>
      </div>
    </div>
  );
}

/**
 * LagAnalysis component - Tab content for analyzing Binance vs Polymarket lag
 *
 * Displays:
 * - Stats row with P50, P95, P99, and sample count
 * - Latency histogram showing distribution
 * - Time series chart showing lag over time
 * - Methodology explanation
 */
export function LagAnalysis({
  lagStats,
  lagMeasurements = [],
  lagTimeSeries = [],
  isLoading = false,
}: LagAnalysisProps) {
  // Extract stats or use defaults
  const p50 = lagStats?.median_lag_ms ?? 0;
  const p95 = lagStats?.p95_lag_ms ?? 0;
  const p99 = lagStats?.p99_lag_ms ?? 0;
  const sampleCount = lagStats?.sample_size ?? 0;

  // Generate mock measurements from stats if not provided
  // In production, these would come from actual collected data
  const measurements =
    lagMeasurements.length > 0
      ? lagMeasurements
      : lagStats
        ? generateMockMeasurements(lagStats)
        : [];

  const timeSeries =
    lagTimeSeries.length > 0
      ? lagTimeSeries
      : lagStats
        ? generateMockTimeSeries(lagStats)
        : [];

  if (isLoading) {
    return (
      <div className="space-y-6">
        <StatsLoading />
        <div className="grid grid-cols-2 gap-6">
          <ChartLoading />
          <ChartLoading />
        </div>
      </div>
    );
  }

  if (!lagStats) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Lag Analysis</CardTitle>
          <CardDescription>No lag data available yet</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="py-12 text-center text-muted-foreground">
            <p className="mb-2">Start data collection to analyze lag between Binance and Polymarket.</p>
            <p className="text-sm">
              Lag measurements help calibrate the trading strategy timing parameters.
            </p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-6">
      {/* Stats Row */}
      <div className="grid grid-cols-4 gap-4">
        <StatBox label="Median (P50)" value={p50.toFixed(0)} unit="ms" color="#22c55e" />
        <StatBox label="P95" value={p95.toFixed(0)} unit="ms" color="#f59e0b" />
        <StatBox label="P99" value={p99.toFixed(0)} unit="ms" color="#ef4444" />
        <StatBox
          label="Sample Count"
          value={sampleCount.toLocaleString()}
          unit="measurements"
          color="hsl(217.2 91.2% 59.8%)"
        />
      </div>

      {/* Charts Row */}
      <div className="grid grid-cols-2 gap-6">
        <LatencyHistogram lagMeasurements={measurements} p50={p50} p95={p95} p99={p99} />
        <LagTimeSeries measurements={timeSeries} p50={p50} p95={p95} />
      </div>

      {/* Methodology Explanation */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-sm">Lag Measurement Methodology</CardTitle>
        </CardHeader>
        <CardContent className="text-sm text-muted-foreground space-y-2">
          <p>
            <strong>Definition:</strong> Lag is measured as the time difference between when a price
            movement is detected on Binance and when the corresponding Polymarket order book reflects
            that movement.
          </p>
          <p>
            <strong>Measurement Process:</strong> When Binance BTC price moves significantly (crossing
            momentum thresholds), we record the timestamp. We then monitor Polymarket order books for
            price adjustments, recording when the combined ask price changes by more than 0.5%.
          </p>
          <p>
            <strong>Trading Implications:</strong> The P50 lag informs the expected window for capturing
            arbitrage opportunities. P95/P99 values help set conservative timeout parameters to avoid
            holding stale positions.
          </p>
          <p>
            <strong>Configuration:</strong> Use these statistics to calibrate{' '}
            <code className="px-1 py-0.5 bg-muted rounded text-xs font-mono">expected_lag_ms</code> and{' '}
            <code className="px-1 py-0.5 bg-muted rounded text-xs font-mono">max_lag_window_ms</code> in
            the lag arbitrage strategy settings.
          </p>
        </CardContent>
      </Card>
    </div>
  );
}

/**
 * Generate mock measurements from stats for visualization
 * This simulates a distribution matching the provided percentiles
 */
function generateMockMeasurements(stats: LagStats): number[] {
  const { sample_size, median_lag_ms, p95_lag_ms, p99_lag_ms, std_lag_ms } = stats;
  const count = Math.min(sample_size, 500); // Cap at 500 for performance
  const measurements: number[] = [];

  for (let i = 0; i < count; i++) {
    // Generate values following approximate distribution
    const rand = Math.random();
    let value: number;

    if (rand < 0.5) {
      // Below median - use normal distribution centered at median/2
      value = median_lag_ms * 0.5 + Math.random() * median_lag_ms * 0.5;
    } else if (rand < 0.95) {
      // Between P50 and P95
      value = median_lag_ms + Math.random() * (p95_lag_ms - median_lag_ms);
    } else if (rand < 0.99) {
      // Between P95 and P99
      value = p95_lag_ms + Math.random() * (p99_lag_ms - p95_lag_ms);
    } else {
      // Above P99 - tail
      value = p99_lag_ms + Math.random() * std_lag_ms;
    }

    measurements.push(Math.max(0, value));
  }

  return measurements;
}

/**
 * Generate mock time series from stats for visualization
 */
function generateMockTimeSeries(
  stats: LagStats
): Array<{ timestamp: number; lag_ms: number }> {
  const { sample_size, median_lag_ms, p95_lag_ms, std_lag_ms } = stats;
  const count = Math.min(sample_size, 100); // Cap at 100 points
  const now = Date.now();
  const intervalMs = 60000; // 1 minute intervals

  const timeSeries: Array<{ timestamp: number; lag_ms: number }> = [];

  for (let i = 0; i < count; i++) {
    const timestamp = now - (count - i) * intervalMs;

    // Generate lag with some random variation around median
    const variation = (Math.random() - 0.5) * std_lag_ms * 2;
    let lag = median_lag_ms + variation;

    // Occasionally spike to P95 range
    if (Math.random() > 0.9) {
      lag = p95_lag_ms + Math.random() * (p95_lag_ms - median_lag_ms) * 0.5;
    }

    timeSeries.push({
      timestamp,
      lag_ms: Math.max(50, lag), // Minimum 50ms
    });
  }

  return timeSeries;
}
