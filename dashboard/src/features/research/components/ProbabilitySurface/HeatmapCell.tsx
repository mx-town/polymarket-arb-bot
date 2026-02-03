import { useState, useCallback } from 'react';

export interface HeatmapCellProps {
  /** Probability value between 0 and 1 */
  probability: number;
  /** Number of samples in this bucket */
  sampleSize: number;
  /** Whether this bucket has enough samples to be statistically reliable */
  isReliable: boolean;
  /** Lower bound of confidence interval */
  ciLower: number;
  /** Upper bound of confidence interval */
  ciUpper: number;
  /** Whether this cell is currently selected */
  isSelected?: boolean;
  /** Click handler */
  onClick?: () => void;
  /** Deviation bucket label for tooltip */
  deviationLabel?: string;
  /** Time remaining label for tooltip */
  timeLabel?: string;
}

/**
 * Get color based on probability value
 * Red (P<0.3) -> Gray (P~0.5) -> Green (P>0.7)
 */
function getProbabilityColor(probability: number): string {
  if (probability < 0.3) {
    // Red gradient: more red as probability approaches 0
    const intensity = 1 - probability / 0.3;
    return `rgba(255, 71, 87, ${0.4 + intensity * 0.6})`;
  } else if (probability > 0.7) {
    // Green gradient: more green as probability approaches 1
    const intensity = (probability - 0.7) / 0.3;
    return `rgba(0, 212, 170, ${0.4 + intensity * 0.6})`;
  } else {
    // Gray gradient for middle values (0.3-0.7)
    const distanceFromCenter = Math.abs(probability - 0.5);
    const grayIntensity = 0.3 + distanceFromCenter * 0.4;
    return `rgba(136, 136, 160, ${grayIntensity})`;
  }
}

/**
 * Get opacity based on sample size (more samples = more opaque)
 */
function getSampleSizeOpacity(sampleSize: number, isReliable: boolean): number {
  if (!isReliable || sampleSize === 0) {
    return 0.15;
  }
  // Scale from 0.3 to 1.0 based on sample size (logarithmic scale)
  const minSamples = 5;
  const maxSamples = 100;
  const clampedSize = Math.max(minSamples, Math.min(maxSamples, sampleSize));
  const logScale = Math.log(clampedSize) / Math.log(maxSamples);
  return 0.3 + logScale * 0.7;
}

/**
 * Individual cell in the probability heatmap
 * Displays probability with color coding and sample size opacity
 */
export function HeatmapCell({
  probability,
  sampleSize,
  isReliable,
  ciLower,
  ciUpper,
  isSelected = false,
  onClick,
  deviationLabel = '',
  timeLabel = '',
}: HeatmapCellProps) {
  const [isHovered, setIsHovered] = useState(false);

  const handleMouseEnter = useCallback(() => setIsHovered(true), []);
  const handleMouseLeave = useCallback(() => setIsHovered(false), []);

  const baseColor = getProbabilityColor(probability);
  const opacity = getSampleSizeOpacity(sampleSize, isReliable);

  // Format percentage for display
  const formatPercent = (value: number) => `${(value * 100).toFixed(1)}%`;

  return (
    <div
      onClick={onClick}
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
      style={{
        width: '100%',
        height: '100%',
        minWidth: '8px',
        minHeight: '16px',
        background: baseColor,
        opacity: opacity,
        cursor: onClick ? 'pointer' : 'default',
        position: 'relative',
        transition: 'transform 0.1s ease, box-shadow 0.1s ease',
        transform: isHovered ? 'scale(1.1)' : 'scale(1)',
        zIndex: isHovered ? 10 : 1,
        boxShadow: isHovered
          ? '0 2px 8px rgba(0, 0, 0, 0.4)'
          : 'none',
        borderRadius: '1px',
        animation: isSelected ? 'cellPulse 1.5s ease-in-out infinite' : 'none',
        outline: isSelected ? '2px solid var(--accent-amber)' : 'none',
        outlineOffset: '-1px',
      }}
    >
      {/* Tooltip on hover */}
      {isHovered && (
        <div
          style={{
            position: 'absolute',
            bottom: '100%',
            left: '50%',
            transform: 'translateX(-50%)',
            marginBottom: '8px',
            padding: '8px 12px',
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            boxShadow: '0 4px 12px rgba(0, 0, 0, 0.4)',
            zIndex: 100,
            whiteSpace: 'nowrap',
            pointerEvents: 'none',
          }}
        >
          <div
            style={{
              fontSize: '0.6875rem',
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-primary)',
              marginBottom: '4px',
            }}
          >
            <span style={{ color: 'var(--text-muted)' }}>P(Win): </span>
            <span
              style={{
                color:
                  probability > 0.7
                    ? 'var(--accent-green)'
                    : probability < 0.3
                      ? 'var(--accent-red)'
                      : 'var(--text-primary)',
                fontWeight: 600,
              }}
            >
              {formatPercent(probability)}
            </span>
          </div>
          <div
            style={{
              fontSize: '0.625rem',
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-secondary)',
              marginBottom: '2px',
            }}
          >
            <span style={{ color: 'var(--text-muted)' }}>CI: </span>
            [{formatPercent(ciLower)} - {formatPercent(ciUpper)}]
          </div>
          <div
            style={{
              fontSize: '0.625rem',
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-secondary)',
              marginBottom: '2px',
            }}
          >
            <span style={{ color: 'var(--text-muted)' }}>Samples: </span>
            <span style={{ color: isReliable ? 'var(--accent-green)' : 'var(--text-muted)' }}>
              {sampleSize}
            </span>
            {!isReliable && (
              <span style={{ color: 'var(--accent-amber)', marginLeft: '4px' }}>
                (low)
              </span>
            )}
          </div>
          {deviationLabel && (
            <div
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                marginTop: '4px',
                paddingTop: '4px',
                borderTop: '1px solid var(--border-subtle)',
              }}
            >
              {deviationLabel} | {timeLabel}
            </div>
          )}
          {/* Tooltip arrow */}
          <div
            style={{
              position: 'absolute',
              top: '100%',
              left: '50%',
              transform: 'translateX(-50%)',
              width: 0,
              height: 0,
              borderLeft: '6px solid transparent',
              borderRight: '6px solid transparent',
              borderTop: '6px solid var(--border)',
            }}
          />
        </div>
      )}

      {/* Pulsing animation styles */}
      <style>
        {`
          @keyframes cellPulse {
            0%, 100% {
              box-shadow: 0 0 0 0 rgba(255, 170, 0, 0.4);
            }
            50% {
              box-shadow: 0 0 0 4px rgba(255, 170, 0, 0);
            }
          }
        `}
      </style>
    </div>
  );
}

export default HeatmapCell;
