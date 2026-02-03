import { useState, useMemo, useCallback } from 'react';
import type { ProbabilityBucket, ProbabilitySurface as ProbabilitySurfaceType } from '../../types/research.types';
import { HeatmapCell } from './HeatmapCell';
import { SurfaceControls, type VolatilityFilter, type SessionFilter, type ZoomLevel } from './SurfaceControls';

/** Number of deviation buckets (columns) */
const DEVIATION_BUCKETS = 80;
/** Number of time buckets (rows) - 1-15 minutes */
const TIME_BUCKETS = 15;

/** Deviation range in percentage */
const DEVIATION_RANGE_WIDE = 2.0; // ±2%
const DEVIATION_RANGE_NARROW = 0.5; // ±0.5%

export interface CurrentPosition {
  /** Current price deviation percentage */
  deviation: number;
  /** Time remaining in minutes */
  timeRemainingMin: number;
}

export interface ProbabilitySurfaceProps {
  /** Probability surface data */
  surface: ProbabilitySurfaceType | null;
  /** Current market position to highlight */
  currentPosition?: CurrentPosition;
  /** Callback when a cell is clicked */
  onCellClick?: (bucket: ProbabilityBucket) => void;
  /** Title for the surface */
  title?: string;
}

/**
 * Find bucket for given deviation and time
 */
function findBucket(
  buckets: ProbabilityBucket[],
  deviation: number,
  timeRemainingMin: number,
  volatilityFilter: VolatilityFilter,
  sessionFilter: SessionFilter
): ProbabilityBucket | null {
  // Convert time to seconds for comparison
  const timeRemainingSec = timeRemainingMin * 60;

  return buckets.find((bucket) => {
    const matchesDeviation =
      deviation >= bucket.deviation_min && deviation < bucket.deviation_max;
    const matchesTime =
      timeRemainingSec >= bucket.time_remaining - 30 &&
      timeRemainingSec < bucket.time_remaining + 30;
    const matchesVolatility =
      volatilityFilter === 'all' || bucket.vol_regime === volatilityFilter;
    const matchesSession =
      sessionFilter === 'all' || bucket.session === sessionFilter;

    return matchesDeviation && matchesTime && matchesVolatility && matchesSession;
  }) || null;
}

/**
 * Generate grid data for the surface
 */
function generateGridData(
  buckets: ProbabilityBucket[],
  zoomLevel: ZoomLevel,
  volatilityFilter: VolatilityFilter,
  sessionFilter: SessionFilter
): (ProbabilityBucket | null)[][] {
  const deviationRange = zoomLevel === 'narrow' ? DEVIATION_RANGE_NARROW : DEVIATION_RANGE_WIDE;
  const deviationStep = (deviationRange * 2) / DEVIATION_BUCKETS;

  const grid: (ProbabilityBucket | null)[][] = [];

  // Time buckets are rows (1-15 minutes, with 15 at top, 1 at bottom)
  for (let timeIdx = TIME_BUCKETS - 1; timeIdx >= 0; timeIdx--) {
    const row: (ProbabilityBucket | null)[] = [];
    const timeRemainingMin = timeIdx + 1;

    // Deviation buckets are columns (-range to +range)
    for (let devIdx = 0; devIdx < DEVIATION_BUCKETS; devIdx++) {
      const deviation = -deviationRange + devIdx * deviationStep;
      const bucket = findBucket(
        buckets,
        deviation,
        timeRemainingMin,
        volatilityFilter,
        sessionFilter
      );
      row.push(bucket);
    }

    grid.push(row);
  }

  return grid;
}

/**
 * Main probability surface component
 * Displays an 80x15 heatmap of win probabilities
 */
