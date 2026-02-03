import type { TradingOpportunity } from '../../types/research.types';

interface Props {
  opportunity: TradingOpportunity;
  highlighted?: boolean;
}

/**
 * Get confidence level label and color
 */
function getConfidenceConfig(score: number): { label: string; color: string; bgColor: string } {
  if (score >= 0.8) {
    return { label: 'HIGH', color: 'var(--accent-green)', bgColor: 'var(--accent-green-dim)' };
  }
  if (score >= 0.5) {
    return { label: 'MED', color: 'var(--accent-amber)', bgColor: 'var(--accent-amber-dim)' };
  }
  return { label: 'LOW', color: 'var(--text-muted)', bgColor: 'var(--bg-elevated)' };
}

/**
 * Format percentage for display
 */
function formatPct(value: number, decimals = 2): string {
  return `${(value * 100).toFixed(decimals)}%`;
}

/**
 * Single trading opportunity row
 * Shows direction, edge metrics, Kelly fraction, and confidence
 */
export function OpportunityRow({ opportunity, highlighted = false }: Props) {
  const isUp = opportunity.direction === 'UP';
  const directionColor = isUp ? 'var(--accent-green)' : 'var(--accent-red)';
  const directionBg = isUp ? 'rgba(0, 212, 170, 0.08)' : 'rgba(255, 71, 87, 0.08)';
  const directionArrow = isUp ? '\u2191' : '\u2193'; // Up/Down arrows
  const confidenceConfig = getConfidenceConfig(opportunity.confidence_score);

  // Determine if opportunity is actionable
  const isActionable = opportunity.is_tradeable && opportunity.edge_after_fees > 0;

  return (
    <div
      style={{
        padding: highlighted ? '0.75rem 1rem' : '0.5rem 1rem',
        background: opportunity.is_tradeable ? directionBg : 'var(--bg-elevated)',
        borderBottom: '1px solid var(--border-subtle)',
        opacity: opportunity.is_tradeable ? 1 : 0.5,
        position: 'relative',
        ...(highlighted && {
          boxShadow: `0 0 20px ${isUp ? 'rgba(0, 212, 170, 0.15)' : 'rgba(255, 71, 87, 0.15)'}`,
          borderLeft: `3px solid ${directionColor}`,
        }),
      }}
      title={opportunity.reject_reason || undefined}
    >
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: highlighted ? '50px 1fr 1fr 1fr 80px' : '40px 1fr 1fr 1fr 70px',
          gap: '0.5rem',
          alignItems: 'center',
        }}
      >
        {/* Direction indicator */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '0.25rem',
          }}
        >
          <span
            style={{
              fontSize: highlighted ? '1.25rem' : '1rem',
              fontWeight: 700,
              color: directionColor,
              fontFamily: 'var(--font-mono)',
            }}
          >
            {directionArrow}
          </span>
          <span
            style={{
              fontSize: highlighted ? '0.75rem' : '0.625rem',
              fontWeight: 600,
              color: directionColor,
              fontFamily: 'var(--font-mono)',
            }}
          >
            {opportunity.direction}
          </span>
        </div>

        {/* Raw Edge */}
        <div style={{ textAlign: 'right' }}>
          <div
            style={{
              fontSize: '0.5625rem',
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              marginBottom: '0.125rem',
            }}
          >
            Raw Edge
          </div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: highlighted ? '0.875rem' : '0.75rem',
              fontWeight: 600,
              color: opportunity.raw_edge > 0 ? 'var(--accent-green)' : 'var(--text-secondary)',
            }}
          >
            {opportunity.raw_edge > 0 ? '+' : ''}
            {formatPct(opportunity.raw_edge)}
          </div>
        </div>

        {/* Edge After Fees */}
        <div style={{ textAlign: 'right' }}>
          <div
            style={{
              fontSize: '0.5625rem',
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              marginBottom: '0.125rem',
            }}
          >
            After Fees
          </div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: highlighted ? '0.875rem' : '0.75rem',
              fontWeight: 600,
              color: isActionable ? 'var(--accent-green)' : 'var(--accent-red)',
            }}
          >
            {opportunity.edge_after_fees > 0 ? '+' : ''}
            {formatPct(opportunity.edge_after_fees)}
          </div>
        </div>

        {/* Kelly Fraction */}
        <div style={{ textAlign: 'right' }}>
          <div
            style={{
              fontSize: '0.5625rem',
              color: 'var(--text-muted)',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
              marginBottom: '0.125rem',
            }}
          >
            Kelly
          </div>
          <div
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: highlighted ? '0.875rem' : '0.75rem',
              fontWeight: 500,
              color: 'var(--text-primary)',
            }}
          >
            {formatPct(opportunity.kelly_fraction, 1)}
          </div>
        </div>

        {/* Confidence Badge */}
        <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
          <span
            style={{
              fontSize: highlighted ? '0.625rem' : '0.5625rem',
              fontWeight: 600,
              fontFamily: 'var(--font-mono)',
              padding: '0.125rem 0.375rem',
              borderRadius: 'var(--radius-sm)',
              background: confidenceConfig.bgColor,
              color: confidenceConfig.color,
              textTransform: 'uppercase',
            }}
          >
            {confidenceConfig.label}
          </span>
        </div>
      </div>

      {/* Reject reason indicator for non-tradeable opportunities */}
      {!opportunity.is_tradeable && opportunity.reject_reason && (
        <div
          style={{
            marginTop: '0.375rem',
            fontSize: '0.5625rem',
            color: 'var(--text-muted)',
            fontStyle: 'italic',
            display: 'flex',
            alignItems: 'center',
            gap: '0.25rem',
          }}
        >
          <span style={{ color: 'var(--accent-red)' }}>{'\u26A0'}</span>
          {opportunity.reject_reason}
        </div>
      )}
    </div>
  );
}
