import { useState } from 'react';
import { useMetrics } from './hooks/useMetrics';
import { MetricsDisplay } from './components/MetricsDisplay';
import { ControlPanel } from './components/ControlPanel';
import { ConfigPanel } from './components/ConfigPanel';
import { MarketsPanel } from './components/MarketsPanel';
import { LagWindowsPanel } from './components/LagWindowsPanel';
import { SignalFeed } from './components/SignalFeed';
import { SpotPricesPanel } from './components/SpotPricesPanel';
import { ResearchDashboard } from '@/features/research';
import './App.css';

type DashboardMode = 'trading' | 'research';

function App() {
  const [mode, setMode] = useState<DashboardMode>('trading');
  const { metrics, connected, refresh } = useMetrics();

  // Extract visibility data from metrics
  const activeMarkets = metrics?.active_markets || [];
  const activeWindows = metrics?.active_windows || [];
  const configSummary = metrics?.config_summary;

  // Extract unified event stream
  const events = metrics?.events || [];

  // Extract spot prices for price tracking panel
  const spotPrices = metrics?.spot_prices || {};

  // Derive bot status from metrics (single source of truth)
  const botRunning = metrics?.bot_running ?? false;
  const botPid = metrics?.pid ?? null;
  const botUptime = metrics?.uptime_sec ?? 0;

  return (
    <div
      style={{
        minHeight: '100vh',
        padding: '1.5rem',
      }}
    >
      {/* Header */}
      <header
        style={{
          marginBottom: '1.5rem',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-sm)',
              background:
                mode === 'trading'
                  ? 'linear-gradient(135deg, var(--accent-green) 0%, var(--accent-blue) 100%)'
                  : 'linear-gradient(135deg, var(--accent-amber, #f59e0b) 0%, var(--accent-blue) 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '1rem',
            }}
          >
            {mode === 'trading' ? '◈' : '🔬'}
          </div>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <h1
                style={{
                  margin: 0,
                  fontSize: '1rem',
                  fontWeight: 600,
                  color: 'var(--text-primary)',
                  letterSpacing: '-0.01em',
                }}
              >
                {mode === 'trading' ? 'Polymarket Arb Bot' : 'Polymarket Research'}
              </h1>
              {mode === 'research' && (
                <span
                  style={{
                    padding: '0.125rem 0.5rem',
                    fontSize: '0.5625rem',
                    fontWeight: 600,
                    textTransform: 'uppercase',
                    letterSpacing: '0.05em',
                    background: 'rgba(245, 158, 11, 0.15)',
                    color: 'var(--accent-amber, #f59e0b)',
                    border: '1px solid rgba(245, 158, 11, 0.3)',
                    borderRadius: '4px',
                  }}
                >
                  Research Mode
                </span>
              )}
            </div>
            <div
              style={{
                fontSize: '0.6875rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              {mode === 'trading'
                ? `${configSummary?.strategy || 'lag_arb'} | ${configSummary?.dry_run ? 'DRY RUN' : 'LIVE'}`
                : 'Probability Analysis | Lag Measurement | Backtesting'}
              {mode === 'trading' && configSummary?.model_loaded && (
                <span
                  style={{
                    fontSize: '0.625rem',
                    fontFamily: 'var(--font-mono)',
                    fontWeight: 600,
                    padding: '0.1875rem 0.5rem',
                    borderRadius: '3px',
                    background: 'rgba(0, 212, 170, 0.15)',
                    color: 'var(--accent-green)',
                    letterSpacing: '0.05em',
                    marginLeft: '0.5rem',
                  }}
                >
                  P() MODEL
                </span>
              )}
            </div>
          </div>
        </div>

        {/* Mode Toggle + Connection indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {/* Mode Toggle */}
          <div
            style={{
              display: 'flex',
              background: 'var(--bg-card)',
              borderRadius: '9999px',
              border: '1px solid var(--border)',
              padding: '2px',
            }}
          >
            <button
              onClick={() => setMode('trading')}
              style={{
                padding: '0.375rem 0.875rem',
                borderRadius: '9999px',
                border: 'none',
                background: mode === 'trading' ? 'var(--accent-blue)' : 'transparent',
                color: mode === 'trading' ? 'var(--bg-primary)' : 'var(--text-secondary)',
                fontSize: '0.6875rem',
                fontFamily: 'var(--font-mono)',
                fontWeight: 500,
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Trading
            </button>
            <button
              onClick={() => setMode('research')}
              style={{
                padding: '0.375rem 0.875rem',
                borderRadius: '9999px',
                border: 'none',
                background: mode === 'research' ? 'var(--accent-purple, #a855f7)' : 'transparent',
                color: mode === 'research' ? 'var(--bg-primary)' : 'var(--text-secondary)',
                fontSize: '0.6875rem',
                fontFamily: 'var(--font-mono)',
                fontWeight: 500,
                cursor: 'pointer',
                transition: 'all 0.15s ease',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Research
            </button>
          </div>

          {configSummary?.market_types && mode === 'trading' && (
            <div
              style={{
                padding: '0.375rem 0.75rem',
                background: 'var(--bg-card)',
                borderRadius: '9999px',
                border: '1px solid var(--border)',
                fontSize: '0.6875rem',
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-secondary)',
              }}
            >
              {configSummary.market_types.join(', ')}
            </div>
          )}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.375rem 0.75rem',
              background: connected ? 'var(--accent-green-dim)' : 'var(--accent-red-dim)',
              borderRadius: '9999px',
              border: `1px solid ${connected ? 'var(--accent-green)' : 'var(--accent-red)'}`,
            }}
          >
            <div
              style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                background: connected ? 'var(--accent-green)' : 'var(--accent-red)',
              }}
            />
            <span
              style={{
                fontSize: '0.6875rem',
                fontFamily: 'var(--font-mono)',
                fontWeight: 500,
                color: connected ? 'var(--accent-green)' : 'var(--accent-red)',
              }}
            >
              {connected ? 'LIVE' : 'OFFLINE'}
            </span>
          </div>
        </div>
      </header>

      {/* Main Content */}
      {mode === 'trading' ? (
        /* Trading Dashboard - 2-column layout (MVP) */
        <div
          style={{
            display: 'grid',
            gridTemplateColumns: '1fr 380px',
            gap: '1.5rem',
            maxWidth: '1400px',
          }}
        >
          {/* Left Column - Data flow: Prices → Markets → Windows → Events */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
            <SpotPricesPanel spotPrices={spotPrices} />
            <MarketsPanel markets={activeMarkets} />
            <LagWindowsPanel windows={activeWindows} config={configSummary} />
            <SignalFeed events={events} />
          </div>

          {/* Right Column - Controls + Config + Health */}
          <div
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '1rem',
            }}
          >
            <ControlPanel
              running={botRunning}
              pid={botPid}
              uptimeSec={botUptime}
              dryRun={configSummary?.dry_run}
              onRefresh={refresh}
            />
            <ConfigPanel />
            <MetricsDisplay metrics={metrics} connected={connected} />
          </div>
        </div>
      ) : (
        /* Research Dashboard */
        <ResearchDashboard />
      )}
    </div>
  );
}

export default App;