export function ProbabilitySurface({
  surface,
  currentPosition,
  onCellClick,
  title = 'Probability Surface',
}: ProbabilitySurfaceProps) {
  const [volatilityFilter, setVolatilityFilter] = useState<VolatilityFilter>('all');
  const [sessionFilter, setSessionFilter] = useState<SessionFilter>('all');
  const [zoomLevel, setZoomLevel] = useState<ZoomLevel>('wide');
  const [selectedCell, setSelectedCell] = useState<{ row: number; col: number } | null>(null);

  const deviationRange = zoomLevel === 'narrow' ? DEVIATION_RANGE_NARROW : DEVIATION_RANGE_WIDE;
  const deviationStep = (deviationRange * 2) / DEVIATION_BUCKETS;

  // Generate grid data
  const buckets = surface?.buckets;
  const gridData = useMemo(() => {
    if (!buckets) return [];
    return generateGridData(buckets, zoomLevel, volatilityFilter, sessionFilter);
  }, [buckets, zoomLevel, volatilityFilter, sessionFilter]);

  // Calculate current position cell
  const currentPositionCell = useMemo(() => {
    if (!currentPosition) return null;
    const { deviation, timeRemainingMin } = currentPosition;

    // Check if within visible range
    if (Math.abs(deviation) > deviationRange || timeRemainingMin < 1 || timeRemainingMin > 15) {
      return null;
    }

    // Calculate column index
    const col = Math.floor((deviation + deviationRange) / deviationStep);
    // Calculate row index (15min at top = row 0, 1min at bottom = row 14)
    const row = TIME_BUCKETS - timeRemainingMin;

    return { row, col };
  }, [currentPosition, deviationRange, deviationStep]);

  const handleCellClick = useCallback(
    (rowIdx: number, colIdx: number, bucket: ProbabilityBucket | null) => {
      setSelectedCell({ row: rowIdx, col: colIdx });
      if (bucket && onCellClick) {
        onCellClick(bucket);
      }
    },
    [onCellClick]
  );

  // Generate axis labels
  const xAxisLabels = useMemo(() => {
    const labels: { value: string; position: number }[] = [];
    const numLabels = 9; // -2%, -1.5%, -1%, -0.5%, 0%, 0.5%, 1%, 1.5%, 2%
    const step = DEVIATION_BUCKETS / (numLabels - 1);

    for (let i = 0; i < numLabels; i++) {
      const deviation = -deviationRange + (i / (numLabels - 1)) * deviationRange * 2;
      labels.push({
        value: `${deviation >= 0 ? '+' : ''}${deviation.toFixed(1)}%`,
        position: i * step,
      });
    }
    return labels;
  }, [deviationRange]);

  const yAxisLabels = useMemo(() => {
    // Show labels for 1, 5, 10, 15 minutes
    return [
      { value: '15m', row: 0 },
      { value: '10m', row: 5 },
      { value: '5m', row: 10 },
      { value: '1m', row: 14 },
    ];
  }, []);

  if (!surface) {
    return (
      <div
        style={{
          background: 'var(--bg-card)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border)',
          padding: '1.5rem',
        }}
      >
        <div
          style={{
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.75rem',
          }}
        >
          No probability surface data available
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
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          background: 'var(--bg-elevated)',
          flexWrap: 'wrap',
          gap: '0.75rem',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div
            style={{
              width: '16px',
              height: '16px',
              borderRadius: '4px',
              background: 'linear-gradient(135deg, var(--accent-red) 0%, var(--accent-green) 100%)',
            }}
          />
          <span
            style={{
              fontSize: '0.75rem',
              fontWeight: 600,
              textTransform: 'uppercase',
              letterSpacing: '0.08em',
              color: 'var(--text-secondary)',
            }}
          >
            {title}
          </span>
          {surface.metadata && (
            <span
              style={{
                fontSize: '0.625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {surface.metadata.total_observations.toLocaleString()} obs |{' '}
              {surface.metadata.reliable_buckets} reliable
            </span>
          )}
        </div>

        <SurfaceControls
          volatilityFilter={volatilityFilter}
          onVolatilityChange={setVolatilityFilter}
          sessionFilter={sessionFilter}
          onSessionChange={setSessionFilter}
          zoomLevel={zoomLevel}
          onZoomChange={setZoomLevel}
        />
      </div>

      {/* Surface Grid */}
      <div style={{ padding: '1rem' }}>
        <div style={{ display: 'flex' }}>
          {/* Y-axis labels */}
          <div
            style={{
              width: '32px',
              display: 'flex',
              flexDirection: 'column',
              justifyContent: 'space-between',
              paddingRight: '8px',
              height: `${TIME_BUCKETS * 20}px`,
            }}
          >
            {yAxisLabels.map((label) => (
              <div
                key={label.value}
                style={{
                  position: 'absolute',
                  top: `${(label.row / TIME_BUCKETS) * 100}%`,
                  transform: 'translateY(-50%)',
                  fontSize: '0.5625rem',
                  fontFamily: 'var(--font-mono)',
                  color: 'var(--text-muted)',
                  textAlign: 'right',
                  width: '24px',
                }}
              >
                {label.value}
              </div>
            ))}
          </div>

          {/* Main grid container */}
          <div style={{ flex: 1, position: 'relative' }}>
            {/* Y-axis label column */}
            <div
              style={{
                position: 'absolute',
                left: '-32px',
                top: 0,
                bottom: 0,
                width: '32px',
                display: 'flex',
                flexDirection: 'column',
              }}
            >
              {yAxisLabels.map((label) => (
                <div
                  key={label.value}
                  style={{
                    position: 'absolute',
                    top: `${(label.row / TIME_BUCKETS) * 100}%`,
                    right: '8px',
                    transform: 'translateY(-50%)',
                    fontSize: '0.5625rem',
                    fontFamily: 'var(--font-mono)',
                    color: 'var(--text-muted)',
                  }}
                >
                  {label.value}
                </div>
              ))}
            </div>

            {/* Grid */}
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: `repeat(${DEVIATION_BUCKETS}, 1fr)`,
                gridTemplateRows: `repeat(${TIME_BUCKETS}, 20px)`,
                gap: '1px',
                background: 'var(--border-subtle)',
                borderRadius: 'var(--radius-sm)',
                overflow: 'hidden',
              }}
            >
              {gridData.map((row, rowIdx) =>
                row.map((bucket, colIdx) => {
                  const isCurrentPosition =
                    currentPositionCell?.row === rowIdx && currentPositionCell?.col === colIdx;
                  const isSelected =
                    selectedCell?.row === rowIdx && selectedCell?.col === colIdx;

                  const deviation = -deviationRange + colIdx * deviationStep;
                  const timeRemainingMin = TIME_BUCKETS - rowIdx;

                  return (
                    <div
                      key={`${rowIdx}-${colIdx}`}
                      style={{
                        position: 'relative',
                      }}
                    >
                      <HeatmapCell
                        probability={bucket?.win_rate ?? 0.5}
                        sampleSize={bucket?.sample_size ?? 0}
                        isReliable={bucket?.is_reliable ?? false}
                        ciLower={bucket?.ci_lower ?? 0}
                        ciUpper={bucket?.ci_upper ?? 1}
                        isSelected={isSelected || isCurrentPosition}
                        onClick={() => handleCellClick(rowIdx, colIdx, bucket)}
                        deviationLabel={`Dev: ${deviation >= 0 ? '+' : ''}${deviation.toFixed(2)}%`}
                        timeLabel={`Time: ${timeRemainingMin}m`}
                      />
                      {/* Current position marker */}
                      {isCurrentPosition && (
                        <div
                          style={{
                            position: 'absolute',
                            inset: 0,
                            border: '2px solid var(--accent-amber)',
                            borderRadius: '2px',
                            pointerEvents: 'none',
                            zIndex: 20,
                          }}
                        >
                          <div
                            style={{
                              position: 'absolute',
                              top: '-6px',
                              left: '50%',
                              transform: 'translateX(-50%)',
                              width: '8px',
                              height: '8px',
                              background: 'var(--accent-amber)',
                              borderRadius: '50%',
                              border: '2px solid var(--bg-card)',
                            }}
                          />
                        </div>
                      )}
                    </div>
                  );
                })
              )}
            </div>

            {/* X-axis labels */}
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                marginTop: '8px',
                paddingLeft: '0',
                paddingRight: '0',
              }}
            >
              {xAxisLabels.map((label, idx) => (
                <div
                  key={idx}
                  style={{
                    fontSize: '0.5625rem',
                    fontFamily: 'var(--font-mono)',
                    color: label.value === '+0.0%' ? 'var(--text-secondary)' : 'var(--text-muted)',
                    fontWeight: label.value === '+0.0%' ? 600 : 400,
                  }}
                >
                  {label.value}
                </div>
              ))}
            </div>

            {/* Axis label */}
            <div
              style={{
                textAlign: 'center',
                marginTop: '4px',
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.1em',
              }}
            >
              Price Deviation
            </div>
          </div>
        </div>

        {/* Legend */}
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            gap: '1.5rem',
            marginTop: '1rem',
            paddingTop: '0.75rem',
            borderTop: '1px solid var(--border-subtle)',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <div
              style={{
                width: '12px',
                height: '12px',
                borderRadius: '2px',
                background: 'rgba(255, 71, 87, 0.8)',
              }}
            />
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              P &lt; 0.3
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <div
              style={{
                width: '12px',
                height: '12px',
                borderRadius: '2px',
                background: 'rgba(136, 136, 160, 0.5)',
              }}
            />
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              P ~ 0.5
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <div
              style={{
                width: '12px',
                height: '12px',
                borderRadius: '2px',
                background: 'rgba(0, 212, 170, 0.8)',
              }}
            />
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              P &gt; 0.7
            </span>
          </div>
          {currentPosition && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <div
                style={{
                  width: '12px',
                  height: '12px',
                  borderRadius: '2px',
                  border: '2px solid var(--accent-amber)',
                  position: 'relative',
                }}
              >
                <div
                  style={{
                    position: 'absolute',
                    top: '-4px',
                    left: '50%',
                    transform: 'translateX(-50%)',
                    width: '6px',
                    height: '6px',
                    background: 'var(--accent-amber)',
                    borderRadius: '50%',
                  }}
                />
              </div>
              <span
                style={{
                  fontSize: '0.5625rem',
                  color: 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                }}
              >
                Current Position
              </span>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default ProbabilitySurface;
