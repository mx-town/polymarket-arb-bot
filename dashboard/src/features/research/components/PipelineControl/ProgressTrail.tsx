/**
 * ProgressTrail — inline step indicator for pipeline progress.
 *
 * Shows completed (green check), active (spinner), and pending (dimmed) stages.
 */

import type { PipelineProgressEvent } from '../../types/research.types';

interface ProgressTrailProps {
  progress: PipelineProgressEvent[];
  command: string;
}

/** Ordered stages per command for display purposes */
const COMMAND_STAGES: Record<string, string[]> = {
  init: ['DOWNLOAD', 'EXTRACT', 'MODEL'],
  rebuild: ['EXTRACT', 'MODEL'],
  observe: ['CAPTURE'],
  verify: ['VERIFY'],
  analyse: ['ANALYSE'],
};

function getStageStatus(
  stageName: string,
  progress: PipelineProgressEvent[]
): 'completed' | 'active' | 'pending' {
  const hasComplete = progress.some(
    (p) => p.stage === `${stageName}_COMPLETE` || p.stage === `${stageName}_COMPLETE`
  );
  if (hasComplete) return 'completed';

  const hasStart = progress.some((p) => p.stage === `${stageName}_START` || p.stage === stageName);
  if (hasStart) return 'active';

  return 'pending';
}

export function ProgressTrail({ progress, command }: ProgressTrailProps) {
  const stages = COMMAND_STAGES[command] || [];

  if (stages.length === 0) {
    // Just show the latest progress event
    const latest = progress[progress.length - 1];
    if (!latest) return null;
    return (
      <span
        style={{
          fontSize: '0.625rem',
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-secondary)',
        }}
      >
        {latest.message}
      </span>
    );
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
      {stages.map((stage, i) => {
        const status = getStageStatus(stage, progress);
        return (
          <div key={stage} style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            {i > 0 && (
              <span
                style={{
                  width: '8px',
                  height: '1px',
                  background: status === 'pending' ? 'var(--text-muted)' : 'var(--accent-green)',
                  opacity: status === 'pending' ? 0.3 : 0.6,
                }}
              />
            )}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.25rem',
              }}
            >
              {/* Status indicator */}
              {status === 'completed' && (
                <span
                  style={{
                    color: 'var(--accent-green)',
                    fontSize: '0.6875rem',
                    lineHeight: 1,
                  }}
                >
                  &#x2713;
                </span>
              )}
              {status === 'active' && (
                <span
                  style={{
                    display: 'inline-block',
                    width: '8px',
                    height: '8px',
                    borderRadius: '50%',
                    border: '1.5px solid var(--accent-blue)',
                    borderTopColor: 'transparent',
                    animation: 'spin 0.8s linear infinite',
                  }}
                />
              )}
              {status === 'pending' && (
                <span
                  style={{
                    display: 'inline-block',
                    width: '6px',
                    height: '6px',
                    borderRadius: '50%',
                    background: 'var(--text-muted)',
                    opacity: 0.3,
                  }}
                />
              )}
              {/* Label */}
              <span
                style={{
                  fontSize: '0.5625rem',
                  fontFamily: 'var(--font-mono)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.03em',
                  color:
                    status === 'completed'
                      ? 'var(--accent-green)'
                      : status === 'active'
                        ? 'var(--text-primary)'
                        : 'var(--text-muted)',
                  opacity: status === 'pending' ? 0.5 : 1,
                  fontWeight: status === 'active' ? 600 : 400,
                }}
              >
                {stage.replace(/_/g, ' ')}
              </span>
            </div>
          </div>
        );
      })}
      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  );
}
