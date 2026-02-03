import { useState, useEffect } from 'react';
import { type Signal, SignalType } from '../../types/research.types';

interface SignalTimelineProps {
  signals: Signal[];
}

// Signal tier color mapping
const SIGNAL_TIER_COLORS: Record<string, string> = {
  DUTCH_BOOK: '#ffaa00',
  LAG_ARB_UP: '#00fff2',
  LAG_ARB_DOWN: '#00fff2',
  MOMENTUM_UP: '#4a9eff',
  MOMENTUM_DOWN: '#4a9eff',
  FLASH_CRASH_UP: '#ff4757',
  FLASH_CRASH_DOWN: '#ff4757',
};

function getSignalColor(signalType: SignalType): string {
  return SIGNAL_TIER_COLORS[signalType] || 'var(--text-muted)';
}

// 5-minute bucket size in ms
const BUCKET_SIZE_MS = 5 * 60 * 1000;
// 60 minutes total
const TIMELINE_DURATION_MS = 60 * 60 * 1000;
const BUCKET_COUNT = 12; // 12 x 5-minute buckets

interface Bucket {
  startMs: number;
  endMs: number;
  signals: Signal[];
}

function groupSignalsIntoBuckets(signals: Signal[], nowMs: number): Bucket[] {
  const buckets: Bucket[] = [];
  const startOfTimeline = nowMs - TIMELINE_DURATION_MS;

  for (let i = 0; i < BUCKET_COUNT; i++) {
    const bucketStart = startOfTimeline + i * BUCKET_SIZE_MS;
    const bucketEnd = bucketStart + BUCKET_SIZE_MS;
    buckets.push({
      startMs: bucketStart,
      endMs: bucketEnd,
      signals: signals.filter((s) => s.timestamp_ms >= bucketStart && s.timestamp_ms < bucketEnd),
    });
  }

  return buckets;
}

function formatBucketTime(timestampMs: number): string {
  const date = new Date(timestampMs);
  return date.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function SignalTimeline({ signals }: SignalTimelineProps) {
  const [hoveredBucket, setHoveredBucket] = useState<number | null>(null);
  // Use state to capture time on mount and update periodically
  const [nowMs, setNowMs] = useState(() => Date.now());

  // Update time every 30 seconds to keep timeline fresh
  useEffect(() => {
    const interval = setInterval(() => setNowMs(Date.now()), 30000);
    return () => clearInterval(interval);
  }, []);

  const buckets = groupSignalsIntoBuckets(signals, nowMs);

  return (
    <div
      style={{
        background: 'var(--bg-elevated)',
        borderRadius: 'var(--radius-sm)',
        padding: '0.5rem',
      }}
    >
      {/* Timeline label */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '0.375rem',
        }}
      >
        <span
          style={{
            fontSize: '0.5625rem',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--text-muted)',
          }}
        >
          Last 60 Minutes
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.5625rem',
            color: 'var(--text-muted)',
          }}
        >
          {signals.length} signals
        </span>
      </div>

      {/* Timeline bar */}
      <div
        style={{
          display: 'flex',
          height: '24px',
          background: 'var(--bg-primary)',
          borderRadius: 'var(--radius-sm)',
          overflow: 'hidden',
          border: '1px solid var(--border-subtle)',
          position: 'relative',
        }}
      >
        {buckets.map((bucket, idx) => (
          <div
            key={idx}
            style={{
              flex: 1,
              position: 'relative',
              borderRight: idx < BUCKET_COUNT - 1 ? '1px solid var(--border-subtle)' : 'none',
              cursor: 'pointer',
              transition: 'background 0.15s',
              background: hoveredBucket === idx ? 'var(--bg-elevated)' : 'transparent',
            }}
            onMouseEnter={() => setHoveredBucket(idx)}
            onMouseLeave={() => setHoveredBucket(null)}
          >
            {/* Signal tick marks */}
            {bucket.signals.map((signal, signalIdx) => {
              // Position within bucket (0-1)
              const positionInBucket = (signal.timestamp_ms - bucket.startMs) / BUCKET_SIZE_MS;
              return (
                <div
                  key={signalIdx}
                  style={{
                    position: 'absolute',
                    left: `${positionInBucket * 100}%`,
                    top: '2px',
                    bottom: '2px',
                    width: '2px',
                    background: getSignalColor(signal.signal_type),
                    borderRadius: '1px',
                    opacity: 0.9,
                  }}
                />
              );
            })}

            {/* Hover tooltip */}
            {hoveredBucket === idx && (
              <div
                style={{
                  position: 'absolute',
                  bottom: '100%',
                  left: '50%',
                  transform: 'translateX(-50%)',
                  marginBottom: '4px',
                  padding: '0.25rem 0.5rem',
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-sm)',
                  whiteSpace: 'nowrap',
                  zIndex: 10,
                  boxShadow: '0 4px 12px rgba(0,0,0,0.3)',
                }}
              >
                <div
                  style={{
                    fontSize: '0.625rem',
                    color: 'var(--text-secondary)',
                    marginBottom: '0.125rem',
                  }}
                >
                  {formatBucketTime(bucket.startMs)} - {formatBucketTime(bucket.endMs)}
                </div>
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.6875rem',
                    color: 'var(--text-primary)',
                    fontWeight: 600,
                  }}
                >
                  {bucket.signals.length} signal{bucket.signals.length !== 1 ? 's' : ''}
                </div>
                {/* Signal type breakdown */}
                {bucket.signals.length > 0 && (
                  <div
                    style={{
                      display: 'flex',
                      gap: '0.375rem',
                      marginTop: '0.25rem',
                      flexWrap: 'wrap',
                    }}
                  >
                    {Object.entries(
                      bucket.signals.reduce(
                        (acc, s) => {
                          acc[s.signal_type] = (acc[s.signal_type] || 0) + 1;
                          return acc;
                        },
                        {} as Record<string, number>
                      )
                    ).map(([type, count]) => (
                      <span
                        key={type}
                        style={{
                          fontSize: '0.5rem',
                          padding: '0.0625rem 0.25rem',
                          borderRadius: '2px',
                          background: SIGNAL_TIER_COLORS[type] || 'var(--text-muted)',
                          color: '#0a0a0f',
                          fontWeight: 600,
                        }}
                      >
                        {count}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Time labels */}
      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          marginTop: '0.25rem',
          paddingLeft: '2px',
          paddingRight: '2px',
        }}
      >
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.5rem',
            color: 'var(--text-muted)',
          }}
        >
          -60m
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.5rem',
            color: 'var(--text-muted)',
          }}
        >
          -30m
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.5rem',
            color: 'var(--text-muted)',
          }}
        >
          now
        </span>
      </div>
    </div>
  );
}
