import {
  ComposedChart,
  Line,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';
import type { EquityCurvePoint } from '../../types/research.types';

interface Props {
  data: EquityCurvePoint[];
}

export function EquityCurve({ data }: Props) {
  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleDateString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  };

  const formatCurrency = (value: number) => {
    return `$${value.toFixed(2)}`;
  };

  const formatPercent = (value: number) => {
    return `${value.toFixed(2)}%`;
  };

  const chartData = data.map((point) => ({
    time: formatTime(point.timestamp),
    timestamp: point.timestamp,
    equity: point.equity,
    drawdown: -Math.abs(point.drawdown_pct),
  }));

  const hasData = chartData.length >= 2;

  const equityValues = chartData.map((d) => d.equity);
  const minEquity = Math.min(...equityValues);
  const maxEquity = Math.max(...equityValues);
  const equityPadding = (maxEquity - minEquity) * 0.1 || 10;

  const drawdownValues = chartData.map((d) => d.drawdown);
  const minDrawdown = Math.min(...drawdownValues, 0);

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        borderRadius: '6px',
        border: '1px solid var(--border)',
        overflow: 'hidden',
      }}
    >
      {/* Header */}
      <div
        style={{
          padding: '0.625rem 1rem',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          background: 'var(--bg-elevated)',
        }}
      >
        <span
          style={{
            fontSize: '0.5625rem',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--text-secondary)',
          }}
        >
          Equity Curve
        </span>
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '0.5625rem',
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
            padding: '3rem 2rem',
            textAlign: 'center',
          }}
        >
          <div
            style={{
              fontSize: '0.875rem',
              fontWeight: 500,
              color: 'var(--text-primary)',
              marginBottom: '0.25rem',
            }}
          >
            No Equity Data
          </div>
          <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
            Run a backtest to generate equity curve
          </div>
        </div>
      ) : (
        <div style={{ padding: '0.75rem', height: '360px' }}>
          <ResponsiveContainer width="100%" height="100%">
            <ComposedChart data={chartData} margin={{ top: 10, right: 10, left: -10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="var(--border-subtle)" />
              <XAxis
                dataKey="time"
                tick={{ fontSize: 9, fill: 'var(--text-muted)' }}
                stroke="var(--border)"
                interval="preserveStartEnd"
                tickMargin={8}
              />
              <YAxis
                yAxisId="equity"
                orientation="left"
                tickFormatter={(v) => `$${v.toFixed(0)}`}
                tick={{ fontSize: 9, fill: 'var(--text-muted)' }}
                stroke="var(--border)"
                domain={[minEquity - equityPadding, maxEquity + equityPadding]}
              />
              <YAxis
                yAxisId="drawdown"
                orientation="right"
                tickFormatter={(v) => `${v.toFixed(1)}%`}
                tick={{ fontSize: 9, fill: 'var(--text-muted)' }}
                stroke="var(--border)"
                domain={[minDrawdown * 1.1, 0]}
              />
              <Tooltip
                contentStyle={{
                  background: 'var(--bg-card)',
                  border: '1px solid var(--border)',
                  borderRadius: '4px',
                  fontSize: '0.6875rem',
                  padding: '0.5rem 0.75rem',
                }}
                formatter={(value: number, name: string) => {
                  if (name === 'equity') {
                    return [formatCurrency(value), 'Equity'];
                  }
                  return [formatPercent(value), 'Drawdown'];
                }}
                labelStyle={{ color: 'var(--text-muted)', marginBottom: '0.25rem' }}
              />
              <ReferenceLine yAxisId="drawdown" y={0} stroke="var(--border)" strokeDasharray="3 3" />
              <Area
                yAxisId="drawdown"
                type="monotone"
                dataKey="drawdown"
                stroke="#ff4757"
                fill="#ff4757"
                fillOpacity={0.2}
                strokeWidth={1}
                name="drawdown"
              />
              <Line
                yAxisId="equity"
                type="monotone"
                dataKey="equity"
                stroke="#00d4aa"
                strokeWidth={2}
                dot={false}
                name="equity"
              />
            </ComposedChart>
          </ResponsiveContainer>
        </div>
      )}

      {/* Legend */}
      {hasData && (
        <div
          style={{
            padding: '0.5rem 1rem',
            borderTop: '1px solid var(--border-subtle)',
            display: 'flex',
            justifyContent: 'center',
            gap: '1.5rem',
            fontSize: '0.5625rem',
            color: 'var(--text-muted)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <div
              style={{
                width: '12px',
                height: '2px',
                background: '#00d4aa',
                borderRadius: '1px',
              }}
            />
            <span>Equity</span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <div
              style={{
                width: '12px',
                height: '8px',
                background: '#ff4757',
                opacity: 0.3,
                borderRadius: '1px',
              }}
            />
            <span>Drawdown</span>
          </div>
        </div>
      )}
    </div>
  );
}
