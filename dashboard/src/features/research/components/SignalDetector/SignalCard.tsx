import { type Signal, SignalType } from '../../types/research.types';

interface SignalCardProps {
  signal: Signal;
}

// Signal tier color configuration
const SIGNAL_COLORS: Record<string, { color: string; bgColor: string; label: string }> = {
  DUTCH_BOOK: {
    color: '#ffaa00',
    bgColor: 'rgba(255, 170, 0, 0.15)',
    label: 'Dutch Book',
  },
  LAG_ARB_UP: {
    color: '#00fff2',
    bgColor: 'rgba(0, 255, 242, 0.12)',
    label: 'Lag Arb UP',
  },
  LAG_ARB_DOWN: {
    color: '#00fff2',
    bgColor: 'rgba(0, 255, 242, 0.12)',
    label: 'Lag Arb DOWN',
  },
  MOMENTUM_UP: {
    color: '#4a9eff',
    bgColor: 'rgba(74, 158, 255, 0.12)',
    label: 'Momentum UP',
  },
  MOMENTUM_DOWN: {
    color: '#4a9eff',
    bgColor: 'rgba(74, 158, 255, 0.12)',
    label: 'Momentum DOWN',
  },
  FLASH_CRASH_UP: {
    color: '#ff4757',
    bgColor: 'rgba(255, 71, 87, 0.15)',
    label: 'Flash Crash UP',
  },
  FLASH_CRASH_DOWN: {
    color: '#ff4757',
    bgColor: 'rgba(255, 71, 87, 0.15)',
    label: 'Flash Crash DOWN',
  },
};

function getSignalConfig(signalType: SignalType) {
  return (
    SIGNAL_COLORS[signalType] || {
      color: 'var(--text-muted)',
      bgColor: 'var(--bg-elevated)',
      label: signalType,
    }
  );
}

function formatTime(timestampMs: number): string {
  const date = new Date(timestampMs);
  return date.toLocaleTimeString('en-US', {
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
}

function formatPrice(price: number): string {
  return price.toFixed(4);
}

function formatPercent(value: number): string {
  return `${(value * 100).toFixed(2)}%`;
}

export function SignalCard({ signal }: SignalCardProps) {
  const config = getSignalConfig(signal.signal_type);

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
        padding: '0.75rem',
        animation: 'slideInFromLeft 0.3s ease-out',
      }}
    >
      {/* Header row: Badge + Timestamp */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          marginBottom: '0.5rem',
        }}
      >
        <span
          style={{
            padding: '0.125rem 0.5rem',
            borderRadius: 'var(--radius-sm)',
            background: config.bgColor,
            color: config.color,
            fontSize: '0.625rem',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.05em',
          }}
        >
          {config.label}
        </span>
        <span
          style={{
            fontFamily: 'var(--font-mono)',
            fontSize: '0.625rem',
            color: 'var(--text-muted)',
          }}
        >
          {formatTime(signal.timestamp_ms)}
        </span>
      </div>

      {/* Prices row */}
      <div
        style={{
          display: 'flex',
          gap: '1rem',
          marginBottom: '0.5rem',
        }}
      >
        <div style={{ flex: 1 }}>
          <span
            style={{
              fontSize: '0.5625rem',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-muted)',
              display: 'block',
              marginBottom: '0.125rem',
            }}
          >
            UP
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.875rem',
              fontWeight: 600,
              color: 'var(--accent-green)',
            }}
          >
            {formatPrice(signal.up_price)}
          </span>
        </div>
        <div style={{ flex: 1 }}>
          <span
            style={{
              fontSize: '0.5625rem',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-muted)',
              display: 'block',
              marginBottom: '0.125rem',
            }}
          >
            DOWN
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.875rem',
              fontWeight: 600,
              color: 'var(--accent-red)',
            }}
          >
            {formatPrice(signal.down_price)}
          </span>
        </div>
        <div style={{ flex: 1 }}>
          <span
            style={{
              fontSize: '0.5625rem',
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-muted)',
              display: 'block',
              marginBottom: '0.125rem',
            }}
          >
            Combined
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.875rem',
              fontWeight: 600,
              color: 'var(--text-primary)',
            }}
          >
            {formatPrice(signal.combined_price)}
          </span>
        </div>
      </div>

      {/* Edge row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.75rem',
          marginBottom: '0.5rem',
          fontSize: '0.6875rem',
        }}
      >
        <span>
          <span style={{ color: 'var(--text-muted)' }}>Edge: </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              color: signal.expected_edge > 0 ? 'var(--accent-green)' : 'var(--accent-red)',
              fontWeight: 500,
            }}
          >
            {formatPercent(signal.expected_edge)}
          </span>
        </span>
        <span>
          <span style={{ color: 'var(--text-muted)' }}>Deviation: </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              color: 'var(--accent-amber)',
              fontWeight: 500,
            }}
          >
            {formatPercent(signal.deviation_pct)}
          </span>
        </span>
      </div>

      {/* Confidence bar */}
      <div>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '0.25rem',
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
            Confidence
          </span>
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.625rem',
              color: 'var(--text-secondary)',
            }}
          >
            {formatPercent(signal.confidence)}
          </span>
        </div>
        <div
          style={{
            height: '4px',
            background: 'var(--bg-elevated)',
            borderRadius: '2px',
            overflow: 'hidden',
          }}
        >
          <div
            style={{
              height: '100%',
              width: `${Math.min(signal.confidence * 100, 100)}%`,
              background: config.color,
              borderRadius: '2px',
              transition: 'width 0.3s ease-out',
            }}
          />
        </div>
      </div>

      {/* Slide-in animation keyframes */}
      <style>
        {`
          @keyframes slideInFromLeft {
            from {
              opacity: 0;
              transform: translateX(-20px);
            }
            to {
              opacity: 1;
              transform: translateX(0);
            }
          }
        `}
      </style>
    </div>
  );
}
