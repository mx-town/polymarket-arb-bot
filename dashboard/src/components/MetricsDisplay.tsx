import type { BotMetrics } from '../api/client';

interface Props {
  metrics: BotMetrics | null;
  connected: boolean;
}

function MetricCard({ label, value, suffix = '' }: { label: string; value: string | number; suffix?: string }) {
  return (
    <div style={{
      background: '#1a1a2e',
      padding: '1rem',
      borderRadius: '8px',
      minWidth: '140px',
    }}>
      <div style={{ fontSize: '0.8rem', color: '#888', marginBottom: '0.25rem' }}>{label}</div>
      <div style={{ fontSize: '1.5rem', fontWeight: 'bold' }}>
        {value}{suffix}
      </div>
    </div>
  );
}

export function MetricsDisplay({ metrics, connected }: Props) {
  if (!metrics) {
    return (
      <div style={{ padding: '1rem', background: '#1a1a2e', borderRadius: '8px' }}>
        <p>Loading metrics...</p>
      </div>
    );
  }

  if (metrics.error) {
    return (
      <div style={{ padding: '1rem', background: '#1a1a2e', borderRadius: '8px' }}>
        <p style={{ color: '#ff6b6b' }}>Bot not running. Start the bot to see metrics.</p>
      </div>
    );
  }

  const formatUptime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    return `${h}h ${m}m ${s}s`;
  };

  const formatPnl = (pnl: number) => {
    const formatted = pnl.toFixed(4);
    return pnl >= 0 ? `+$${formatted}` : `-$${Math.abs(pnl).toFixed(4)}`;
  };

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', marginBottom: '1rem', gap: '0.5rem' }}>
        <h2 style={{ margin: 0 }}>Live Metrics</h2>
        <span style={{
          width: '10px',
          height: '10px',
          borderRadius: '50%',
          background: connected ? '#4ecdc4' : '#ff6b6b',
        }} />
        <span style={{ fontSize: '0.8rem', color: '#888' }}>
          {connected ? 'Connected' : 'Disconnected'}
        </span>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '1rem' }}>
        <MetricCard label="Uptime" value={formatUptime(metrics.uptime_sec)} />
        <MetricCard label="Markets Scanned" value={metrics.markets_scanned} />
        <MetricCard label="Opportunities" value={`${metrics.opportunities_taken}/${metrics.opportunities_seen}`} />
        <MetricCard label="Trades Filled" value={metrics.trades_filled} />
        <MetricCard label="Trades Failed" value={metrics.trades_failed} />
        <MetricCard
          label="Total P&L"
          value={formatPnl(metrics.total_pnl)}
        />
        <MetricCard
          label="Daily P&L"
          value={formatPnl(metrics.daily_pnl)}
        />
        <MetricCard label="WS Latency" value={metrics.avg_latency_ms.toFixed(1)} suffix="ms" />
        <MetricCard label="WS Reconnects" value={metrics.ws_reconnects} />
        <MetricCard label="Consecutive Losses" value={metrics.consecutive_losses} />
      </div>
    </div>
  );
}
