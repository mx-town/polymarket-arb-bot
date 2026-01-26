import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  Cell,
  ReferenceLine,
} from 'recharts';
import type { ClosedTrade } from '../api/client';

interface Props {
  trades: ClosedTrade[];
}

export function ActivityChart({ trades }: Props) {
  // Show last 20 trades
  const recentTrades = trades.slice(-20);

  const chartData = recentTrades.map((trade, idx) => ({
    index: idx + 1,
    pnl: trade.pnl,
    market: trade.market_slug,
    reason: trade.exit_reason,
    duration: trade.hold_duration_sec,
  }));

  const hasTrades = chartData.length > 0;

  const formatPnl = (value: number) => {
    return `$${value.toFixed(4)}`;
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
        <span style={{ fontSize: '1rem' }}>&#x1F4CA;</span>
        <span
          style={{
            fontSize: '0.75rem',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--text-secondary)',
          }}
        >
          Trade Activity
        </span>
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '0.6875rem',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          Last {chartData.length} trades
        </span>
      </div>

      {/* Chart */}
      {!hasTrades ? (
        <div
          style={{
            padding: '2rem 1rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.75rem',
          }}
        >
          <div style={{ marginBottom: '0.25rem' }}>No closed trades yet</div>
          <div style={{ fontSize: '0.6875rem' }}>Bars will appear after positions are closed</div>
        </div>
      ) : (
        <div style={{ padding: '0.75rem', height: '180px' }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={chartData} margin={{ top: 5, right: 5, left: -15, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
              <XAxis
                dataKey="index"
                tick={{ fontSize: 10, fill: 'var(--text-muted)' }}
                stroke="var(--border)"
              />
              <YAxis
                tickFormatter={(v) => `$${v.toFixed(2)}`}
                tick={{ fontSize: 10, fill: 'var(--text-muted)' }}
                stroke="var(--border)"
              />
              <Tooltip
                contentStyle={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: '0.6875rem',
                }}
                formatter={(value: number) => [formatPnl(value), 'P&L']}
                labelFormatter={(label) => {
                  const trade = chartData[label - 1];
                  return trade ? `${trade.market} (${trade.reason})` : `Trade #${label}`;
                }}
                labelStyle={{ color: 'var(--text-muted)' }}
              />
              <ReferenceLine y={0} stroke="var(--border)" strokeWidth={1} />
              <Bar dataKey="pnl" name="P&L">
                {chartData.map((entry, index) => (
                  <Cell
                    key={`cell-${index}`}
                    fill={entry.pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'}
                  />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
