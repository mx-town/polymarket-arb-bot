import type { BotMetrics } from '../api/client';

interface Props {
  metrics: BotMetrics | null;
  connected: boolean;
}

interface StatProps {
  label: string;
  value: string | number;
  mono?: boolean;
  accent?: 'green' | 'red' | 'amber' | 'blue';
  size?: 'sm' | 'md' | 'lg';
}

function Stat({ label, value, mono = true, accent, size = 'md' }: StatProps) {
  const sizeStyles = {
    sm: { value: '1rem', label: '0.6875rem' },
    md: { value: '1.25rem', label: '0.6875rem' },
    lg: { value: '1.75rem', label: '0.75rem' },
  };

  const accentColors = {
    green: 'var(--accent-green)',
    red: 'var(--accent-red)',
    amber: 'var(--accent-amber)',
    blue: 'var(--accent-blue)',
  };

  return (
    <div style={{ minWidth: 0 }}>
      <div
        style={{
          fontSize: sizeStyles[size].label,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.05em',
          marginBottom: '0.25rem',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: sizeStyles[size].value,
          fontFamily: mono ? 'var(--font-mono)' : 'inherit',
          fontWeight: 600,
          color: accent ? accentColors[accent] : 'var(--text-primary)',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}
      >
        {value}
      </div>
    </div>
  );
}

interface CardProps {
  title: string;
  icon: string;
  children: React.ReactNode;
  accent?: string;
}

function MetricCard({ title, icon, children, accent }: CardProps) {
  return (
    <div
      style={{
        background: 'var(--bg-card)',
        borderRadius: 'var(--radius-md)',
        border: '1px solid var(--border)',
        overflow: 'hidden',
      }}
    >
      <div
        style={{
          padding: '0.75rem 1rem',
          borderBottom: '1px solid var(--border)',
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          background: accent
            ? `linear-gradient(135deg, ${accent}08 0%, transparent 60%)`
            : undefined,
        }}
      >
        <span style={{ fontSize: '1rem' }}>{icon}</span>
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
      </div>
      <div style={{ padding: '1rem' }}>{children}</div>
    </div>
  );
}

export function MetricsDisplay({ metrics, connected }: Props) {
  if (!metrics) {
    return (
      <div
        style={{
          background: 'var(--bg-card)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--border)',
          padding: '2rem',
          textAlign: 'center',
          color: 'var(--text-muted)',
        }}
      >
        <div className="animate-pulse">Loading metrics...</div>
      </div>
    );
  }

  if (metrics.error) {
    return (
      <div
        style={{
          background: 'var(--accent-red-dim)',
          borderRadius: 'var(--radius-md)',
          border: '1px solid var(--accent-red)',
          padding: '1.5rem',
          display: 'flex',
          alignItems: 'center',
          gap: '1rem',
        }}
      >
        <span style={{ fontSize: '1.5rem' }}>⏸</span>
        <div>
          <div style={{ fontWeight: 600, marginBottom: '0.25rem' }}>Bot Offline</div>
          <div style={{ fontSize: '0.875rem', color: 'var(--text-secondary)' }}>
            Start the bot to see live metrics
          </div>
        </div>
      </div>
    );
  }

  const formatUptime = (seconds: number) => {
    const h = Math.floor(seconds / 3600);
    const m = Math.floor((seconds % 3600) / 60);
    const s = Math.floor(seconds % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  };

  const formatPnl = (pnl: number) => {
    const abs = Math.abs(pnl);
    if (abs >= 1000) return `${pnl >= 0 ? '+' : '-'}$${(abs / 1000).toFixed(1)}k`;
    if (abs >= 1) return `${pnl >= 0 ? '+' : '-'}$${abs.toFixed(2)}`;
    return `${pnl >= 0 ? '+' : '-'}$${abs.toFixed(4)}`;
  };

  const winRate =
    metrics.trades_filled > 0
      ? (((metrics.trades_filled - metrics.trades_failed) / metrics.trades_filled) * 100).toFixed(0)
      : '0';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
      {/* P&L Hero Card */}
      <div
        style={{
          background: `linear-gradient(135deg, var(--bg-card) 0%, ${metrics.total_pnl >= 0 ? 'var(--accent-green-dim)' : 'var(--accent-red-dim)'} 100%)`,
          borderRadius: 'var(--radius-lg)',
          border: `1px solid ${metrics.total_pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)'}`,
          padding: '1.5rem',
          display: 'grid',
          gridTemplateColumns: '1fr auto',
          gap: '1.5rem',
          alignItems: 'center',
        }}
      >
        <div>
          <div
            style={{
              fontSize: '0.75rem',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              color: 'var(--text-muted)',
              marginBottom: '0.5rem',
            }}
          >
            Total P&L
          </div>
          <div
            style={{
              fontSize: '2.5rem',
              fontFamily: 'var(--font-mono)',
              fontWeight: 700,
              color: metrics.total_pnl >= 0 ? 'var(--accent-green)' : 'var(--accent-red)',
              lineHeight: 1,
            }}
          >
            {formatPnl(metrics.total_pnl)}
          </div>
        </div>
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '0.75rem',
            borderLeft: '1px solid var(--border)',
            paddingLeft: '1.5rem',
          }}
        >
          <Stat
            label="Daily"
            value={formatPnl(metrics.daily_pnl)}
            accent={metrics.daily_pnl >= 0 ? 'green' : 'red'}
            size="sm"
          />
          <Stat label="Win Rate" value={`${winRate}%`} accent="blue" size="sm" />
        </div>
      </div>

      {/* Metrics Grid */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fit, minmax(200px, 1fr))',
          gap: '1rem',
        }}
      >
        {/* Status Card */}
        <MetricCard
          title="Status"
          icon="◉"
          accent={connected ? 'var(--accent-green)' : 'var(--accent-red)'}
        >
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <div
                style={{
                  width: '10px',
                  height: '10px',
                  borderRadius: '50%',
                  background: connected ? 'var(--accent-green)' : 'var(--accent-red)',
                  boxShadow: connected
                    ? '0 0 8px var(--accent-green)'
                    : '0 0 8px var(--accent-red)',
                }}
              />
              <span
                style={{
                  fontFamily: 'var(--font-mono)',
                  fontSize: '0.875rem',
                  color: connected ? 'var(--accent-green)' : 'var(--accent-red)',
                }}
              >
                {connected ? 'CONNECTED' : 'DISCONNECTED'}
              </span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
              <Stat label="Uptime" value={formatUptime(metrics.uptime_sec)} size="sm" />
              <Stat
                label="Latency"
                value={`${metrics.avg_latency_ms.toFixed(0)}ms`}
                size="sm"
                accent={metrics.avg_latency_ms > 500 ? 'amber' : undefined}
              />
            </div>
          </div>
        </MetricCard>

        {/* Trading Activity Card */}
        <MetricCard title="Activity" icon="⚡" accent="var(--accent-blue)">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <Stat label="Markets" value={metrics.markets_scanned} size="sm" />
            <Stat label="Signals" value={metrics.opportunities_seen} size="sm" />
            <Stat label="Taken" value={metrics.opportunities_taken} accent="green" size="sm" />
            <Stat
              label="Hit Rate"
              value={
                metrics.opportunities_seen > 0
                  ? `${((metrics.opportunities_taken / metrics.opportunities_seen) * 100).toFixed(0)}%`
                  : '—'
              }
              size="sm"
            />
          </div>
        </MetricCard>

        {/* Execution Card */}
        <MetricCard title="Execution" icon="↗" accent="var(--accent-amber)">
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '1rem' }}>
            <Stat label="Filled" value={metrics.trades_filled} accent="green" size="sm" />
            <Stat
              label="Failed"
              value={metrics.trades_failed}
              accent={metrics.trades_failed > 0 ? 'red' : undefined}
              size="sm"
            />
            <Stat
              label="Reconnects"
              value={metrics.ws_reconnects}
              accent={metrics.ws_reconnects > 5 ? 'amber' : undefined}
              size="sm"
            />
            <Stat
              label="Losses"
              value={`${metrics.consecutive_losses} streak`}
              accent={metrics.consecutive_losses > 2 ? 'red' : undefined}
              size="sm"
            />
          </div>
        </MetricCard>
      </div>
    </div>
  );
}
