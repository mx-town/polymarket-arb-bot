import type { Signal } from '../../types/research.types';
import { SignalCard } from './SignalCard';
import { SignalTimeline } from './SignalTimeline';

interface SignalDetectorProps {
  signals: Signal[];
  onClear?: () => void;
}

const MAX_VISIBLE_SIGNALS = 10;

export function SignalDetector({ signals, onClear }: SignalDetectorProps) {
  // Sort signals by timestamp (newest first) and limit to max visible
  const sortedSignals = [...signals]
    .sort((a, b) => b.timestamp_ms - a.timestamp_ms)
    .slice(0, MAX_VISIBLE_SIGNALS);

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
        display: 'flex',
        flexDirection: 'column',
        height: '100%',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '0.75rem 1rem',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--bg-elevated)',
          flexShrink: 0,
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <span style={{ fontSize: '1rem' }}>&#x1F4E1;</span>
          <span
            style={{
              fontSize: '0.75rem',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-secondary)',
            }}
          >
            Signal Detector
          </span>
          <span
            style={{
              padding: '0.125rem 0.375rem',
              borderRadius: 'var(--radius-sm)',
              background: signals.length > 0 ? 'var(--accent-green)' : 'var(--bg-primary)',
              color: signals.length > 0 ? '#0a0a0f' : 'var(--text-muted)',
              fontSize: '0.625rem',
              fontFamily: 'var(--font-mono)',
              fontWeight: 600,
            }}
          >
            {signals.length}
          </span>
        </div>
        {signals.length > 0 && onClear && (
          <button
            onClick={onClear}
            style={{
              padding: '0.25rem 0.5rem',
              borderRadius: 'var(--radius-sm)',
              background: 'transparent',
              border: '1px solid var(--border)',
              color: 'var(--text-muted)',
              fontSize: '0.625rem',
              fontWeight: 500,
              cursor: 'pointer',
              transition: 'all 0.15s',
            }}
            onMouseEnter={(e) => {
              e.currentTarget.style.borderColor = 'var(--accent-red)';
              e.currentTarget.style.color = 'var(--accent-red)';
            }}
            onMouseLeave={(e) => {
              e.currentTarget.style.borderColor = 'var(--border)';
              e.currentTarget.style.color = 'var(--text-muted)';
            }}
          >
            Clear
          </button>
        )}
      </div>

      {/* Signals list */}
      <div
        style={{
          flex: 1,
          overflowY: 'auto',
          padding: '0.75rem',
        }}
      >
        {sortedSignals.length === 0 ? (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              justifyContent: 'center',
              padding: '2rem 1rem',
              textAlign: 'center',
            }}
          >
            <div
              style={{
                width: '48px',
                height: '48px',
                borderRadius: '50%',
                background: 'var(--bg-elevated)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                marginBottom: '0.75rem',
              }}
            >
              <span style={{ fontSize: '1.5rem', opacity: 0.5 }}>&#x1F4E1;</span>
            </div>
            <div
              style={{
                fontSize: '0.75rem',
                color: 'var(--text-secondary)',
                marginBottom: '0.25rem',
              }}
            >
              No signals detected
            </div>
            <div
              style={{
                fontSize: '0.6875rem',
                color: 'var(--text-muted)',
              }}
            >
              Waiting for trading opportunities...
            </div>
          </div>
        ) : (
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '0.5rem',
            }}
          >
            {sortedSignals.map((signal, idx) => (
              <SignalCard key={`${signal.timestamp_ms}-${idx}`} signal={signal} />
            ))}
          </div>
        )}
      </div>

      {/* Timeline footer */}
      <div
        style={{
          padding: '0.75rem',
          borderTop: '1px solid var(--border)',
          flexShrink: 0,
        }}
      >
        <SignalTimeline signals={signals} />
      </div>
    </div>
  );
}
