/**
 * PipelineStatusBar — compact horizontal strip for pipeline control.
 *
 * Three states:
 * - Idle + model exists: READY | Model age | Data stats | action buttons
 * - Setup required: SETUP REQUIRED | init prompt with months selector
 * - Running: command name + elapsed time | ProgressTrail | Cancel button
 */

import { useState, useEffect, useRef } from 'react';
import { usePipelineStatus } from '../../hooks/usePipelineStatus';
import { ProgressTrail } from './ProgressTrail';

interface PipelineStatusBarProps {
  onPipelineComplete?: () => void;
}

function formatElapsed(seconds: number): string {
  const m = Math.floor(seconds / 60);
  const s = Math.floor(seconds % 60);
  return `${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
}

export function PipelineStatusBar({ onPipelineComplete }: PipelineStatusBarProps) {
  const { status, currentJob, startCommand, stopCommand, isStarting, error } = usePipelineStatus();
  const [months, setMonths] = useState(6);
  const [elapsed, setElapsed] = useState(0);
  const prevJobRef = useRef(currentJob?.status);

  // Track elapsed time when running
  const jobStatus = currentJob?.status;
  const jobStartedAt = currentJob?.started_at;
  const isJobRunning = jobStatus === 'running' && !!jobStartedAt;

  // Reset elapsed when job stops (derived state, no effect needed)
  const computedElapsed = isJobRunning ? elapsed : 0;

  useEffect(() => {
    if (!isJobRunning || !jobStartedAt) {
      return;
    }

    const startedAt = new Date(jobStartedAt).getTime();
    const tick = () => setElapsed((Date.now() - startedAt) / 1000);
    tick();
    const interval = setInterval(tick, 1000);
    return () => clearInterval(interval);
  }, [isJobRunning, jobStartedAt]);

  // Fire onPipelineComplete when job transitions to completed/failed
  useEffect(() => {
    const prevStatus = prevJobRef.current;
    prevJobRef.current = jobStatus;

    if (
      prevStatus === 'running' &&
      (jobStatus === 'completed' || jobStatus === 'failed' || jobStatus === 'cancelled')
    ) {
      onPipelineComplete?.();
    }
  }, [jobStatus, onPipelineComplete]);

  if (!status) {
    return null; // Still loading
  }

  const isRunning = currentJob?.status === 'running';

  // Determine accent color
  const accentColor = isRunning
    ? 'var(--accent-blue)'
    : status.has_model
      ? 'var(--accent-green)'
      : 'var(--accent-amber)';

  // Status dot style
  const dotStyle: React.CSSProperties = {
    width: '8px',
    height: '8px',
    borderRadius: '50%',
    background: accentColor,
    flexShrink: 0,
    ...(isRunning && {
      animation: 'pulse 1.5s ease-in-out infinite',
    }),
  };

  const buttonStyle: React.CSSProperties = {
    height: '24px',
    padding: '0 0.5rem',
    fontSize: '0.625rem',
    fontFamily: 'var(--font-mono)',
    fontWeight: 500,
    textTransform: 'uppercase' as const,
    letterSpacing: '0.04em',
    border: '1px solid var(--border)',
    borderRadius: '4px',
    background: 'transparent',
    color: 'var(--text-secondary)',
    cursor: 'pointer',
    whiteSpace: 'nowrap' as const,
    transition: 'all 0.15s ease',
  };

  const separatorStyle: React.CSSProperties = {
    width: '1px',
    height: '24px',
    background: 'var(--border)',
  };

  const labelStyle: React.CSSProperties = {
    fontSize: '0.5625rem',
    fontFamily: 'var(--font-mono)',
    textTransform: 'uppercase' as const,
    letterSpacing: '0.04em',
    color: 'var(--text-muted)',
  };

  const valueStyle: React.CSSProperties = {
    fontSize: '0.8125rem',
    fontFamily: 'var(--font-mono)',
    fontWeight: 600,
    color: 'var(--text-primary)',
  };

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
        borderLeft: `3px solid ${accentColor}`,
        padding: '0.5rem 1rem',
        marginBottom: '1rem',
        display: 'flex',
        alignItems: 'center',
        gap: '1rem',
        minHeight: '40px',
      }}
    >
      {/* Status dot */}
      <div style={dotStyle} />

      {/* ============ Running State ============ */}
      {isRunning && currentJob && (
        <>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>
            <span style={labelStyle}>{currentJob.command.toUpperCase()} RUNNING</span>
            <span style={valueStyle}>{formatElapsed(computedElapsed)}</span>
          </div>

          <div style={separatorStyle} />

          <ProgressTrail progress={currentJob.progress} command={currentJob.command} />

          <div style={{ marginLeft: 'auto' }}>
            <button
              style={{
                ...buttonStyle,
                borderColor: 'var(--accent-red)',
                color: 'var(--accent-red)',
              }}
              onClick={stopCommand}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(255, 71, 87, 0.1)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent';
              }}
            >
              Cancel
            </button>
          </div>
        </>
      )}

      {/* ============ Setup Required State ============ */}
      {!isRunning && !status.has_model && (
        <>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>
            <span style={{ ...labelStyle, color: 'var(--accent-amber)' }}>SETUP REQUIRED</span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-secondary)' }}>
              No probability model found
            </span>
          </div>

          <div style={separatorStyle} />

          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem', marginLeft: 'auto' }}>
            <span style={labelStyle}>Months:</span>
            <select
              value={months}
              onChange={(e) => setMonths(Number(e.target.value))}
              style={{
                height: '24px',
                padding: '0 0.25rem',
                fontSize: '0.6875rem',
                fontFamily: 'var(--font-mono)',
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border)',
                borderRadius: '4px',
                color: 'var(--text-primary)',
                cursor: 'pointer',
              }}
            >
              {[1, 3, 6, 12].map((m) => (
                <option key={m} value={m}>
                  {m}
                </option>
              ))}
            </select>
            <button
              style={{
                ...buttonStyle,
                borderColor: 'var(--accent-green)',
                color: 'var(--accent-green)',
              }}
              onClick={() => startCommand('init', { months })}
              disabled={isStarting}
              onMouseEnter={(e) => {
                e.currentTarget.style.background = 'rgba(0, 212, 170, 0.1)';
              }}
              onMouseLeave={(e) => {
                e.currentTarget.style.background = 'transparent';
              }}
            >
              {isStarting ? 'Starting...' : 'Initialize Pipeline'}
            </button>
          </div>
        </>
      )}

      {/* ============ Ready State ============ */}
      {!isRunning && status.has_model && (
        <>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>
            <span style={{ ...labelStyle, color: 'var(--accent-green)' }}>READY</span>
          </div>

          <div style={separatorStyle} />

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>
            <span style={labelStyle}>Model</span>
            <span style={valueStyle}>
              {status.model_age_hours != null ? `${status.model_age_hours}h ago` : '--'}
            </span>
          </div>

          <div style={separatorStyle} />

          <div style={{ display: 'flex', flexDirection: 'column', gap: '0.125rem' }}>
            <span style={labelStyle}>Observations</span>
            <span style={valueStyle}>
              {status.observation_files} files ({status.observation_size_mb} MB)
            </span>
          </div>

          <div
            style={{ display: 'flex', alignItems: 'center', gap: '0.375rem', marginLeft: 'auto' }}
          >
            {['init', 'rebuild', 'verify', 'analyse'].map((cmd) => (
              <button
                key={cmd}
                style={buttonStyle}
                onClick={() => startCommand(cmd, cmd === 'init' ? { months } : {})}
                disabled={isStarting}
                onMouseEnter={(e) => {
                  e.currentTarget.style.background = 'var(--bg-elevated)';
                }}
                onMouseLeave={(e) => {
                  e.currentTarget.style.background = 'transparent';
                }}
              >
                {cmd}
              </button>
            ))}
          </div>
        </>
      )}

      {/* Error display */}
      {error && (
        <span
          style={{
            fontSize: '0.625rem',
            color: 'var(--accent-red)',
            fontFamily: 'var(--font-mono)',
            marginLeft: '0.5rem',
          }}
        >
          {error}
        </span>
      )}

      <style>
        {`
          @keyframes pulse {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.4; }
          }
        `}
      </style>
    </div>
  );
}
