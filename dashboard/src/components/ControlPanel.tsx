import { useState } from 'react';
import { startBot, stopBot, restartTradingBot } from '../api/client';

interface Props {
  running: boolean;
  pid: number | null;
  uptimeSec: number;
  dryRun?: boolean;
  onRefresh?: () => void;
}

export function ControlPanel({ running, pid, uptimeSec, dryRun, onRefresh }: Props) {
  const [starting, setStarting] = useState(false);
  const [stopping, setStopping] = useState(false);
  const [restarting, setRestarting] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  const handleStart = async () => {
    setStarting(true);
    setMessage(null);
    try {
      const result = await startBot({ dry_run: dryRun });
      setMessage({ text: `Bot started (${result.status.status})`, type: 'success' });
      setTimeout(() => onRefresh?.(), 2000);
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : 'Failed to start', type: 'error' });
    } finally {
      setStarting(false);
    }
  };

  const handleStop = async () => {
    setStopping(true);
    setMessage(null);
    try {
      const result = await stopBot();
      setMessage({ text: `Bot stopped (${result.status.status})`, type: 'success' });
      setTimeout(() => onRefresh?.(), 2000);
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : 'Failed to stop', type: 'error' });
    } finally {
      setStopping(false);
    }
  };

  const handleRestart = async () => {
    setRestarting(true);
    setMessage(null);
    try {
      const result = await restartTradingBot({ dry_run: dryRun });
      setMessage({ text: `Bot restarted (${result.status.status})`, type: 'success' });
      setTimeout(() => onRefresh?.(), 2000);
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : 'Failed to restart', type: 'error' });
    } finally {
      setRestarting(false);
    }
  };

  const formatUptime = (seconds: number) => {
    if (!seconds) return '\u2014';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  };

  const buttonBase: React.CSSProperties = {
    padding: '0.625rem 1rem',
    borderRadius: 'var(--radius-sm)',
    fontSize: '0.75rem',
    fontWeight: 600,
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    gap: '0.5rem',
    border: 'none',
    cursor: 'pointer',
    width: '100%',
  };

  const disabledStyle: React.CSSProperties = {
    background: 'var(--border)',
    color: 'var(--text-muted)',
    cursor: 'not-allowed',
  };

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
          gap: '0.5rem',
          background: 'var(--bg-elevated)',
        }}
      >
        <span style={{ fontSize: '1rem' }}>{'\u2318'}</span>
        <span
          style={{
            fontSize: '0.75rem',
            fontWeight: 600,
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--text-secondary)',
          }}
        >
          Control
        </span>
      </div>

      {/* Status Display */}
      <div style={{ padding: '1rem' }}>
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            gap: '0.75rem',
            marginBottom: '1rem',
          }}
        >
          <div
            style={{
              width: '12px',
              height: '12px',
              borderRadius: '50%',
              background: running ? 'var(--accent-green)' : 'var(--accent-red)',
              boxShadow: running
                ? '0 0 12px var(--accent-green), 0 0 4px var(--accent-green)'
                : '0 0 12px var(--accent-red)',
              animation: running ? 'pulse 2s ease-in-out infinite' : undefined,
            }}
          />
          <div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.875rem',
                fontWeight: 600,
                color: running ? 'var(--accent-green)' : 'var(--accent-red)',
              }}
            >
              {running ? 'RUNNING' : 'STOPPED'}
            </div>
            {pid && (
              <div
                style={{
                  fontSize: '0.6875rem',
                  color: 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                }}
              >
                PID {pid}
              </div>
            )}
          </div>
          {uptimeSec > 0 && (
            <div
              style={{
                marginLeft: 'auto',
                textAlign: 'right',
              }}
            >
              <div
                style={{
                  fontSize: '0.6875rem',
                  color: 'var(--text-muted)',
                  textTransform: 'uppercase',
                }}
              >
                Uptime
              </div>
              <div
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.875rem',
                  color: 'var(--text-primary)',
                }}
              >
                {formatUptime(uptimeSec)}
              </div>
            </div>
          )}
        </div>

        {/* Button Grid */}
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 1fr 1fr',
            gap: '0.5rem',
          }}
        >
          {/* Start Button */}
          <button
            onClick={handleStart}
            disabled={starting || running}
            style={{
              ...buttonBase,
              ...(!running && !starting
                ? {
                    background:
                      'linear-gradient(135deg, var(--accent-green) 0%, #22aa44 100%)',
                    color: 'white',
                  }
                : disabledStyle),
            }}
          >
            {starting ? (
              <>
                <span className="animate-pulse">{'\u25CF'}</span>
                Starting...
              </>
            ) : (
              <>
                <span>{'\u25B6'}</span>
                Start
              </>
            )}
          </button>

          {/* Restart Button */}
          <button
            onClick={handleRestart}
            disabled={restarting || !running}
            style={{
              ...buttonBase,
              ...(running && !restarting
                ? {
                    background:
                      'linear-gradient(135deg, var(--accent-amber) 0%, #cc8833 100%)',
                    color: 'white',
                  }
                : disabledStyle),
            }}
          >
            {restarting ? (
              <>
                <span className="animate-pulse">{'\u25CF'}</span>
                Restarting...
              </>
            ) : (
              <>
                <span>{'\u21BB'}</span>
                Restart
              </>
            )}
          </button>

          {/* Stop Button */}
          <button
            onClick={handleStop}
            disabled={stopping || !running}
            style={{
              ...buttonBase,
              ...(running && !stopping
                ? {
                    background:
                      'linear-gradient(135deg, var(--accent-red) 0%, #cc3344 100%)',
                    color: 'white',
                  }
                : disabledStyle),
            }}
          >
            {stopping ? (
              <>
                <span className="animate-pulse">{'\u25CF'}</span>
                Stopping...
              </>
            ) : (
              <>
                <span>{'\u25A0'}</span>
                Stop
              </>
            )}
          </button>
        </div>
      </div>

      {/* Message */}
      {message && (
        <div
          style={{
            padding: '0.75rem 1rem',
            background:
              message.type === 'success' ? 'var(--accent-green-dim)' : 'var(--accent-red-dim)',
            color: message.type === 'success' ? 'var(--accent-green)' : 'var(--accent-red)',
            fontSize: '0.75rem',
            borderTop: '1px solid var(--border)',
          }}
        >
          {message.text}
        </div>
      )}
    </div>
  );
}
