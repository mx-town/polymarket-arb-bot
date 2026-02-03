import { cn } from '@/lib/utils';

interface EnrichmentStatus {
  modelLoaded: boolean;
  modelVersion?: string;
  candleInterval?: string;
  isTrackingCandles: boolean;
  signalDetectionActive: boolean;
  signalsDetectedCount: number;
}

interface Props {
  status: EnrichmentStatus;
}

/**
 * Status badges for enrichment features
 * Shows: Model status, Candle tracking, Signal detection
 */
export function EnrichmentBadges({ status }: Props) {
  return (
    <div
      style={{
        display: 'flex',
        flexWrap: 'wrap',
        gap: '0.5rem',
        alignItems: 'center',
      }}
    >
      {/* Model Status Badge */}
      <StatusBadge
        active={status.modelLoaded}
        activeLabel={`Model ${status.modelVersion || 'Loaded'}`}
        inactiveLabel="No Model"
        activeColor="var(--color-accent-green)"
        icon={status.modelLoaded ? '🧠' : undefined}
      />

      {/* Candle Tracking Badge */}
      <StatusBadge
        active={status.isTrackingCandles}
        activeLabel={`Tracking ${status.candleInterval || '1H'}`}
        inactiveLabel="Not Tracking"
        activeColor="var(--color-accent-blue)"
        icon={status.isTrackingCandles ? '📊' : undefined}
      />

      {/* Signal Detection Badge */}
      <StatusBadge
        active={status.signalDetectionActive}
        activeLabel={`Active (${status.signalsDetectedCount})`}
        inactiveLabel="Inactive"
        activeColor="var(--color-accent-amber)"
        icon={status.signalDetectionActive ? '⚡' : undefined}
      />
    </div>
  );
}

interface StatusBadgeProps {
  active: boolean;
  activeLabel: string;
  inactiveLabel: string;
  activeColor: string;
  icon?: string;
}

function StatusBadge({ active, activeLabel, inactiveLabel, activeColor, icon }: StatusBadgeProps) {
  return (
    <div
      className={cn(
        'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 text-xs font-medium transition-colors'
      )}
      style={{
        background: active ? `${activeColor}20` : 'var(--color-bg-elevated)',
        border: `1px solid ${active ? activeColor : 'var(--color-border-main)'}`,
        color: active ? activeColor : 'var(--color-text-muted)',
      }}
    >
      {icon && <span style={{ fontSize: '0.625rem' }}>{icon}</span>}
      <span style={{ fontSize: '0.6875rem', fontWeight: 500 }}>
        {active ? activeLabel : inactiveLabel}
      </span>
    </div>
  );
}

export type { EnrichmentStatus };
