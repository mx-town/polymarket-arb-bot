import { useState, useEffect } from 'react';
import { EquityCurve } from './EquityCurve';
import { TradeTable } from './TradeTable';
import { fetchBacktestResults } from '../../api/research-client';
import type { BacktestResult } from '../../types/research.types';

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
            borderTopColor: '#3b82f6',
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
          background: 'rgba(255, 71, 87, 0.1)',
          border: '1px solid #ff4757',
          borderRadius: '6px',
          padding: '1.5rem',
          textAlign: 'center',
        }}
      >
        <div
          style={{
            fontSize: '0.875rem',
            fontWeight: 600,
            color: '#ff4757',
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
          borderRadius: '6px',
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
          No Backtest Data
        </div>
        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>
          Run a backtest to see performance metrics and trade history
        </div>
      </div>
    );
  }

  const { metrics, equity_curve, trades } = results;

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

  const pnlColor = metrics.total_pnl >= 0 ? '#00d4aa' : '#ff4757';
  const winRateColor = metrics.win_rate >= 50 ? '#00d4aa' : '#ffaa00';
  const sharpeColor =
    metrics.sharpe_ratio >= 1 ? '#00d4aa' : metrics.sharpe_ratio >= 0 ? '#ffaa00' : '#ff4757';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem' }}>
      {/* Compact Header Strip */}
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          padding: '0.625rem 1rem',
          display: 'flex',
          alignItems: 'center',
          gap: '1.5rem',
          borderLeft: `3px solid ${pnlColor}`,
        }}
      >
        {/* Hero metric: Total PnL */}
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '0.375rem' }}>
          <span
            style={{
              fontSize: '1.5rem',
              fontWeight: 700,
              fontFamily: 'var(--font-mono)',
              color: pnlColor,
              lineHeight: 1,
            }}
          >
            {formatPnl(metrics.total_pnl)}
          </span>
          <span
            style={{
              fontSize: '0.5625rem',
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
              textTransform: 'uppercase',
            }}
          >
            P&L
          </span>
        </div>

        {/* Separator */}
        <div style={{ width: '1px', height: '24px', background: 'var(--border)' }} />

        {/* Secondary metrics inline */}
        <div style={{ display: 'flex', gap: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Win Rate
            </span>
            <span
              style={{
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: winRateColor,
                fontFamily: 'var(--font-mono)',
              }}
            >
              {formatPercent(metrics.win_rate)}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Sharpe
            </span>
            <span
              style={{
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: sharpeColor,
                fontFamily: 'var(--font-mono)',
              }}
            >
              {formatRatio(metrics.sharpe_ratio)}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Max DD
            </span>
            <span
              style={{
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: '#ff4757',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {formatPercent(metrics.max_drawdown_pct)}
            </span>
          </div>
        </div>

        {/* Separator */}
        <div style={{ width: '1px', height: '24px', background: 'var(--border)' }} />

        {/* Trade counts */}
        <div style={{ display: 'flex', gap: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Trades
            </span>
            <span
              style={{
                fontSize: '0.8125rem',
                fontWeight: 500,
                color: 'var(--text-secondary)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {metrics.total_trades}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Avg Trade
            </span>
            <span
              style={{
                fontSize: '0.8125rem',
                fontWeight: 500,
                color: 'var(--text-secondary)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {formatPercent(metrics.avg_trade_return)}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              W/L
            </span>
            <span
              style={{
                fontSize: '0.8125rem',
                fontWeight: 500,
                color: 'var(--text-secondary)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {metrics.winning_trades}/{metrics.losing_trades}
            </span>
          </div>
        </div>
      </div>

      {/* Equity Curve */}
      <EquityCurve data={equity_curve} />

      {/* Trade Table */}
      <TradeTable trades={trades} />
    </div>
  );
}
