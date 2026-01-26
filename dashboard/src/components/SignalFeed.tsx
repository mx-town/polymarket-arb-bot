import type { SignalEntry } from '../api/client';

interface Props {
  signals: SignalEntry[];
}

export function SignalFeed({ signals }: Props) {
  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  return (
    <div style={{
      background: 'var(--bg-card)',
      borderRadius: 'var(--radius-md)',
      border: '1px solid var(--border)',
      overflow: 'hidden',
    }}>
      {/* Header */}
      <div style={{
        padding: '0.75rem 1rem',
        borderBottom: '1px solid var(--border)',
        display: 'flex',
        alignItems: 'center',
        gap: '0.5rem',
        background: 'var(--bg-elevated)',
      }}>
        <span style={{ fontSize: '1rem' }}>&#x26A1;</span>
        <span style={{
          fontSize: '0.75rem',
          fontWeight: 600,
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          color: 'var(--text-secondary)',
        }}>
          Signal Feed
        </span>
        <span style={{
          marginLeft: 'auto',
          fontSize: '0.6875rem',
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
        }}>
          Last {signals.length}
        </span>
      </div>

      {/* Signals list */}
      {signals.length === 0 ? (
        <div style={{
          padding: '1.5rem 1rem',
          textAlign: 'center',
          color: 'var(--text-muted)',
          fontSize: '0.75rem',
        }}>
          <div style={{ marginBottom: '0.25rem' }}>No signals yet</div>
          <div style={{ fontSize: '0.6875rem' }}>
            Waiting for price movements...
          </div>
        </div>
      ) : (
        <div style={{
          maxHeight: '250px',
          overflowY: 'auto',
        }}>
          {signals.map((signal, idx) => (
            <div
              key={`${signal.timestamp}-${idx}`}
              style={{
                padding: '0.5rem 1rem',
                borderBottom: '1px solid var(--border-subtle)',
                display: 'flex',
                alignItems: 'flex-start',
                gap: '0.75rem',
                fontSize: '0.6875rem',
              }}
            >
              {/* Direction indicator */}
              <div style={{
                width: '24px',
                height: '24px',
                borderRadius: 'var(--radius-sm)',
                background: signal.direction === 'UP'
                  ? 'var(--accent-green-dim)'
                  : signal.direction === 'DOWN'
                    ? 'var(--accent-red-dim)'
                    : 'var(--bg-elevated)',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: signal.direction === 'UP'
                  ? 'var(--accent-green)'
                  : signal.direction === 'DOWN'
                    ? 'var(--accent-red)'
                    : 'var(--text-muted)',
                fontWeight: 700,
                fontSize: '0.625rem',
                flexShrink: 0,
              }}>
                {signal.direction === 'UP' ? '&#x2191;' : signal.direction === 'DOWN' ? '&#x2193;' : '?'}
              </div>

              {/* Signal details */}
              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  marginBottom: '0.25rem',
                }}>
                  <span style={{
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                  }}>
                    {signal.symbol}
                  </span>
                  <span style={{
                    padding: '0.0625rem 0.375rem',
                    borderRadius: 'var(--radius-sm)',
                    background: signal.expected_winner === 'UP'
                      ? 'var(--accent-green-dim)'
                      : 'var(--accent-red-dim)',
                    color: signal.expected_winner === 'UP'
                      ? 'var(--accent-green)'
                      : 'var(--accent-red)',
                    fontSize: '0.5625rem',
                    fontWeight: 600,
                  }}>
                    {signal.expected_winner}
                  </span>
                </div>

                <div style={{
                  display: 'flex',
                  gap: '0.75rem',
                  color: 'var(--text-secondary)',
                }}>
                  <span>
                    <span style={{ color: 'var(--text-muted)' }}>Mom: </span>
                    <span style={{
                      fontFamily: 'var(--font-mono)',
                      color: 'var(--accent-amber)',
                    }}>
                      {signal.momentum ? `${(signal.momentum * 100).toFixed(3)}%` : '—'}
                    </span>
                  </span>
                  <span>
                    <span style={{ color: 'var(--text-muted)' }}>Spot: </span>
                    <span style={{ fontFamily: 'var(--font-mono)' }}>
                      ${signal.spot_price?.toFixed(2) || '—'}
                    </span>
                  </span>
                  <span>
                    <span style={{ color: 'var(--text-muted)' }}>Conf: </span>
                    <span style={{ fontFamily: 'var(--font-mono)' }}>
                      {signal.confidence ? `${(signal.confidence * 100).toFixed(0)}%` : '—'}
                    </span>
                  </span>
                </div>
              </div>

              {/* Timestamp */}
              <div style={{
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-muted)',
                fontSize: '0.625rem',
                flexShrink: 0,
              }}>
                {formatTime(signal.timestamp)}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
