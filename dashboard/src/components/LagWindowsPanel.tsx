import type { LagWindow, ConfigSummary } from '../api/client';

interface Props {
  windows: LagWindow[];
  config?: ConfigSummary;
}

export function LagWindowsPanel({ windows, config }: Props) {
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
        <span style={{ fontSize: '1rem' }}>&#x23F1;</span>
        <span
          style={{
            fontSize: '0.75rem',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--text-secondary)',
          }}
        >
          Lag Windows
        </span>
        {windows.length > 0 && (
          <span
            style={{
              marginLeft: 'auto',
              fontSize: '0.6875rem',
              padding: '0.125rem 0.5rem',
              background: 'var(--accent-amber-dim)',
              color: 'var(--accent-amber)',
              borderRadius: '9999px',
              fontFamily: 'var(--font-mono)',
              animation: 'pulse 2s ease-in-out infinite',
            }}
          >
            {windows.length} ACTIVE
          </span>
        )}
      </div>

      {/* Config summary */}
      {config && (
        <div
          style={{
            padding: '0.75rem 1rem',
            borderBottom: '1px solid var(--border)',
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: '0.5rem',
            fontSize: '0.6875rem',
          }}
        >
          <div>
            <div style={{ color: 'var(--text-muted)', marginBottom: '0.125rem' }}>Window</div>
            <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-blue)' }}>
              {config.max_lag_window_ms}ms
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--text-muted)', marginBottom: '0.125rem' }}>Momentum Thr</div>
            <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-blue)' }}>
              {(config.momentum_threshold * 100).toFixed(2)}%
            </div>
          </div>
          <div>
            <div style={{ color: 'var(--text-muted)', marginBottom: '0.125rem' }}>Max Price</div>
            <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--accent-blue)' }}>
              ${config.max_combined_price.toFixed(3)}
            </div>
          </div>
        </div>
      )}

      {/* Active windows */}
      {windows.length === 0 ? (
        <div
          style={{
            padding: '1.5rem 1rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.75rem',
          }}
        >
          <div style={{ marginBottom: '0.25rem' }}>No active lag windows</div>
          <div style={{ fontSize: '0.6875rem' }}>Waiting for momentum signal...</div>
        </div>
      ) : (
        <div style={{ maxHeight: '200px', overflowY: 'auto' }}>
          {windows.map((window, idx) => {
            const remainingPct = (window.remaining_ms / (config?.max_lag_window_ms || 5000)) * 100;
            const isExpiring = remainingPct < 30;

            return (
              <div
                key={`${window.symbol}-${idx}`}
                style={{
                  padding: '0.75rem 1rem',
                  borderBottom: '1px solid var(--border-subtle)',
                  background: isExpiring ? 'var(--accent-red-dim)' : undefined,
                }}
              >
                {/* Symbol and winner */}
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    marginBottom: '0.5rem',
                  }}
                >
                  <div
                    style={{
                      fontFamily: 'var(--font-mono)',
                      fontSize: '0.875rem',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                    }}
                  >
                    {window.symbol}
                  </div>
                  <div
                    style={{
                      padding: '0.125rem 0.5rem',
                      borderRadius: 'var(--radius-sm)',
                      background:
                        window.expected_winner === 'UP'
                          ? 'var(--accent-green-dim)'
                          : 'var(--accent-red-dim)',
                      color:
                        window.expected_winner === 'UP'
                          ? 'var(--accent-green)'
                          : 'var(--accent-red)',
                      fontSize: '0.6875rem',
                      fontWeight: 600,
                    }}
                  >
                    {window.expected_winner}
                  </div>
                </div>

                {/* Progress bar */}
                <div
                  style={{
                    height: '4px',
                    background: 'var(--border)',
                    borderRadius: '2px',
                    marginBottom: '0.5rem',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      height: '100%',
                      width: `${remainingPct}%`,
                      background: isExpiring ? 'var(--accent-red)' : 'var(--accent-amber)',
                      borderRadius: '2px',
                      transition: 'width 0.3s',
                    }}
                  />
                </div>

                {/* Details */}
                <div
                  style={{
                    display: 'grid',
                    gridTemplateColumns: 'repeat(4, 1fr)',
                    gap: '0.5rem',
                    fontSize: '0.6875rem',
                  }}
                >
                  <div>
                    <div style={{ color: 'var(--text-muted)' }}>Remaining</div>
                    <div
                      style={{
                        fontFamily: 'var(--font-mono)',
                        color: isExpiring ? 'var(--accent-red)' : 'var(--text-primary)',
                      }}
                    >
                      {(window.remaining_ms / 1000).toFixed(1)}s
                    </div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-muted)' }}>Momentum</div>
                    <div
                      style={{
                        fontFamily: 'var(--font-mono)',
                        color: 'var(--accent-amber)',
                      }}
                    >
                      {(window.momentum * 100).toFixed(3)}%
                    </div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-muted)' }}>Spot</div>
                    <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                      ${window.spot_price.toFixed(2)}
                    </div>
                  </div>
                  <div>
                    <div style={{ color: 'var(--text-muted)' }}>Candle Open</div>
                    <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                      ${window.candle_open.toFixed(2)}
                    </div>
                  </div>
                </div>

                {/* Entry status */}
                {window.entry_made && (
                  <div
                    style={{
                      marginTop: '0.5rem',
                      padding: '0.25rem 0.5rem',
                      background: 'var(--accent-green-dim)',
                      borderRadius: 'var(--radius-sm)',
                      color: 'var(--accent-green)',
                      fontSize: '0.6875rem',
                      fontWeight: 500,
                    }}
                  >
                    Entry Made
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
