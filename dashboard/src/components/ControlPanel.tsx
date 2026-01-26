import { useEffect, useState } from 'react';
import type { BotStatus } from '../api/client';
import { getStatus, restartBot } from '../api/client';

export function ControlPanel() {
  const [status, setStatus] = useState<BotStatus | null>(null);
  const [loading, setLoading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

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
    if (!confirm('Are you sure you want to restart the bot?')) return;

    setLoading(true);
    setMessage(null);
    try {
      const result = await restartBot();
      setMessage(result.message);
      setTimeout(fetchStatus, 2000);
    } catch (e) {
      setMessage(e instanceof Error ? e.message : 'Failed to restart');
    } finally {
      setLoading(false);
    }
  };

  const formatUptime = (seconds?: number) => {
    if (!seconds) return 'N/A';
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    return h > 0 ? `${h}h ${m}m` : `${m}m`;
  };

  return (
    <div style={{
      background: '#1a1a2e',
      padding: '1.5rem',
      borderRadius: '8px',
    }}>
      <h2 style={{ margin: '0 0 1rem 0' }}>Bot Control</h2>

      <div style={{ display: 'flex', alignItems: 'center', gap: '1rem', marginBottom: '1rem' }}>
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
        }}>
          <span style={{
            width: '12px',
            height: '12px',
            borderRadius: '50%',
            background: status?.running ? '#4ecdc4' : '#ff6b6b',
          }} />
          <span style={{ fontWeight: 'bold' }}>
            {status?.running ? 'Running' : 'Stopped'}
          </span>
        </div>

        {status?.pid && (
          <span style={{ color: '#888', fontSize: '0.9rem' }}>
            PID: {status.pid}
          </span>
        )}

        {status?.uptime_sec && (
          <span style={{ color: '#888', fontSize: '0.9rem' }}>
            Uptime: {formatUptime(status.uptime_sec)}
          </span>
        )}
      </div>

      <button
        onClick={handleRestart}
        disabled={loading || !status?.running}
        style={{
          background: '#ff6b6b',
          border: 'none',
          color: 'white',
          padding: '0.75rem 1.5rem',
          borderRadius: '4px',
          cursor: loading || !status?.running ? 'not-allowed' : 'pointer',
          opacity: loading || !status?.running ? 0.5 : 1,
          fontWeight: 'bold',
        }}
      >
        {loading ? 'Restarting...' : 'Restart Bot'}
      </button>

      {message && (
        <p style={{
          marginTop: '1rem',
          padding: '0.5rem',
          background: '#16213e',
          borderRadius: '4px',
          fontSize: '0.9rem',
        }}>
          {message}
        </p>
      )}
    </div>
  );
}
