import { AreaChart, Area, ResponsiveContainer } from 'recharts';
import type { SpotPriceData } from '../api/client';

interface Props {
  spotPrices: Record<string, SpotPriceData>;
}

// Map Binance symbols to display names
const SYMBOL_DISPLAY: Record<string, { name: string; short: string }> = {
  BTCUSDT: { name: 'Bitcoin', short: 'BTC' },
  ETHUSDT: { name: 'Ethereum', short: 'ETH' },
  SOLUSDT: { name: 'Solana', short: 'SOL' },
  XRPUSDT: { name: 'XRP', short: 'XRP' },
  BNBUSDT: { name: 'BNB', short: 'BNB' },
  ADAUSDT: { name: 'Cardano', short: 'ADA' },
  DOGEUSDT: { name: 'Dogecoin', short: 'DOGE' },
  AVAXUSDT: { name: 'Avalanche', short: 'AVAX' },
  DOTUSDT: { name: 'Polkadot', short: 'DOT' },
  LINKUSDT: { name: 'Chainlink', short: 'LINK' },
  LTCUSDT: { name: 'Litecoin', short: 'LTC' },
  SHIBUSDT: { name: 'Shiba Inu', short: 'SHIB' },
  NEARUSDT: { name: 'NEAR', short: 'NEAR' },
  APTUSDT: { name: 'Aptos', short: 'APT' },
};

function formatPrice(price: number | null | undefined): string {
  if (price === null || price === undefined) return '-';
  if (price >= 1000) return `$${price.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
  if (price >= 1) return `$${price.toFixed(2)}`;
  if (price >= 0.01) return `$${price.toFixed(4)}`;
  return `$${price.toFixed(6)}`;
}

function SpotPriceCard({
  symbol,
  data,
}: {
  symbol: string;
  data: SpotPriceData;
}) {
  const display = SYMBOL_DISPLAY[symbol] || { name: symbol, short: symbol.replace('USDT', '') };
  const momentum = data.momentum ?? 0;
  const momentumPct = momentum * 100;
  const isUp = momentum >= 0;

  // Prepare chart data
  const chartData = data.history.map((point) => ({
    ts: point.ts,
    price: point.price,
  }));

  return (
    <div
      style={{
        background: 'var(--bg-elevated)',
        borderRadius: 'var(--radius-sm)',
        padding: '0.5rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.25rem',
      }}
    >
      {/* Header: symbol and momentum */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '0.5rem',
        }}
      >
        <div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: '0.75rem',
              fontWeight: 600,
              color: 'var(--text-primary)',
            }}
          >
            {display.short}
          </div>
          <div
            style={{
              fontSize: '0.625rem',
              color: 'var(--text-muted)',
            }}
          >
            {display.name}
          </div>
        </div>
        <div
          style={{
            padding: '0.125rem 0.375rem',
            borderRadius: 'var(--radius-sm)',
            background: isUp ? 'var(--accent-green-dim)' : 'var(--accent-red-dim)',
            color: isUp ? 'var(--accent-green)' : 'var(--accent-red)',
            fontSize: '0.625rem',
            fontFamily: 'var(--font-mono)',
            fontWeight: 500,
          }}
        >
          {isUp ? '+' : ''}
          {momentumPct.toFixed(3)}%
        </div>
      </div>

      {/* Price */}
      <div
        style={{
          fontFamily: 'var(--font-mono)',
          fontSize: '0.875rem',
          fontWeight: 600,
          color: 'var(--text-primary)',
        }}
      >
        {formatPrice(data.price)}
      </div>

      {/* Sparkline */}
      {chartData.length > 1 && (
        <div style={{ height: '24px', marginTop: '0.125rem' }}>
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={chartData}>
              <defs>
                <linearGradient id={`gradient-${symbol}`} x1="0" y1="0" x2="0" y2="1">
                  <stop
                    offset="0%"
                    stopColor={isUp ? 'var(--accent-green)' : 'var(--accent-red)'}
                    stopOpacity={0.3}
                  />
                  <stop
                    offset="100%"
                    stopColor={isUp ? 'var(--accent-green)' : 'var(--accent-red)'}
                    stopOpacity={0}
                  />
                </linearGradient>
              </defs>
              <Area
                type="monotone"
                dataKey="price"
                stroke={isUp ? 'var(--accent-green)' : 'var(--accent-red)'}
                strokeWidth={1.5}
                fill={`url(#gradient-${symbol})`}
                dot={false}
                isAnimationActive={false}
              />
            </AreaChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Candle open */}
      {data.candle_open && (
        <div
          style={{
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: '0.5625rem',
            color: 'var(--text-muted)',
          }}
        >
          <span>Open</span>
          <span style={{ fontFamily: 'var(--font-mono)' }}>
            {formatPrice(data.candle_open)}
          </span>
        </div>
      )}
    </div>
  );
}

export function SpotPricesPanel({ spotPrices }: Props) {
  const symbols = Object.keys(spotPrices);

  if (symbols.length === 0) {
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
          <span style={{ fontSize: '1rem' }}>&#x1F4C8;</span>
          <span
            style={{
              fontSize: '0.75rem',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-secondary)',
            }}
          >
            Spot Prices
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
          No price data available
        </div>
      </div>
    );
  }

  // Sort symbols by a predefined order (major coins first)
  const sortOrder = [
    'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'XRPUSDT', 'BNBUSDT',
    'ADAUSDT', 'DOGEUSDT', 'AVAXUSDT', 'DOTUSDT', 'LINKUSDT',
    'LTCUSDT', 'SHIBUSDT', 'NEARUSDT', 'APTUSDT',
  ];
  const sortedSymbols = symbols.sort((a, b) => {
    const aIdx = sortOrder.indexOf(a);
    const bIdx = sortOrder.indexOf(b);
    if (aIdx === -1 && bIdx === -1) return a.localeCompare(b);
    if (aIdx === -1) return 1;
    if (bIdx === -1) return -1;
    return aIdx - bIdx;
  });

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
        <span style={{ fontSize: '1rem' }}>&#x1F4C8;</span>
        <span
          style={{
            fontSize: '0.75rem',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--text-secondary)',
          }}
        >
          Spot Prices
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
          {symbols.length} assets
        </span>
      </div>

      {/* Grid of price cards */}
      <div
        style={{
          padding: '0.75rem',
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))',
          gap: '0.5rem',
          maxHeight: '320px',
          overflowY: 'auto',
        }}
      >
        {sortedSymbols.map((symbol) => (
          <SpotPriceCard key={symbol} symbol={symbol} data={spotPrices[symbol]} />
        ))}
      </div>
    </div>
  );
}
