import type { TradingEvent, EventType } from '../api/client';

interface Props {
  events: TradingEvent[];
}

// Event display configuration
const EVENT_CONFIG: Record<
  EventType,
  { icon: string; color: string; bgColor: string; label: string }
> = {
  DIRECTION: {
    icon: '\u26A1', // lightning
    color: 'var(--accent-amber)',
    bgColor: 'var(--accent-amber-dim)',
    label: 'Direction',
  },
  POSITION_OPENED: {
    icon: '\u25CE', // target
    color: 'var(--accent-green)',
    bgColor: 'var(--accent-green-dim)',
    label: 'Opened',
  },
  POSITION_CLOSED: {
    icon: '\u2713', // checkmark
    color: 'var(--accent-blue)',
    bgColor: 'var(--accent-blue-dim)',
    label: 'Closed',
  },
  LAG_WINDOW_OPEN: {
    icon: '\u23F1', // timer
    color: 'var(--accent-amber)',
    bgColor: 'var(--accent-amber-dim)',
    label: 'Window',
  },
  LAG_WINDOW_EXPIRED: {
    icon: '\u23F0', // alarm
    color: 'var(--text-muted)',
    bgColor: 'var(--bg-elevated)',
    label: 'Expired',
  },
  ENTRY_SKIP: {
    icon: '\u2298', // circle-slash
    color: 'var(--text-muted)',
    bgColor: 'var(--bg-elevated)',
    label: 'Skip',
  },
  BLOCKED: {
    icon: '\u26D4', // prohibition
    color: 'var(--accent-red)',
    bgColor: 'var(--accent-red-dim)',
    label: 'Blocked',
  },
  ENTRY_FAILED: {
    icon: '\u2717', // x-mark
    color: 'var(--accent-red)',
    bgColor: 'var(--accent-red-dim)',
    label: 'Failed',
  },
};

