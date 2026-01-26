import { useMetrics } from './hooks/useMetrics';
import { MetricsDisplay } from './components/MetricsDisplay';
import { ControlPanel } from './components/ControlPanel';
import { ConfigPanel } from './components/ConfigPanel';
import './App.css';

function App() {
  const { metrics, connected } = useMetrics();

  return (
    <div style={{
      minHeight: '100vh',
      padding: '1.5rem',
    }}>
      {/* Header */}
      <header style={{
        marginBottom: '1.5rem',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div style={{
            width: '32px',
            height: '32px',
            borderRadius: 'var(--radius-sm)',
            background: 'linear-gradient(135deg, var(--accent-green) 0%, var(--accent-blue) 100%)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: '1rem',
          }}>
            ◈
          </div>
          <div>
            <h1 style={{
              margin: 0,
              fontSize: '1rem',
              fontWeight: 600,
              color: 'var(--text-primary)',
              letterSpacing: '-0.01em',
            }}>
              Polymarket Arb Bot
            </h1>
            <div style={{
              fontSize: '0.6875rem',
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}>
              Dashboard v1.0
            </div>
          </div>
        </div>

        {/* Connection indicator */}
        <div style={{
          display: 'flex',
          alignItems: 'center',
          gap: '0.5rem',
          padding: '0.375rem 0.75rem',
          background: connected ? 'var(--accent-green-dim)' : 'var(--accent-red-dim)',
          borderRadius: '9999px',
          border: `1px solid ${connected ? 'var(--accent-green)' : 'var(--accent-red)'}`,
        }}>
          <div style={{
            width: '6px',
            height: '6px',
            borderRadius: '50%',
            background: connected ? 'var(--accent-green)' : 'var(--accent-red)',
          }} />
          <span style={{
            fontSize: '0.6875rem',
            fontFamily: 'var(--font-mono)',
            fontWeight: 500,
            color: connected ? 'var(--accent-green)' : 'var(--accent-red)',
          }}>
            {connected ? 'LIVE' : 'OFFLINE'}
          </span>
        </div>
      </header>

      {/* Main Content */}
      <div style={{
        display: 'grid',
        gridTemplateColumns: '1fr 280px',
        gap: '1.5rem',
        maxWidth: '1400px',
      }}>
        {/* Left Column - Metrics & Config */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '1.5rem' }}>
          <MetricsDisplay metrics={metrics} connected={connected} />
          <ConfigPanel />
        </div>

        {/* Right Column - Control */}
        <div style={{
          display: 'flex',
          flexDirection: 'column',
          gap: '1rem',
        }}>
          <ControlPanel />

          {/* Quick Info */}
          <div style={{
            background: 'var(--bg-card)',
            borderRadius: 'var(--radius-md)',
            border: '1px solid var(--border)',
            padding: '1rem',
          }}>
            <div style={{
              fontSize: '0.625rem',
              textTransform: 'uppercase',
              letterSpacing: '0.1em',
              color: 'var(--text-muted)',
              marginBottom: '0.75rem',
            }}>
              Quick Actions
            </div>
            <div style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '0.5rem',
              fontSize: '0.75rem',
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-secondary)',
            }}>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>Start:</span>{' '}
                <span style={{ color: 'var(--accent-blue)' }}>uv run python -m src.main</span>
              </div>
              <div>
                <span style={{ color: 'var(--text-muted)' }}>API:</span>{' '}
                <span style={{ color: 'var(--accent-blue)' }}>:8000</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}

export default App;
