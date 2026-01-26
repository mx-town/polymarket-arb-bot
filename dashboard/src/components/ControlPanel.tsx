import { useState } from 'react';
import { restartBot, refreshMarkets } from '../api/client';

interface Props {
  running: boolean;
  pid: number | null;
  uptimeSec: number;
  onRefresh?: () => void;
}

export function ControlPanel({ running, pid, uptimeSec, onRefresh }: Props) {
  const [loading, setLoading] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  const handleRestart = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const result = await restartBot();
      setMessage({ text: result.message, type: 'success' });
      // Trigger refresh after restart
      setTimeout(() => onRefresh?.(), 2000);
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : 'Failed to restart', type: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const handleRefreshMarkets = async () => {
    setRefreshing(true);
    setMessage(null);
    try {
      const result = await refreshMarkets();
      setMessage({ text: result.message, type: 'success' });
      // Trigger data refresh
      setTimeout(() => onRefresh?.(), 1000);
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : 'Failed to refresh markets', type: 'error' });
    } finally {
      setRefreshing(false);
    }
  };

  const formatUptime = (seconds: number) => {
    if (!seconds) return '\u2014';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
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
        <span style={{ fontSize: '1rem' }}>\u2318</span>
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

        {/* Refresh Markets Button */}
        <button
          onClick={handleRefreshMarkets}
          disabled={refreshing || !running}
          style={{
            width: '100%',
            background: running
              ? 'linear-gradient(135deg, var(--accent-blue) 0%, #2266aa 100%)'
              : 'var(--border)',
            color: running ? 'white' : 'var(--text-muted)',
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
            marginBottom: '0.5rem',
          }}
        >
          {refreshing ? (
            <>
              <span className="animate-pulse">\u25CF</span>
              Refreshing...
            </>
          ) : (
            <>
              <span>\u21BB</span>
              Refresh Markets
            </>
          )}
        </button>

        {/* Restart Button */}
        <button
          onClick={handleRestart}
          disabled={loading || !running}
          style={{
            width: '100%',
            background: running
              ? 'linear-gradient(135deg, var(--accent-red) 0%, #cc3344 100%)'
              : 'var(--border)',
            color: running ? 'white' : 'var(--text-muted)',
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
          }}
        >
          {loading ? (
            <>
              <span className="animate-pulse">\u25CF</span>
              Restarting...
            </>
          ) : (
            <>
              <span>\u21BB</span>
              Restart Bot
            </>
          )}
        </button>
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
