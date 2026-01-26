import type { ActiveMarket } from '../api/client';

interface Props {
  markets: ActiveMarket[];
}

export function MarketsPanel({ markets }: Props) {
  if (markets.length === 0) {
    return (
      <div
        style={{
          background: 'var(--bg-card)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border)',
          padding: '1rem',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.5rem',
            marginBottom: '0.75rem',
          }}
        >
          <span style={{ fontSize: '1rem' }}>&#x25C9;</span>
          <span
            style={{
              fontSize: '0.75rem',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-secondary)',
            }}
          >
            Markets
          </span>
          <span
            style={{
              marginLeft: 'auto',
              fontSize: '0.6875rem',
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
            }}
          >
            0 watching
          </span>
        </div>
        <div
          style={{
            color: 'var(--text-muted)',
            fontSize: '0.75rem',
            textAlign: 'center',
            padding: '1rem',
          }}
        >
          No markets loaded
        </div>
      </div>
    );
  }

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
        <span style={{ fontSize: '1rem' }}>&#x25C9;</span>
        <span
          style={{
            fontSize: '0.75rem',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--text-secondary)',
          }}
        >
          Markets
        </span>
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '0.6875rem',
            padding: '0.125rem 0.5rem',
            background: 'var(--accent-blue-dim)',
            color: 'var(--accent-blue)',
            borderRadius: '9999px',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {markets.length} watching
        </span>
      </div>

      {/* Markets list */}
      <div
        style={{
          maxHeight: '300px',
          overflowY: 'auto',
        }}
      >
        {markets.map((market) => {
          const spread = market.combined_ask - market.combined_bid;
          const spreadPct = spread * 100;
          const isGoodSpread = spreadPct < 2;

          return (
            <div
              key={market.market_id}
              style={{
                padding: '0.75rem 1rem',
                borderBottom: '1px solid var(--border-subtle)',
                display: 'flex',
                flexDirection: 'column',
                gap: '0.5rem',
              }}
            >
              {/* Market name and validity */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                }}
              >
                <div
                  style={{
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    background: market.is_valid ? 'var(--accent-green)' : 'var(--accent-red)',
                  }}
                />
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.8125rem',
                    color: 'var(--text-primary)',
                    fontWeight: 500,
                  }}
                >
                  {market.slug}
                </span>
              </div>

              {/* Price info */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: 'repeat(4, 1fr)',
                  gap: '0.5rem',
                  fontSize: '0.6875rem',
                }}
              >
                <div>
                  <div style={{ color: 'var(--text-muted)', marginBottom: '0.125rem' }}>
                    Combined Ask
                  </div>
                  <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                    ${market.combined_ask.toFixed(4)}
                  </div>
                </div>
                <div>
                  <div style={{ color: 'var(--text-muted)', marginBottom: '0.125rem' }}>
                    Combined Bid
                  </div>
                  <div style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                    ${market.combined_bid.toFixed(4)}
                  </div>
                </div>
                <div>
                  <div style={{ color: 'var(--text-muted)', marginBottom: '0.125rem' }}>Spread</div>
                  <div
                    style={{
                      fontFamily: 'var(--font-mono)',
                      color: isGoodSpread ? 'var(--accent-green)' : 'var(--accent-amber)',
                    }}
                  >
                    {spreadPct.toFixed(2)}%
                  </div>
                </div>
                <div>
                  <div style={{ color: 'var(--text-muted)', marginBottom: '0.125rem' }}>
                    Profit If &lt;$1
                  </div>
                  <div
                    style={{
                      fontFamily: 'var(--font-mono)',
                      color: market.combined_ask < 1 ? 'var(--accent-green)' : 'var(--accent-red)',
                    }}
                  >
                    ${Math.max(0, 1 - market.combined_ask).toFixed(4)}
                  </div>
                </div>
              </div>

              {/* UP/DOWN prices */}
              <div
                style={{
                  display: 'grid',
                  gridTemplateColumns: '1fr 1fr',
                  gap: '0.75rem',
                  fontSize: '0.6875rem',
                  marginTop: '0.25rem',
                }}
              >
                <div
                  style={{
                    padding: '0.375rem 0.5rem',
                    background: 'var(--accent-green-dim)',
                    borderRadius: 'var(--radius-sm)',
                  }}
                >
                  <div
                    style={{
                      color: 'var(--accent-green)',
                      fontWeight: 500,
                      marginBottom: '0.125rem',
                    }}
                  >
                    UP
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Ask</span>
                    <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                      ${market.up_best_ask.toFixed(3)}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Bid</span>
                    <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                      ${market.up_best_bid.toFixed(3)}
                    </span>
                  </div>
                </div>
                <div
                  style={{
                    padding: '0.375rem 0.5rem',
                    background: 'var(--accent-red-dim)',
                    borderRadius: 'var(--radius-sm)',
                  }}
                >
                  <div
                    style={{
                      color: 'var(--accent-red)',
                      fontWeight: 500,
                      marginBottom: '0.125rem',
                    }}
                  >
                    DOWN
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Ask</span>
                    <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                      ${market.down_best_ask.toFixed(3)}
                    </span>
                  </div>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <span style={{ color: 'var(--text-muted)' }}>Bid</span>
                    <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                      ${market.down_best_bid.toFixed(3)}
                    </span>
                  </div>
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
