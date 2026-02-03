import { useMemo } from 'react';
import type { TradingOpportunity } from '../../types/research.types';
import { OpportunityRow } from './OpportunityRow';

interface Props {
  opportunities: TradingOpportunity[];
}

/**
 * EdgeCalculator component
 * Displays trading opportunities sorted by edge with the best opportunity highlighted
 */
export function EdgeCalculator({ opportunities }: Props) {
  // Sort opportunities by edge after fees (descending)
  const sortedOpportunities = useMemo(() => {
    return [...opportunities].sort((a, b) => b.edge_after_fees - a.edge_after_fees);
  }, [opportunities]);

  // Separate best opportunity from the rest
  const bestOpportunity = sortedOpportunities.length > 0 ? sortedOpportunities[0] : null;
  const otherOpportunities = sortedOpportunities.slice(1);

  // Count tradeable vs rejected
  const tradeableCount = opportunities.filter((o) => o.is_tradeable).length;
  const rejectedCount = opportunities.length - tradeableCount;

  // Check if best opportunity is actually actionable
  const hasBestActionable =
    bestOpportunity && bestOpportunity.is_tradeable && bestOpportunity.edge_after_fees > 0;

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
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
        }}
      >
        <span style={{ fontSize: '1rem' }}>{'\u2316'}</span>
        <span
          style={{
            fontSize: '0.75rem',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--text-secondary)',
          }}
        >
          Trading Opportunities
        </span>

        {/* Count badge */}
        <span
          style={{
            marginLeft: 'auto',
            fontSize: '0.625rem',
            fontFamily: 'var(--font-mono)',
            padding: '0.125rem 0.5rem',
            borderRadius: '9999px',
            background: hasBestActionable ? 'var(--accent-green-dim)' : 'var(--bg-card)',
            color: hasBestActionable ? 'var(--accent-green)' : 'var(--text-muted)',
          }}
        >
          {opportunities.length} detected
        </span>
      </div>

      {/* Content */}
      {opportunities.length === 0 ? (
        // Empty state
        <div
          style={{
            padding: '2rem 1rem',
            textAlign: 'center',
            color: 'var(--text-muted)',
          }}
        >
          <div
            style={{
              fontSize: '1.5rem',
              marginBottom: '0.5rem',
              opacity: 0.5,
            }}
          >
            {'\u2300'}
          </div>
          <div style={{ fontSize: '0.75rem', marginBottom: '0.25rem' }}>
            No opportunities detected
          </div>
          <div style={{ fontSize: '0.625rem' }}>Waiting for market signals...</div>
        </div>
      ) : (
        <>
          {/* Best opportunity (highlighted) */}
          {bestOpportunity && (
            <div
              style={{
                background: hasBestActionable
                  ? 'linear-gradient(180deg, var(--bg-elevated) 0%, var(--bg-card) 100%)'
                  : 'var(--bg-elevated)',
              }}
            >
              <div
                style={{
                  padding: '0.5rem 1rem 0.25rem',
                  fontSize: '0.5625rem',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  color: hasBestActionable ? 'var(--accent-green)' : 'var(--text-muted)',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '0.375rem',
                }}
              >
                {hasBestActionable && (
                  <span
                    style={{
                      width: '6px',
                      height: '6px',
                      borderRadius: '50%',
                      background: 'var(--accent-green)',
                      animation: 'pulse 2s ease-in-out infinite',
                    }}
                  />
                )}
                Best Opportunity
              </div>
              <OpportunityRow opportunity={bestOpportunity} highlighted />
            </div>
          )}

          {/* Other opportunities (scrollable) */}
          {otherOpportunities.length > 0 && (
            <div>
              <div
                style={{
                  padding: '0.5rem 1rem 0.25rem',
                  fontSize: '0.5625rem',
                  fontWeight: 600,
                  textTransform: 'uppercase',
                  letterSpacing: '0.08em',
                  color: 'var(--text-muted)',
                  borderTop: '1px solid var(--border)',
                }}
              >
                Other Opportunities ({otherOpportunities.length})
              </div>
              <div
                style={{
                  maxHeight: '240px',
                  overflowY: 'auto',
                }}
              >
                {otherOpportunities.map((opportunity, idx) => (
                  <OpportunityRow key={`${opportunity.direction}-${idx}`} opportunity={opportunity} />
                ))}
              </div>
            </div>
          )}
        </>
      )}

      {/* Footer summary */}
      {opportunities.length > 0 && (
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
            <span style={{ color: 'var(--accent-green)' }}>{tradeableCount}</span> tradeable
          </span>
          <span>
            <span style={{ color: 'var(--accent-red)' }}>{rejectedCount}</span> rejected
          </span>
        </div>
      )}
    </div>
  );
}
