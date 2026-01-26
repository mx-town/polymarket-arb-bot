import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from 'recharts';
import type { PnlSnapshot } from '../api/client';

interface Props {
  data: PnlSnapshot[];
}

export function PnlChart({ data }: Props) {
  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const formatPnl = (value: number) => {
    return `$${value.toFixed(4)}`;
  };

  // Transform data for chart
  const chartData = data.map((snapshot) => ({
    time: formatTime(snapshot.timestamp),
    total_pnl: snapshot.total_pnl,
    realized_pnl: snapshot.realized_pnl,
  }));

  const hasData = chartData.length >= 3;

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
          P&L Over Time
        </span>
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '0.6875rem',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {chartData.length} points
        </span>
      </div>

      {/* Chart */}
      {!hasData ? (
        <div
          style={{
            padding: '2rem 1rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.75rem',
          }}
        >
          <div style={{ marginBottom: '0.25rem' }}>Collecting data...</div>
          <div style={{ fontSize: '0.6875rem' }}>Chart will appear after ~30 seconds of data</div>
        </div>
      ) : (
        <div style={{ padding: '0.75rem', height: '180px' }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 5, right: 5, left: -15, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
              <XAxis
                dataKey="time"
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
                formatter={(value: number) => [formatPnl(value), '']}
                labelStyle={{ color: 'var(--text-muted)' }}
              />
              <Line
                type="monotone"
                dataKey="total_pnl"
                stroke="var(--accent-green)"
                strokeWidth={2}
                dot={false}
                name="Total P&L"
              />
              <Line
                type="monotone"
                dataKey="realized_pnl"
                stroke="var(--accent-blue)"
                strokeWidth={1}
                strokeDasharray="4 4"
                dot={false}
                name="Realized P&L"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
