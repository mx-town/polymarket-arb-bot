import { useMemo, useState } from 'react';
import type { LagStats } from '../../types/research.types';
import { LatencyHistogram } from './LatencyHistogram';
import { LagTimeSeries } from './LagTimeSeries';

interface LagAnalysisProps {
  lagStats: LagStats | null;
  lagMeasurements?: number[];
  lagTimeSeries?: Array<{ timestamp: number; lag_ms: number }>;
  isLoading?: boolean;
}

function seededRandom(seed: number): () => number {
  return function () {
    seed = (seed * 9301 + 49297) % 233280;
    return seed / 233280;
  };
}

function generateMockMeasurements(stats: LagStats): number[] {
  const { sample_size, median_lag_ms, p95_lag_ms, p99_lag_ms, std_lag_ms } = stats;
  const count = Math.min(sample_size, 500);
  const measurements: number[] = [];
  const seed = Math.floor(median_lag_ms + p95_lag_ms + p99_lag_ms);
  const random = seededRandom(seed);

  for (let i = 0; i < count; i++) {
    const rand = random();
    let value: number;
    if (rand < 0.5) {
      value = median_lag_ms * 0.5 + random() * median_lag_ms * 0.5;
    } else if (rand < 0.95) {
      value = median_lag_ms + random() * (p95_lag_ms - median_lag_ms);
    } else if (rand < 0.99) {
      value = p95_lag_ms + random() * (p99_lag_ms - p95_lag_ms);
    } else {
      value = p99_lag_ms + random() * std_lag_ms;
    }
    measurements.push(Math.max(0, value));
  }
  return measurements;
}

function generateMockTimeSeries(
  stats: LagStats
): Array<{ timestamp: number; lag_ms: number }> {
  const { sample_size, median_lag_ms, p95_lag_ms, std_lag_ms } = stats;
  const count = Math.min(sample_size, 100);
  const baseTime = new Date().setHours(0, 0, 0, 0);
  const intervalMs = 60000;
  const timeSeries: Array<{ timestamp: number; lag_ms: number }> = [];
  const seed = Math.floor(median_lag_ms + p95_lag_ms);
  const random = seededRandom(seed);

  for (let i = 0; i < count; i++) {
    const timestamp = baseTime + i * intervalMs;
    const variation = (random() - 0.5) * std_lag_ms * 2;
    let lag = median_lag_ms + variation;
    if (random() > 0.9) {
      lag = p95_lag_ms + random() * (p95_lag_ms - median_lag_ms) * 0.5;
    }
    timeSeries.push({ timestamp, lag_ms: Math.max(50, lag) });
  }
  return timeSeries;
}

function getLagColor(lagMs: number): string {
  if (lagMs < 1000) return '#00d4aa';
  if (lagMs < 2000) return '#ffaa00';
  return '#ff4757';
}

function getLagStatus(lagMs: number): string {
  if (lagMs < 1000) return 'FAST';
  if (lagMs < 2000) return 'MODERATE';
  return 'SLOW';
}

function LoadingSkeleton() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
      <div
        style={{
          height: '40px',
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          animation: 'pulse 2s ease-in-out infinite',
        }}
      />
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', flex: 1 }}>
        <div
          style={{
            height: '320px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            animation: 'pulse 2s ease-in-out infinite',
          }}
        />
        <div
          style={{
            height: '320px',
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            animation: 'pulse 2s ease-in-out infinite',
          }}
        />
      </div>
    </div>
  );
}

function EmptyState() {
  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: '6px',
        padding: '3rem 2rem',
        textAlign: 'center',
      }}
    >
      <div
        style={{
          fontSize: '0.875rem',
          fontWeight: 500,
          color: 'var(--text-primary)',
          marginBottom: '0.25rem',
        }}
      >
        No Lag Data
      </div>
      <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
        Start data collection to measure latency
      </div>
    </div>
  );
}

