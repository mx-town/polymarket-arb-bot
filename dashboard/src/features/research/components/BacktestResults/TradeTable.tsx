/**
 * TradeTable component
 * Scrollable table of backtest trades with sorting and filtering
 */

import { useState, useMemo } from 'react';
import type { BacktestTrade } from '../../types/research.types';

interface Props {
  trades: BacktestTrade[];
}

type SortKey = 'entry_time' | 'direction' | 'entry_price' | 'exit_price' | 'pnl' | 'return_pct';
type SortDirection = 'asc' | 'desc';
type DirectionFilter = 'ALL' | 'UP' | 'DOWN';

export function TradeTable({ trades }: Props) {
  const [sortKey, setSortKey] = useState<SortKey>('entry_time');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [directionFilter, setDirectionFilter] = useState<DirectionFilter>('ALL');

  // Filter trades by direction
  const filteredTrades = useMemo(() => {
    if (directionFilter === 'ALL') return trades;
    return trades.filter((t) => t.direction === directionFilter);
  }, [trades, directionFilter]);

  // Sort trades
  const sortedTrades = useMemo(() => {
    const sorted = [...filteredTrades].sort((a, b) => {
      let comparison = 0;
      switch (sortKey) {
        case 'entry_time':
          comparison = new Date(a.entry_time).getTime() - new Date(b.entry_time).getTime();
          break;
        case 'direction':
          comparison = a.direction.localeCompare(b.direction);
          break;
        case 'entry_price':
          comparison = a.entry_price - b.entry_price;
          break;
        case 'exit_price':
          comparison = a.exit_price - b.exit_price;
          break;
        case 'pnl':
          comparison = a.pnl - b.pnl;
          break;
        case 'return_pct':
          comparison = a.return_pct - b.return_pct;
          break;
        default:
          comparison = 0;
      }
      return sortDirection === 'asc' ? comparison : -comparison;
    });
    return sorted;
  }, [filteredTrades, sortKey, sortDirection]);

  const handleSort = (key: SortKey) => {
    if (sortKey === key) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDirection('desc');
    }
  };

  const formatTime = (timestamp: string) => {
    const date = new Date(timestamp);
    return date.toLocaleString('en-US', {
      month: 'short',
      day: 'numeric',
      hour: '2-digit',
      minute: '2-digit',
      hour12: false,
    });
  };

  const formatHoldTime = (entryTime: string, exitTime: string) => {
    const entry = new Date(entryTime).getTime();
    const exit = new Date(exitTime).getTime();
    const diffMs = exit - entry;
    const diffSec = Math.floor(diffMs / 1000);

    if (diffSec < 60) return `${diffSec}s`;
    if (diffSec < 3600) return `${Math.floor(diffSec / 60)}m`;
    return `${Math.floor(diffSec / 3600)}h ${Math.floor((diffSec % 3600) / 60)}m`;
  };

  const getSortIndicator = (key: SortKey) => {
    if (sortKey !== key) return null;
    return sortDirection === 'asc' ? ' \u25B2' : ' \u25BC';
  };

  const headerStyle = (key: SortKey): React.CSSProperties => ({
    textAlign: key === 'direction' ? 'center' : 'right',
    cursor: 'pointer',
    userSelect: 'none',
    padding: '0.5rem 0.75rem',
    fontSize: '0.625rem',
    fontWeight: sortKey === key ? 600 : 500,
    color: sortKey === key ? 'var(--text-primary)' : 'var(--text-muted)',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    whiteSpace: 'nowrap',
  });

  // Count trades by direction
  const upCount = trades.filter((t) => t.direction === 'UP').length;
  const downCount = trades.filter((t) => t.direction === 'DOWN').length;

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
          background: 'var(--bg-elevated)',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}>
          <span style={{ fontSize: '1rem' }}>&#x1F4CB;</span>
          <span
            style={{
              fontSize: '0.75rem',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-secondary)',
            }}
          >
            Trades
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
            {filteredTrades.length} trades
          </span>
        </div>

        {/* Direction filter */}
        <div
          style={{
            display: 'flex',
            background: 'var(--bg-card)',
            borderRadius: 'var(--radius-sm)',
            padding: '0.125rem',
            border: '1px solid var(--border-subtle)',
            width: 'fit-content',
          }}
        >
          {(['ALL', 'UP', 'DOWN'] as DirectionFilter[]).map((dir) => (
            <button
              key={dir}
              onClick={() => setDirectionFilter(dir)}
              style={{
                padding: '0.25rem 0.625rem',
                fontSize: '0.625rem',
                fontFamily: 'var(--font-mono)',
                fontWeight: directionFilter === dir ? 600 : 400,
                color:
                  directionFilter === dir
                    ? dir === 'UP'
                      ? 'var(--accent-green)'
                      : dir === 'DOWN'
                        ? 'var(--accent-red)'
                        : 'var(--text-primary)'
                    : 'var(--text-muted)',
                background: directionFilter === dir ? 'var(--bg-elevated)' : 'transparent',
                border: 'none',
                borderRadius: 'var(--radius-sm)',
                cursor: 'pointer',
                textTransform: 'uppercase',
              }}
            >
              {dir === 'ALL' ? `All (${trades.length})` : dir === 'UP' ? `Up (${upCount})` : `Down (${downCount})`}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      {trades.length === 0 ? (
        <div
          style={{
            padding: '2rem 1rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.75rem',
          }}
        >
          <div style={{ marginBottom: '0.25rem' }}>No trades available</div>
          <div style={{ fontSize: '0.6875rem' }}>Run a backtest to see trade history</div>
        </div>
      ) : (
        <div style={{ maxHeight: '320px', overflowY: 'auto' }}>
          {/* Table header */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: '40px 1fr 60px 70px 70px 70px 70px',
              borderBottom: '1px solid var(--border)',
              background: 'var(--bg-secondary)',
              position: 'sticky',
              top: 0,
              zIndex: 1,
            }}
          >
            <div style={{ ...headerStyle('entry_time'), textAlign: 'center' }}>#</div>
            <div style={{ ...headerStyle('entry_time'), textAlign: 'left' }} onClick={() => handleSort('entry_time')}>
              Time{getSortIndicator('entry_time')}
            </div>
            <div style={headerStyle('direction')} onClick={() => handleSort('direction')}>
              Dir{getSortIndicator('direction')}
            </div>
            <div style={headerStyle('entry_price')} onClick={() => handleSort('entry_price')}>
              Entry{getSortIndicator('entry_price')}
            </div>
            <div style={headerStyle('exit_price')} onClick={() => handleSort('exit_price')}>
              Exit{getSortIndicator('exit_price')}
            </div>
            <div style={headerStyle('pnl')} onClick={() => handleSort('pnl')}>
              P&L{getSortIndicator('pnl')}
            </div>
            <div style={{ ...headerStyle('return_pct'), textAlign: 'right' }}>Hold</div>
          </div>

          {/* Table rows */}
          {sortedTrades.map((trade, idx) => {
            const isWin = trade.pnl >= 0;
            const rowBg = isWin ? 'rgba(0, 212, 170, 0.04)' : 'rgba(255, 71, 87, 0.04)';

            return (
              <div
                key={`${trade.entry_time}-${idx}`}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '40px 1fr 60px 70px 70px 70px 70px',
                  borderBottom: '1px solid var(--border-subtle)',
                  background: rowBg,
                  fontSize: '0.6875rem',
                  fontFamily: 'var(--font-mono)',
                }}
              >
                <div
                  style={{
                    padding: '0.5rem 0.75rem',
                    textAlign: 'center',
                    color: 'var(--text-muted)',
                  }}
                >
                  {idx + 1}
                </div>
                <div
                  style={{
                    padding: '0.5rem 0.75rem',
                    color: 'var(--text-secondary)',
                    overflow: 'hidden',
                    textOverflow: 'ellipsis',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {formatTime(trade.entry_time)}
                </div>
                <div
                  style={{
                    padding: '0.5rem 0.75rem',
                    textAlign: 'center',
                  }}
                >
                  <span
                    style={{
                      padding: '0.125rem 0.375rem',
                      borderRadius: 'var(--radius-sm)',
                      fontSize: '0.5625rem',
                      fontWeight: 600,
                      background: trade.direction === 'UP' ? 'var(--accent-green-dim)' : 'var(--accent-red-dim)',
                      color: trade.direction === 'UP' ? 'var(--accent-green)' : 'var(--accent-red)',
                    }}
                  >
                    {trade.direction}
                  </span>
                </div>
                <div
                  style={{
                    padding: '0.5rem 0.75rem',
                    textAlign: 'right',
                    color: 'var(--text-secondary)',
                  }}
                >
                  ${trade.entry_price.toFixed(3)}
                </div>
                <div
                  style={{
                    padding: '0.5rem 0.75rem',
                    textAlign: 'right',
                    color: 'var(--text-secondary)',
                  }}
                >
                  ${trade.exit_price.toFixed(3)}
                </div>
                <div
                  style={{
                    padding: '0.5rem 0.75rem',
                    textAlign: 'right',
                    fontWeight: 600,
                    color: isWin ? 'var(--accent-green)' : 'var(--accent-red)',
                  }}
                >
                  {isWin ? '+' : ''}${trade.pnl.toFixed(2)}
                </div>
                <div
                  style={{
                    padding: '0.5rem 0.75rem',
                    textAlign: 'right',
                    color: 'var(--text-muted)',
                  }}
                >
                  {formatHoldTime(trade.entry_time, trade.exit_time)}
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Footer summary */}
      {trades.length > 0 && (
        <div
          style={{
            padding: '0.5rem 1rem',
            borderTop: '1px solid var(--border)',
            background: 'var(--bg-elevated)',
            display: 'flex',
            justifyContent: 'space-between',
            fontSize: '0.625rem',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-muted)',
          }}
        >
          <span>
            {filteredTrades.filter((t) => t.pnl >= 0).length} wins | {filteredTrades.filter((t) => t.pnl < 0).length}{' '}
            losses
          </span>
          <span
            style={{
              color:
                filteredTrades.reduce((sum, t) => sum + t.pnl, 0) >= 0
                  ? 'var(--accent-green)'
                  : 'var(--accent-red)',
            }}
          >
            Total: {filteredTrades.reduce((sum, t) => sum + t.pnl, 0) >= 0 ? '+' : ''}$
            {filteredTrades.reduce((sum, t) => sum + t.pnl, 0).toFixed(2)}
          </span>
        </div>
      )}
    </div>
  );
}
