/**
 * EquityCurve component
 * Displays a line chart of cumulative P&L with drawdown area below
 */

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

  // Transform data for chart - drawdown should be negative for display below zero
  const chartData = data.map((point) => ({
    time: formatTime(point.timestamp),
    timestamp: point.timestamp,
    equity: point.equity,
    drawdown: -Math.abs(point.drawdown_pct), // Ensure negative for below-zero display
  }));

  const hasData = chartData.length >= 2;

  // Calculate Y-axis domain for equity
  const equityValues = chartData.map((d) => d.equity);
  const minEquity = Math.min(...equityValues);
  const maxEquity = Math.max(...equityValues);
  const equityPadding = (maxEquity - minEquity) * 0.1 || 10;

  // Calculate Y-axis domain for drawdown
  const drawdownValues = chartData.map((d) => d.drawdown);
  const minDrawdown = Math.min(...drawdownValues, 0);

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
          Equity Curve
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
          <div style={{ marginBottom: '0.25rem' }}>No equity data available</div>
          <div style={{ fontSize: '0.6875rem' }}>Run a backtest to generate equity curve</div>
        </div>
      ) : (
        <div style={{ padding: '0.75rem', height: '280px' }}>
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
              {/* Left Y-axis for Equity */}
              <YAxis
                yAxisId="equity"
                orientation="left"
                tickFormatter={(v) => `$${v.toFixed(0)}`}
                tick={{ fontSize: 9, fill: 'var(--text-muted)' }}
                stroke="var(--border)"
                domain={[minEquity - equityPadding, maxEquity + equityPadding]}
              />
              {/* Right Y-axis for Drawdown */}
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
                  borderRadius: 'var(--radius-sm)',
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
              {/* Drawdown area (red, below zero) */}
              <Area
                yAxisId="drawdown"
                type="monotone"
                dataKey="drawdown"
                stroke="var(--accent-red)"
                fill="var(--accent-red)"
                fillOpacity={0.2}
                strokeWidth={1}
                name="drawdown"
              />
              {/* Equity line (green) */}
              <Line
                yAxisId="equity"
                type="monotone"
                dataKey="equity"
                stroke="var(--accent-green)"
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
            fontSize: '0.625rem',
            color: 'var(--text-muted)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <div
              style={{
                width: '12px',
                height: '2px',
                background: 'var(--accent-green)',
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
                background: 'var(--accent-red)',
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
