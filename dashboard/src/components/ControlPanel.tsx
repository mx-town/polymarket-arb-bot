import { useEffect, useState } from 'react';
import type { BotStatus } from '../api/client';
import { getStatus, restartBot } from '../api/client';

export function ControlPanel() {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<{ text: string; type: 'success' | 'error' } | null>(null);

  const fetchStatus = async () => {
    try {
      const data = await getStatus();
      setStatus(data);
    } catch (e) {
      console.error('Failed to fetch status:', e);
    }
  };

  useEffect(() => {
    fetchStatus();
    const interval = setInterval(fetchStatus, 5000);
    return () => clearInterval(interval);
  }, []);

  const handleRestart = async () => {
    setLoading(true);
    setMessage(null);
    try {
      const result = await restartBot();
      setMessage({ text: result.message, type: 'success' });
      setTimeout(fetchStatus, 2000);
    } catch (e) {
      setMessage({ text: e instanceof Error ? e.message : 'Failed to restart', type: 'error' });
    } finally {
      setLoading(false);
    }
  };

  const formatUptime = (seconds?: number) => {
    if (!seconds) return '—';
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
        <span style={{ fontSize: '1rem' }}>⌘</span>
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
              background: status?.running ? 'var(--accent-green)' : 'var(--accent-red)',
              boxShadow: status?.running
                ? '0 0 12px var(--accent-green), 0 0 4px var(--accent-green)'
                : '0 0 12px var(--accent-red)',
              animation: status?.running ? 'pulse 2s ease-in-out infinite' : undefined,
            }}
          />
          <div>
            <div
              style={{
                fontFamily: 'var(--font-mono)',
                fontSize: '0.875rem',
                fontWeight: 600,
                color: status?.running ? 'var(--accent-green)' : 'var(--accent-red)',
              }}
            >
              {status?.running ? 'RUNNING' : 'STOPPED'}
            </div>
            {status?.pid && (
              <div
                style={{
                  fontSize: '0.6875rem',
                  color: 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                }}
              >
                PID {status.pid}
              </div>
            )}
          </div>
          {status?.uptime_sec && (
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
                {formatUptime(status.uptime_sec)}
              </div>
            </div>
          )}
        </div>

        {/* Restart Button */}
        <button
          onClick={handleRestart}
          disabled={loading || !status?.running}
          style={{
            width: '100%',
            background: status?.running
              ? 'linear-gradient(135deg, var(--accent-red) 0%, #cc3344 100%)'
              : 'var(--border)',
            color: status?.running ? 'white' : 'var(--text-muted)',
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
              <span className="animate-pulse">●</span>
              Restarting...
            </>
          ) : (
            <>
              <span>↻</span>
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
