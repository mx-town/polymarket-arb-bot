/**
 * BacktestResults component
 * Main tab content displaying backtest performance metrics, equity curve, and trade history
 */

import { useState, useEffect } from 'react';
import { EquityCurve } from './EquityCurve';
import { TradeTable } from './TradeTable';
import { fetchBacktestResults } from '../../api/research-client';
import type { BacktestResult } from '../../types/research.types';

interface MetricCardProps {
  label: string;
  value: string;
  color?: string;
  subValue?: string;
}

function MetricCard({ label, value, color, subValue }: MetricCardProps) {
  return (
    <div
      style={{
        background: 'var(--bg-elevated)',
        borderRadius: 'var(--radius-sm)',
        padding: '0.75rem 1rem',
        display: 'flex',
        flexDirection: 'column',
        gap: '0.25rem',
      }}
    >
      <div
        style={{
          fontSize: '0.625rem',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          color: 'var(--text-muted)',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: '1.125rem',
          fontWeight: 600,
          fontFamily: 'var(--font-mono)',
          color: color || 'var(--text-primary)',
        }}
      >
        {value}
      </div>
      {subValue && (
        <div
          style={{
            fontSize: '0.625rem',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          {subValue}
        </div>
      )}
    </div>
  );
}

export function BacktestResults() {
  const [results, setResults] = useState<BacktestResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let mounted = true;

    async function loadResults() {
      try {
        setLoading(true);
        setError(null);
        const data = await fetchBacktestResults();
        if (mounted) {
          setResults(data);
        }
      } catch (err) {
        if (mounted) {
          setError(err instanceof Error ? err.message : 'Failed to load backtest results');
        }
      } finally {
        if (mounted) {
          setLoading(false);
        }
      }
    }

    loadResults();

    return () => {
      mounted = false;
    };
  }, []);

  if (loading) {
    return (
      <div
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '3rem',
          color: 'var(--text-muted)',
        }}
      >
        <div
          style={{
            width: '32px',
            height: '32px',
            border: '2px solid var(--border)',
            borderTopColor: 'var(--accent-blue)',
            borderRadius: '50%',
            animation: 'spin 1s linear infinite',
            marginBottom: '1rem',
          }}
        />
        <style>
          {`
            @keyframes spin {
              to { transform: rotate(360deg); }
            }
          `}
        </style>
        <div style={{ fontSize: '0.75rem' }}>Loading backtest results...</div>
      </div>
    );
  }

  if (error) {
    return (
      <div
        style={{
          background: 'var(--accent-red-dim)',
          border: '1px solid var(--accent-red)',
          borderRadius: 'var(--radius-md)',
          padding: '1.5rem',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontSize: '0.875rem',
            fontWeight: 600,
            color: 'var(--accent-red)',
            marginBottom: '0.5rem',
          }}
        >
          Error Loading Results
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>{error}</div>
      </div>
    );
  }

  if (!results || results.trades.length === 0) {
    return (
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: 'var(--radius-md)',
          padding: '3rem',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontSize: '2rem',
            marginBottom: '1rem',
          }}
        >
          &#x1F4CA;
        </div>
        <div
          style={{
            fontSize: '0.875rem',
            fontWeight: 600,
            color: 'var(--text-primary)',
            marginBottom: '0.5rem',
          }}
        >
          No Backtest Data
        </div>
        <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
          Run a backtest to see performance metrics and trade history
        </div>
      </div>
    );
  }

  const { metrics, equity_curve, trades } = results;

  // Format metric values
  const formatPnl = (value: number) => {
    const prefix = value >= 0 ? '+' : '';
    return `${prefix}$${value.toFixed(2)}`;
  };

  const formatPercent = (value: number) => {
    return `${value.toFixed(2)}%`;
  };

  const formatRatio = (value: number) => {
    return value.toFixed(2);
  };

  // Determine colors based on values
  const pnlColor = metrics.total_pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)';
  const winRateColor = metrics.win_rate >= 50 ? 'var(--accent-green)' : 'var(--accent-amber)';
  const sharpeColor = metrics.sharpe_ratio >= 1 ? 'var(--accent-green)' : metrics.sharpe_ratio >= 0 ? 'var(--accent-amber)' : 'var(--accent-red)';
  const profitFactorColor = metrics.profit_factor >= 1.5 ? 'var(--accent-green)' : metrics.profit_factor >= 1 ? 'var(--accent-amber)' : 'var(--accent-red)';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {/* Performance Metrics Row */}
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
          <span style={{ fontSize: '1rem' }}>&#x1F3AF;</span>
          <span
            style={{
              fontSize: '0.75rem',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-secondary)',
            }}
          >
            Performance Metrics
          </span>
        </div>

        <div
          style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(6, 1fr)',
            gap: '0.75rem',
          }}
        >
          <MetricCard
            label="Total P&L"
            value={formatPnl(metrics.total_pnl)}
            color={pnlColor}
            subValue={`${metrics.winning_trades}W / ${metrics.losing_trades}L`}
          />
          <MetricCard
            label="Win Rate"
            value={formatPercent(metrics.win_rate)}
            color={winRateColor}
            subValue={`Avg Win: $${metrics.avg_win.toFixed(2)}`}
          />
          <MetricCard
            label="Sharpe Ratio"
            value={formatRatio(metrics.sharpe_ratio)}
            color={sharpeColor}
            subValue={`Sortino: ${formatRatio(metrics.sortino_ratio)}`}
          />
          <MetricCard
            label="Max Drawdown"
            value={formatPercent(metrics.max_drawdown_pct)}
            color="var(--accent-red)"
            subValue={`Avg Loss: $${Math.abs(metrics.avg_loss).toFixed(2)}`}
          />
          <MetricCard
            label="Profit Factor"
            value={formatRatio(metrics.profit_factor)}
            color={profitFactorColor}
            subValue={`Expectancy: $${metrics.expectancy.toFixed(2)}`}
          />
          <MetricCard
            label="Total Trades"
            value={metrics.total_trades.toString()}
            subValue={`Avg Return: ${formatPercent(metrics.avg_trade_return)}`}
          />
        </div>
      </div>

      {/* Equity Curve */}
      <EquityCurve data={equity_curve} />

      {/* Trade Table */}
      <TradeTable trades={trades} />
    </div>
  );
}