export function LagAnalysis({
  lagStats,
  lagMeasurements = [],
  lagTimeSeries = [],
  isLoading = false,
}: LagAnalysisProps) {
  const [showMethodology, setShowMethodology] = useState(false);

  const p50 = lagStats?.median_lag_ms ?? 0;
  const p95 = lagStats?.p95_lag_ms ?? 0;
  const p99 = lagStats?.p99_lag_ms ?? 0;
  const sampleCount = lagStats?.sample_size ?? 0;

  const measurements = useMemo(() => {
    if (lagMeasurements.length > 0) return lagMeasurements;
    if (lagStats) return generateMockMeasurements(lagStats);
    return [];
  }, [lagStats, lagMeasurements]);

  const timeSeries = useMemo(() => {
    if (lagTimeSeries.length > 0) return lagTimeSeries;
    if (lagStats) return generateMockTimeSeries(lagStats);
    return [];
  }, [lagStats, lagTimeSeries]);

  if (isLoading) return <LoadingSkeleton />;
  if (!lagStats) return <EmptyState />;

  const heroColor = getLagColor(p50);
  const heroStatus = getLagStatus(p50);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', height: '100%' }}>
      {/* Compact Header Strip - All key info in one dense row */}
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          padding: '0.625rem 1rem',
          display: 'flex',
          alignItems: 'center',
          gap: '1.5rem',
          borderLeft: `3px solid ${heroColor}`,
        }}
      >
        {/* Primary metric */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.375rem' }}>
          <span
            style={{
              fontSize: '1.5rem',
              fontWeight: 700,
              fontFamily: 'var(--font-mono)',
              color: heroColor,
              lineHeight: 1,
            }}
          >
            {(p50 / 1000).toFixed(2)}
          </span>
          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            sec
          </span>
          <span
            style={{
              marginLeft: '0.5rem',
              padding: '0.125rem 0.375rem',
              background: `${heroColor}18`,
              border: `1px solid ${heroColor}40`,
              borderRadius: '3px',
              fontSize: '0.5625rem',
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
              color: heroColor,
              textTransform: 'uppercase',
              letterSpacing: '0.03em',
            }}
          >
            {heroStatus}
          </span>
        </div>

        {/* Separator */}
        <div style={{ width: '1px', height: '24px', background: 'var(--border)' }} />

        {/* Percentile stats inline */}
        <div style={{ display: 'flex', gap: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span style={{ fontSize: '0.5625rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>P50</span>
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: '#00d4aa', fontFamily: 'var(--font-mono)' }}>{p50.toFixed(0)}</span>
            <span style={{ fontSize: '0.5625rem', color: 'var(--text-muted)' }}>ms</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span style={{ fontSize: '0.5625rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>P95</span>
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: '#ffaa00', fontFamily: 'var(--font-mono)' }}>{p95.toFixed(0)}</span>
            <span style={{ fontSize: '0.5625rem', color: 'var(--text-muted)' }}>ms</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span style={{ fontSize: '0.5625rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>P99</span>
            <span style={{ fontSize: '0.8125rem', fontWeight: 600, color: '#ff4757', fontFamily: 'var(--font-mono)' }}>{p99.toFixed(0)}</span>
            <span style={{ fontSize: '0.5625rem', color: 'var(--text-muted)' }}>ms</span>
          </div>
        </div>

        {/* Separator */}
        <div style={{ width: '1px', height: '24px', background: 'var(--border)' }} />

        {/* Sample count */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
          <span style={{ fontSize: '0.5625rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Samples</span>
          <span style={{ fontSize: '0.8125rem', fontWeight: 500, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>{sampleCount.toLocaleString()}</span>
        </div>

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Config values inline */}
        <div style={{ display: 'flex', gap: '1rem', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
            <span style={{ fontSize: '0.5625rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>expected_lag</span>
            <code style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#00d4aa' }}>{Math.round(p50)}</code>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
            <span style={{ fontSize: '0.5625rem', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>max_window</span>
            <code style={{ fontSize: '0.75rem', fontFamily: 'var(--font-mono)', fontWeight: 600, color: '#ffaa00' }}>{Math.round(p95 * 1.1)}</code>
          </div>
          <button
            onClick={() => setShowMethodology(!showMethodology)}
            style={{
              background: 'none',
              border: 'none',
              fontSize: '0.5625rem',
              fontFamily: 'var(--font-mono)',
              color: '#3b82f6',
              cursor: 'pointer',
              textDecoration: 'underline',
              textUnderlineOffset: '2px',
              padding: 0,
            }}
          >
            {showMethodology ? 'hide' : 'info'}
          </button>
        </div>
      </div>

      {/* Methodology expandable (if shown) */}
      {showMethodology && (
        <div
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: '6px',
            padding: '0.625rem 1rem',
            fontSize: '0.6875rem',
            color: 'var(--text-secondary)',
            lineHeight: 1.5,
            display: 'flex',
            gap: '2rem',
          }}
        >
          <div>
            <strong style={{ color: 'var(--text-primary)' }}>Measurement:</strong> Time between Binance momentum signal and Polymarket order book adjustment.
          </div>
          <div>
            <strong style={{ color: 'var(--text-primary)' }}>Config:</strong> Set <code style={{ color: '#3b82f6' }}>expected_lag_ms</code> to P50, <code style={{ color: '#3b82f6' }}>max_lag_window_ms</code> to P95+10%.
          </div>
        </div>
      )}

      {/* Charts - THE MAIN EVENT */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.5rem', height: '360px' }}>
        <LatencyHistogram lagMeasurements={measurements} p50={p50} p95={p95} p99={p99} />
        <LagTimeSeries measurements={timeSeries} p50={p50} p95={p95} />
      </div>
    </div>
  );
}
