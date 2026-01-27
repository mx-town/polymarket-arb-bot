import { useState, useMemo } from 'react';
import type { ActiveMarket } from '../api/client';

interface Props {
  markets: ActiveMarket[];
}

type SortKey = 'spread' | 'profit' | 'combined';
type IntervalFilter = 'all' | '1h' | '15m';

// Extract asset and interval from market slug
// e.g., "btc-updown-1h-jan-27-2026" -> { asset: "BTC", interval: "1h" }
function parseMarketSlug(slug: string): { asset: string; interval: string } {
  const parts = slug.toLowerCase().split('-');
  const asset = parts[0]?.toUpperCase() || 'UNKNOWN';

  // Look for interval in slug
  let interval = '1h'; // default
  for (const part of parts) {
    if (part === '1h' || part === '15m' || part === '5m') {
      interval = part;
      break;
    }
  }

  return { asset, interval };
}

// Check if market is tradeable (1h = 0% fees)
function isTradeable(interval: string): boolean {
  return interval === '1h';
}

export function MarketsPanel({ markets }: Props) {
  const [expandedAssets, setExpandedAssets] = useState<Set<string>>(new Set(['BTC', 'ETH']));
  const [sortKey, setSortKey] = useState<SortKey>('profit');
  const [intervalFilter, setIntervalFilter] = useState<IntervalFilter>('all');

  // Parse and enrich markets with asset/interval info
  const enrichedMarkets = useMemo(() => {
    return markets.map((market) => {
      const { asset, interval } = parseMarketSlug(market.slug);
      const spread = market.combined_ask - market.combined_bid;
      const profit = Math.max(0, 1 - market.combined_ask);
      return { ...market, asset, interval, spread, profit };
    });
  }, [markets]);

  // Filter by interval
  const filteredMarkets = useMemo(() => {
    if (intervalFilter === 'all') return enrichedMarkets;
    return enrichedMarkets.filter((m) => m.interval === intervalFilter);
  }, [enrichedMarkets, intervalFilter]);

  // Group markets by asset
  const groupedMarkets = useMemo(() => {
    const groups: Record<string, typeof filteredMarkets> = {};

    for (const market of filteredMarkets) {
      if (!groups[market.asset]) {
        groups[market.asset] = [];
      }
      groups[market.asset].push(market);
    }

    // Sort within each group
    for (const asset in groups) {
      groups[asset].sort((a, b) => {
        switch (sortKey) {
          case 'spread':
            return a.spread - b.spread; // Lower spread first
          case 'profit':
            return b.profit - a.profit; // Higher profit first
          case 'combined':
            return a.combined_ask - b.combined_ask; // Lower combined first
          default:
            return 0;
        }
      });
    }

    return groups;
  }, [filteredMarkets, sortKey]);

  // Sort asset groups by total profit potential
  const sortedAssets = useMemo(() => {
    return Object.keys(groupedMarkets).sort((a, b) => {
      const totalA = groupedMarkets[a].reduce((sum, m) => sum + m.profit, 0);
      const totalB = groupedMarkets[b].reduce((sum, m) => sum + m.profit, 0);
      return totalB - totalA;
    });
  }, [groupedMarkets]);

  const toggleAsset = (asset: string) => {
    setExpandedAssets((prev) => {
      const next = new Set(prev);
      if (next.has(asset)) {
        next.delete(asset);
      } else {
        next.add(asset);
      }
      return next;
    });
  };

  const expandAll = () => setExpandedAssets(new Set(sortedAssets));
  const collapseAll = () => setExpandedAssets(new Set());

  // Count markets by interval
  const intervalCounts = useMemo(() => {
    const counts = { '1h': 0, '15m': 0 };
    for (const m of enrichedMarkets) {
      if (m.interval === '1h') counts['1h']++;
      else if (m.interval === '15m') counts['15m']++;
    }
    return counts;
  }, [enrichedMarkets]);

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
          background: 'var(--bg-elevated)',
        }}
      >
        <div
          style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginBottom: '0.5rem' }}
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
            {filteredMarkets.length} watching
          </span>
        </div>

        {/* Controls row */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', flexWrap: 'wrap' }}>
          {/* Interval filter tabs */}
          <div
            style={{
              display: 'flex',
              background: 'var(--bg-card)',
              borderRadius: 'var(--radius-sm)',
              padding: '0.125rem',
              border: '1px solid var(--border-subtle)',
            }}
          >
            {(['all', '1h', '15m'] as IntervalFilter[]).map((interval) => (
              <button
                key={interval}
                onClick={() => setIntervalFilter(interval)}
                style={{
                  padding: '0.25rem 0.5rem',
                  fontSize: '0.625rem',
                  fontFamily: 'var(--font-mono)',
                  fontWeight: intervalFilter === interval ? 600 : 400,
                  color: intervalFilter === interval ? 'var(--text-primary)' : 'var(--text-muted)',
                  background: intervalFilter === interval ? 'var(--bg-elevated)' : 'transparent',
                  border: 'none',
                  borderRadius: 'var(--radius-sm)',
                  cursor: 'pointer',
                  textTransform: 'uppercase',
                }}
              >
                {interval === 'all'
                  ? `All (${markets.length})`
                  : `${interval} (${intervalCounts[interval]})`}
              </button>
            ))}
          </div>

          {/* Sort dropdown */}
          <select
            value={sortKey}
            onChange={(e) => setSortKey(e.target.value as SortKey)}
            style={{
              padding: '0.25rem 0.5rem',
              fontSize: '0.625rem',
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-secondary)',
              background: 'var(--bg-card)',
              border: '1px solid var(--border-subtle)',
              borderRadius: 'var(--radius-sm)',
              cursor: 'pointer',
            }}
          >
            <option value="profit">Sort: Profit</option>
            <option value="spread">Sort: Spread</option>
            <option value="combined">Sort: Combined</option>
          </select>

          {/* Expand/Collapse buttons */}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: '0.25rem' }}>
            <button
              onClick={expandAll}
              style={{
                padding: '0.25rem 0.5rem',
                fontSize: '0.625rem',
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-muted)',
                background: 'transparent',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                cursor: 'pointer',
              }}
            >
              Expand
            </button>
            <button
              onClick={collapseAll}
              style={{
                padding: '0.25rem 0.5rem',
                fontSize: '0.625rem',
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-muted)',
                background: 'transparent',
                border: '1px solid var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                cursor: 'pointer',
              }}
            >
              Collapse
            </button>
          </div>
        </div>
      </div>

      {/* Grouped markets */}
      <div style={{ maxHeight: '400px', overflowY: 'auto' }}>
        {sortedAssets.map((asset) => {
          const assetMarkets = groupedMarkets[asset];
          const isExpanded = expandedAssets.has(asset);
          const tradeableCount = assetMarkets.filter((m) => isTradeable(m.interval)).length;
          const totalProfit = assetMarkets.reduce((sum, m) => sum + m.profit, 0);

          return (
            <div key={asset}>
              {/* Asset header (collapsible) */}
              <div
                onClick={() => toggleAsset(asset)}
                style={{
                  padding: '0.5rem 1rem',
                  background: 'var(--bg-elevated)',
                  borderBottom: '1px solid var(--border-subtle)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.5rem',
                  cursor: 'pointer',
                  userSelect: 'none',
                }}
              >
                <span
                  style={{
                    fontSize: '0.625rem',
                    color: 'var(--text-muted)',
                    transition: 'transform 0.2s',
                    transform: isExpanded ? 'rotate(90deg)' : 'rotate(0deg)',
                  }}
                >
                  &#9654;
                </span>
                <span
                  style={{
                    fontFamily: 'var(--font-mono)',
                    fontSize: '0.75rem',
                    fontWeight: 600,
                    color: 'var(--text-primary)',
                  }}
                >
                  {asset}
                </span>
                <span
                  style={{
                    fontSize: '0.625rem',
                    color: 'var(--text-muted)',
                    fontFamily: 'var(--font-mono)',
                  }}
                >
                  ({assetMarkets.length})
                </span>
                {tradeableCount > 0 && (
                  <span
                    style={{
                      fontSize: '0.5625rem',
                      padding: '0.125rem 0.375rem',
                      background: 'var(--accent-green-dim)',
                      color: 'var(--accent-green)',
                      borderRadius: '9999px',
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 500,
                    }}
                  >
                    {tradeableCount} TRADEABLE
                  </span>
                )}
                <span
                  style={{
                    marginLeft: 'auto',
                    fontSize: '0.625rem',
                    fontFamily: 'var(--font-mono)',
                    color: totalProfit > 0 ? 'var(--accent-green)' : 'var(--text-muted)',
                  }}
                >
                  +${totalProfit.toFixed(3)}
                </span>
              </div>

              {/* Markets table */}
              {isExpanded && (
                <div>
                  {/* Table header */}
                  <div
                    style={{
                      display: 'grid',
                      gridTemplateColumns: '1fr 60px 70px 70px 60px',
                      gap: '0.25rem',
                      padding: '0.25rem 1rem',
                      fontSize: '0.5625rem',
                      color: 'var(--text-muted)',
                      fontFamily: 'var(--font-mono)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                      borderBottom: '1px solid var(--border-subtle)',
                    }}
                  >
                    <div>Market</div>
                    <div style={{ textAlign: 'right' }}>Interval</div>
                    <div style={{ textAlign: 'right' }}>Combined</div>
                    <div style={{ textAlign: 'right' }}>Spread</div>
                    <div style={{ textAlign: 'right' }}>Profit</div>
                  </div>

                  {/* Table rows */}
                  {assetMarkets.map((market) => {
                    const tradeable = isTradeable(market.interval);
                    return (
                      <div
                        key={market.market_id}
                        style={{
                          display: 'grid',
                          gridTemplateColumns: '1fr 60px 70px 70px 60px',
                          gap: '0.25rem',
                          padding: '0.375rem 1rem',
                          fontSize: '0.6875rem',
                          fontFamily: 'var(--font-mono)',
                          borderBottom: '1px solid var(--border-subtle)',
                          background: market.is_valid ? 'transparent' : 'var(--accent-red-dim)',
                        }}
                      >
                        <div
                          style={{
                            display: 'flex',
                            alignItems: 'center',
                            gap: '0.375rem',
                            overflow: 'hidden',
                          }}
                        >
                          <div
                            style={{
                              width: '5px',
                              height: '5px',
                              borderRadius: '50%',
                              background: market.is_valid
                                ? 'var(--accent-green)'
                                : 'var(--accent-red)',
                              flexShrink: 0,
                            }}
                          />
                          <span
                            style={{
                              color: 'var(--text-primary)',
                              overflow: 'hidden',
                              textOverflow: 'ellipsis',
                              whiteSpace: 'nowrap',
                            }}
                            title={market.slug}
                          >
                            {market.slug
                              .replace(`${asset.toLowerCase()}-updown-`, '')
                              .replace(/-/g, ' ')}
                          </span>
                        </div>
                        <div
                          style={{
                            textAlign: 'right',
                            color: tradeable ? 'var(--accent-green)' : 'var(--accent-amber)',
                          }}
                        >
                          <span
                            style={{
                              fontSize: '0.5625rem',
                              padding: '0.0625rem 0.25rem',
                              background: tradeable
                                ? 'var(--accent-green-dim)'
                                : 'var(--accent-amber-dim)',
                              borderRadius: '2px',
                            }}
                          >
                            {market.interval.toUpperCase()}
                          </span>
                        </div>
                        <div
                          style={{
                            textAlign: 'right',
                            color:
                              market.combined_ask < 1
                                ? 'var(--accent-green)'
                                : 'var(--text-secondary)',
                          }}
                        >
                          ${market.combined_ask.toFixed(3)}
                        </div>
                        <div
                          style={{
                            textAlign: 'right',
                            color:
                              market.spread < 0.02 ? 'var(--accent-green)' : 'var(--accent-amber)',
                          }}
                        >
                          {(market.spread * 100).toFixed(1)}%
                        </div>
                        <div
                          style={{
                            textAlign: 'right',
                            color: market.profit > 0 ? 'var(--accent-green)' : 'var(--text-muted)',
                            fontWeight: market.profit > 0.01 ? 600 : 400,
                          }}
                        >
                          {market.profit > 0 ? `+$${market.profit.toFixed(2)}` : '-'}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      </div>

      {/* Footer summary */}
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
          {sortedAssets.length} assets |{' '}
          {filteredMarkets.filter((m) => isTradeable(m.interval)).length} tradeable
        </span>
        <span style={{ color: 'var(--accent-green)' }}>
          Total: +${filteredMarkets.reduce((sum, m) => sum + m.profit, 0).toFixed(3)}
        </span>
      </div>
    </div>
  );
}