export function SignalFeed({ events }: Props) {
  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const getEventConfig = (type: string) => {
    return EVENT_CONFIG[type as EventType] || EVENT_CONFIG.DIRECTION;
  };

  const renderEventDetails = (event: TradingEvent) => {
    const type = event.type as EventType;

    switch (type) {
      case 'DIRECTION':
        return (
          <div
            style={{
              display: 'flex',
              gap: '0.75rem',
              color: 'var(--text-secondary)',
            }}
          >
            <span>
              <span style={{ color: 'var(--text-muted)' }}>Mom: </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--accent-amber)',
                }}
              >
                {event.momentum ? `${(event.momentum * 100).toFixed(3)}%` : '\u2014'}
              </span>
            </span>
            <span>
              <span style={{ color: 'var(--text-muted)' }}>Winner: </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  color:
                    event.expected_winner === 'UP' ? 'var(--accent-green)' : 'var(--accent-red)',
                }}
              >
                {event.expected_winner || '\u2014'}
              </span>
            </span>
          </div>
        );

      case 'POSITION_OPENED':
        return (
          <div
            style={{
              display: 'flex',
              gap: '0.75rem',
              color: 'var(--text-secondary)',
            }}
          >
            <span>
              <span style={{ color: 'var(--text-muted)' }}>Cost: </span>
              <span style={{ fontFamily: 'var(--font-mono)' }}>
                ${event.cost?.toFixed(4) || '\u2014'}
              </span>
            </span>
            <span>
              <span style={{ color: 'var(--text-muted)' }}>Profit: </span>
              <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-green)' }}>
                ${event.expected_profit?.toFixed(4) || '\u2014'}
              </span>
            </span>
          </div>
        );

      case 'POSITION_CLOSED':
        return (
          <div
            style={{
              display: 'flex',
              gap: '0.75rem',
              color: 'var(--text-secondary)',
            }}
          >
            <span>
              <span style={{ color: 'var(--text-muted)' }}>P&L: </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  color: (event.pnl || 0) >= 0 ? 'var(--accent-green)' : 'var(--accent-red)',
                }}
              >
                ${event.pnl?.toFixed(4) || '\u2014'}
              </span>
            </span>
            <span>
              <span style={{ color: 'var(--text-muted)' }}>Reason: </span>
              <span style={{ fontFamily: 'var(--font-mono)' }}>
                {event.exit_reason || '\u2014'}
              </span>
            </span>
          </div>
        );

      case 'LAG_WINDOW_OPEN':
        return (
          <div
            style={{
              display: 'flex',
              gap: '0.75rem',
              color: 'var(--text-secondary)',
            }}
          >
            <span>
              <span style={{ color: 'var(--text-muted)' }}>Winner: </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  color:
                    event.expected_winner === 'UP' ? 'var(--accent-green)' : 'var(--accent-red)',
                }}
              >
                {event.expected_winner || '\u2014'}
              </span>
            </span>
            <span>
              <span style={{ color: 'var(--text-muted)' }}>Window: </span>
              <span style={{ fontFamily: 'var(--font-mono)' }}>
                {event.window_duration_ms ? `${event.window_duration_ms}ms` : '\u2014'}
              </span>
            </span>
          </div>
        );

      case 'LAG_WINDOW_EXPIRED':
        return (
          <div style={{ color: 'var(--text-secondary)' }}>
            <span style={{ color: 'var(--text-muted)' }}>Entry: </span>
            <span
              style={{
                fontFamily: 'var(--font-mono)',
                color: event.entry_made ? 'var(--accent-green)' : 'var(--text-muted)',
              }}
            >
              {event.entry_made ? 'Yes' : 'No'}
            </span>
          </div>
        );

      case 'ENTRY_SKIP':
        return (
          <div style={{ color: 'var(--text-secondary)' }}>
            <span style={{ color: 'var(--text-muted)' }}>Reason: </span>
            <span style={{ fontFamily: 'var(--font-mono)' }}>{event.reason || '\u2014'}</span>
          </div>
        );

      case 'BLOCKED':
        return (
          <div style={{ color: 'var(--accent-red)' }}>
            <span style={{ color: 'var(--text-muted)' }}>Reason: </span>
            <span style={{ fontFamily: 'var(--font-mono)' }}>{event.reason || '\u2014'}</span>
          </div>
        );

      case 'ENTRY_FAILED':
        return (
          <div
            style={{
              display: 'flex',
              gap: '0.75rem',
              color: 'var(--text-secondary)',
            }}
          >
            <span>
              <span style={{ color: 'var(--text-muted)' }}>Up: </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  color: event.up_success ? 'var(--accent-green)' : 'var(--accent-red)',
                }}
              >
                {event.up_success ? 'OK' : 'Fail'}
              </span>
            </span>
            <span>
              <span style={{ color: 'var(--text-muted)' }}>Down: </span>
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  color: event.down_success ? 'var(--accent-green)' : 'var(--accent-red)',
                }}
              >
                {event.down_success ? 'OK' : 'Fail'}
              </span>
            </span>
          </div>
        );

      default:
        return null;
    }
  };

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '0.75rem 1rem',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          background: 'var(--bg-elevated)',
        }}
      >
        <span style={{ fontSize: '1rem' }}>&#x26A1;</span>
        <span
          style={{
            fontSize: '0.75rem',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--text-secondary)',
          }}
        >
          Event Feed
        </span>
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '0.6875rem',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          Last {events.length}
        </span>
      </div>

      {/* Events list */}
      {events.length === 0 ? (
        <div
          style={{
            padding: '1.5rem 1rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.75rem',
          }}
        >
          <div style={{ marginBottom: '0.25rem' }}>No events yet</div>
          <div style={{ fontSize: '0.6875rem' }}>Waiting for trading activity...</div>
        </div>
      ) : (
        <div
          style={{
            maxHeight: '300px',
            overflowY: 'auto',
          }}
        >
          {events.map((event, idx) => {
            const config = getEventConfig(event.type);
            return (
              <div
                key={`${event.timestamp}-${idx}`}
                style={{
                  padding: '0.5rem 1rem',
                  borderBottom: '1px solid var(--border-subtle)',
                  display: 'flex',
                  alignItems: 'flex-start',
                  gap: '0.75rem',
                  fontSize: '0.6875rem',
                }}
              >
                {/* Event type indicator */}
                <div
                  style={{
                    width: '24px',
                    height: '24px',
                    borderRadius: 'var(--radius-sm)',
                    background: config.bgColor,
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    color: config.color,
                    fontWeight: 700,
                    fontSize: '0.75rem',
                    flexShrink: 0,
                  }}
                >
                  {config.icon}
                </div>

                {/* Event details */}
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: '0.5rem',
                      marginBottom: '0.25rem',
                    }}
                  >
                    <span
                      style={{
                        fontFamily: 'var(--font-mono)',
                        fontWeight: 600,
                        color: 'var(--text-primary)',
                      }}
                    >
                      {event.symbol}
                    </span>
                    <span
                      style={{
                        padding: '0.0625rem 0.375rem',
                        borderRadius: 'var(--radius-sm)',
                        background: config.bgColor,
                        color: config.color,
                        fontSize: '0.5625rem',
                        fontWeight: 600,
                      }}
                    >
                      {config.label}
                    </span>
                  </div>

                  {renderEventDetails(event)}
                </div>

                {/* Timestamp */}
                <div
                  style={{
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--text-muted)',
                    fontSize: '0.625rem',
                    flexShrink: 0,
                  }}
                >
                  {formatTime(event.timestamp)}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
