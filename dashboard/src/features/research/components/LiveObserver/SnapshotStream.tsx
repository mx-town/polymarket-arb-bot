import { useRef, useEffect, useState, useCallback } from 'react';
import type { EnrichedSnapshot } from '../../types/research.types';

interface Props {
  snapshots: EnrichedSnapshot[];
  maxItems?: number;
}

export function SnapshotStream({ snapshots, maxItems = 100 }: Props) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isPaused, setIsPaused] = useState(false);
  const [newItemIds, setNewItemIds] = useState<Set<number>>(new Set());
  const prevLengthRef = useRef(snapshots.length);

  const displayedSnapshots = snapshots.slice(-maxItems);

  const trackNewItem = useCallback((timestamp: number) => {
    setNewItemIds((prev) => {
      const updated = new Set(prev);
      updated.add(timestamp);
      return updated;
    });
    setTimeout(() => {
      setNewItemIds((current) => {
        const cleaned = new Set(current);
        cleaned.delete(timestamp);
        return cleaned;
      });
    }, 500);
  }, []);

  useEffect(() => {
    if (!isPaused && containerRef.current && snapshots.length > 0) {
      containerRef.current.scrollTop = 0;
    }
  }, [snapshots.length, isPaused]);

  useEffect(() => {
    if (snapshots.length > prevLengthRef.current && snapshots.length > 0) {
      const latestTimestamp = snapshots[snapshots.length - 1].timestamp_ms;
      const timeoutId = setTimeout(() => trackNewItem(latestTimestamp), 0);
      prevLengthRef.current = snapshots.length;
      return () => clearTimeout(timeoutId);
    }
    prevLengthRef.current = snapshots.length;
  }, [snapshots, trackNewItem]);

  const formatTime = (timestampMs: number) => {
    const date = new Date(timestampMs);
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const formatPrice = (price: number) => {
    return price.toLocaleString('en-US', {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    });
  };

  const formatPercent = (value: number) => {
    const sign = value >= 0 ? '+' : '';
    return `${sign}${(value * 100).toFixed(3)}%`;
  };

  const formatProbability = (prob: number) => {
    return `${(prob * 100).toFixed(1)}%`;
  };

  const getDeviationColor = (deviation: number) => {
    const absDeviation = Math.abs(deviation);
    if (absDeviation >= 0.005) return '#ffaa00';
    if (absDeviation >= 0.002) return '#3b82f6';
    return 'var(--text-muted)';
  };

  const getEdgeColor = (edge: number) => {
    if (edge >= 0.02) return '#00d4aa';
    if (edge >= 0.01) return '#3b82f6';
    if (edge > 0) return 'var(--text-secondary)';
    return 'var(--text-muted)';
  };

  const reversedSnapshots = [...displayedSnapshots].reverse();

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        borderRadius: '6px',
        border: '1px solid var(--border)',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
        minHeight: '300px',
      }}
    >
      {/* Header row */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '70px 90px 80px 60px 70px 60px',
          gap: '0.5rem',
          padding: '0.5rem 0.75rem',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-elevated)',
          fontSize: '0.5625rem',
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          color: 'var(--text-muted)',
        }}
      >
        <span>Time</span>
        <span>BTC Price</span>
        <span>Deviation</span>
        <span>P(UP)</span>
        <span>Edge</span>
        <span>Signal</span>
      </div>

      {/* Scrollable content */}
      {displayedSnapshots.length === 0 ? (
        <div
          style={{
            background: 'var(--bg-card)',
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
            No Snapshots
          </div>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            Start observation to collect data
          </div>
        </div>
      ) : (
        <div
          ref={containerRef}
          onMouseEnter={() => setIsPaused(true)}
          onMouseLeave={() => setIsPaused(false)}
          style={{
            flex: 1,
            overflowY: 'auto',
            overflowX: 'hidden',
          }}
        >
          {reversedSnapshots.map((snapshot) => {
            const isNew = newItemIds.has(snapshot.timestamp_ms);
            return (
              <div
                key={snapshot.timestamp_ms}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '70px 90px 80px 60px 70px 60px',
                  gap: '0.5rem',
                  padding: '0.375rem 0.75rem',
                  borderBottom: '1px solid var(--border-subtle)',
                  fontSize: '0.6875rem',
                  fontFamily: 'var(--font-mono)',
                  animation: isNew ? 'slideIn 0.2s ease-out' : 'none',
                  background: snapshot.signal_detected
                    ? 'rgba(255, 170, 0, 0.08)'
                    : 'transparent',
                }}
              >
                <span style={{ color: 'var(--text-muted)' }}>
                  {formatTime(snapshot.timestamp_ms)}
                </span>
                <span style={{ color: 'var(--text-primary)', fontWeight: 500 }}>
                  ${formatPrice(snapshot.binance_price)}
                </span>
                <span style={{ color: getDeviationColor(snapshot.divergence_pct) }}>
                  {formatPercent(snapshot.divergence_pct)}
                </span>
                <span
                  style={{
                    color:
                      snapshot.model_prob_up >= 0.55
                        ? '#00d4aa'
                        : snapshot.model_prob_up <= 0.45
                          ? '#ff4757'
                          : 'var(--text-secondary)',
                  }}
                >
                  {formatProbability(snapshot.model_prob_up)}
                </span>
                <span style={{ color: getEdgeColor(snapshot.edge_after_fees) }}>
                  {formatPercent(snapshot.edge_after_fees)}
                </span>
                <span>
                  {snapshot.signal_detected ? (
                    <span
                      style={{
                        display: 'inline-flex',
                        alignItems: 'center',
                        gap: '0.25rem',
                        padding: '0.125rem 0.375rem',
                        background: '#ffaa00',
                        color: '#0a0a0f',
                        borderRadius: '9999px',
                        fontSize: '0.5625rem',
                        fontWeight: 600,
                      }}
                    >
                      SIG
                    </span>
                  ) : (
                    <span style={{ color: 'var(--text-muted)' }}>-</span>
                  )}
                </span>
              </div>
            );
          })}
        </div>
      )}

      {/* Footer with pause indicator */}
      {isPaused && displayedSnapshots.length > 0 && (
        <div
          style={{
            padding: '0.25rem 0.75rem',
            background: 'var(--bg-elevated)',
            borderTop: '1px solid var(--border)',
            fontSize: '0.5625rem',
            color: '#ffaa00',
            textAlign: 'center',
          }}
        >
          Auto-scroll paused (hover to pause)
        </div>
      )}
    </div>
  );
}
