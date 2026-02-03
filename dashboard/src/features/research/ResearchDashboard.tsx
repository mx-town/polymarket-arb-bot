/**
 * ResearchDashboard - Main research UI layout
 *
 * Layout structure:
 * ┌─────────────────────────────────────────────────────────────────────────────┐
 * │  HEADER: "Research Mode" badge + connection status                          │
 * ├──────────────────┬──────────────────────────────────────┬───────────────────┤
 * │  SIGNALS         │  PROBABILITY SURFACE (hero)          │  EDGE CALCULATOR  │
 * │  (SignalDetector)│  (ProbabilitySurface)                │  (EdgeCalculator) │
 * ├──────────────────┴──────────────────────────────────────┴───────────────────┤
 * │  TABS: [ Lag Analysis ] [ Backtest ] [ Live Observer ]                      │
 * ├─────────────────────────────────────────────────────────────────────────────┤
 * │  TAB CONTENT (dynamic based on selected tab)                                │
 * └─────────────────────────────────────────────────────────────────────────────┘
 */

import { useState } from 'react';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Badge } from '@/components/ui/badge';

import { useResearchMetrics } from './hooks/useResearchMetrics';
import { ProbabilitySurface } from './components/ProbabilitySurface';
import { SignalDetector } from './components/SignalDetector';
import { EdgeCalculator } from './components/EdgeCalculator';
import { LagAnalysis } from './components/LagAnalysis';
import { BacktestResults } from './components/BacktestResults';
import { LiveObserver } from './components/LiveObserver';

export function ResearchDashboard() {
  const {
    surface,
    signals,
    opportunities,
    lagStats,
    isConnected,
    isLoading,
    error,
    clearSignals,
  } = useResearchMetrics();

  const [activeTab, setActiveTab] = useState('lag-analysis');

  // Loading state
  if (isLoading) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '2rem',
        }}
      >
        <div
          style={{
            width: '48px',
            height: '48px',
            border: '3px solid var(--border)',
            borderTopColor: 'var(--accent-blue)',
            borderRadius: '50%',
            animation: 'spin 1s linear infinite',
            marginBottom: '1.5rem',
          }}
        />
        <style>
          {`
            @keyframes spin {
              to { transform: rotate(360deg); }
            }
          `}
        </style>
        <div
          style={{
            fontSize: '0.875rem',
            color: 'var(--text-secondary)',
            marginBottom: '0.5rem',
          }}
        >
          Loading Research Data
        </div>
        <div
          style={{
            fontSize: '0.75rem',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
          }}
        >
          Connecting to research API...
        </div>
      </div>
    );
  }

  // Error state
  if (error && !surface && signals.length === 0) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          padding: '2rem',
        }}
      >
        <div
          style={{
            background: 'var(--accent-red-dim)',
            border: '1px solid var(--accent-red)',
            borderRadius: 'var(--radius-md)',
            padding: '2rem',
            maxWidth: '480px',
            textAlign: 'center',
          }}
        >
          <div
            style={{
              fontSize: '2rem',
              marginBottom: '1rem',
            }}
          >
            &#x26A0;
          </div>
          <div
            style={{
              fontSize: '1rem',
              fontWeight: 600,
              color: 'var(--accent-red)',
              marginBottom: '0.75rem',
            }}
          >
            Failed to Load Research Data
          </div>
          <div
            style={{
              fontSize: '0.75rem',
              color: 'var(--text-secondary)',
              marginBottom: '1rem',
            }}
          >
            {error}
          </div>
          <button
            onClick={() => window.location.reload()}
            style={{
              padding: '0.5rem 1rem',
              borderRadius: 'var(--radius-sm)',
              background: 'var(--accent-blue)',
              color: 'white',
              fontSize: '0.75rem',
              fontWeight: 500,
              cursor: 'pointer',
              border: 'none',
            }}
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

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
          {/* Logo */}
          <div
            style={{
              width: '32px',
              height: '32px',
              borderRadius: 'var(--radius-sm)',
              background:
                'linear-gradient(135deg, var(--accent-amber) 0%, var(--accent-blue) 100%)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              fontSize: '1rem',
            }}
          >
            &#x1F52C;
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
                Polymarket Research
              </h1>
              <Badge
                variant="outline"
                className="text-[10px] uppercase tracking-wider border-amber-500/50 text-amber-500 bg-amber-500/10"
              >
                Research Mode
              </Badge>
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
              Probability Analysis | Lag Measurement | Backtesting
            </div>
          </div>
        </div>

        {/* Connection Status */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
          {/* Signal count badge */}
          {signals.length > 0 && (
            <div
              style={{
                padding: '0.375rem 0.75rem',
                background: 'var(--accent-green-dim)',
                borderRadius: '9999px',
                border: '1px solid var(--accent-green)',
                fontSize: '0.6875rem',
                fontFamily: 'var(--font-mono)',
                color: 'var(--accent-green)',
              }}
            >
              {signals.length} signals
            </div>
          )}

          {/* Connection indicator */}
          <div
            style={{
              display: 'flex',
              alignItems: 'center',
              gap: '0.5rem',
              padding: '0.375rem 0.75rem',
              background: isConnected ? 'var(--accent-green-dim)' : 'var(--accent-red-dim)',
              borderRadius: '9999px',
              border: `1px solid ${isConnected ? 'var(--accent-green)' : 'var(--accent-red)'}`,
            }}
          >
            <div
              style={{
                width: '6px',
                height: '6px',
                borderRadius: '50%',
                background: isConnected ? 'var(--accent-green)' : 'var(--accent-red)',
              }}
            />
            <span
              style={{
                fontSize: '0.6875rem',
                fontFamily: 'var(--font-mono)',
                fontWeight: 500,
                color: isConnected ? 'var(--accent-green)' : 'var(--accent-red)',
              }}
            >
              {isConnected ? 'LIVE' : 'OFFLINE'}
            </span>
          </div>
        </div>
      </header>

      {/* Main Content - 3-column layout */}
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '280px 1fr 320px',
          gap: '1.5rem',
          marginBottom: '1.5rem',
        }}
      >
        {/* Left Column - Signal Detector */}
        <div style={{ minHeight: '400px' }}>
          <SignalDetector signals={signals} onClear={clearSignals} />
        </div>

        {/* Center Column - Probability Surface (Hero) */}
        <div>
          <ProbabilitySurface
            surface={surface}
            title="Win Probability Surface"
            onCellClick={(bucket) => {
              console.log('Cell clicked:', bucket);
            }}
          />
        </div>

        {/* Right Column - Edge Calculator */}
        <div>
          <EdgeCalculator opportunities={opportunities} />
        </div>
      </div>

      {/* Tabs Section */}
      <Tabs value={activeTab} onValueChange={setActiveTab} className="w-full">
        <TabsList
          className="w-full justify-start"
          style={{
            background: 'var(--bg-card)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-md)',
            padding: '0.5rem',
            marginBottom: '1rem',
          }}
        >
          <TabsTrigger
            value="lag-analysis"
            className="data-[state=active]:bg-[var(--bg-elevated)] data-[state=active]:text-[var(--text-primary)]"
            style={{
              fontSize: '0.75rem',
              fontWeight: 500,
              padding: '0.5rem 1rem',
            }}
          >
            <span style={{ marginRight: '0.5rem' }}>&#x23F1;</span>
            Lag Analysis
          </TabsTrigger>
          <TabsTrigger
            value="backtest"
            className="data-[state=active]:bg-[var(--bg-elevated)] data-[state=active]:text-[var(--text-primary)]"
            style={{
              fontSize: '0.75rem',
              fontWeight: 500,
              padding: '0.5rem 1rem',
            }}
          >
            <span style={{ marginRight: '0.5rem' }}>&#x1F4CA;</span>
            Backtest
          </TabsTrigger>
          <TabsTrigger
            value="live-observer"
            className="data-[state=active]:bg-[var(--bg-elevated)] data-[state=active]:text-[var(--text-primary)]"
            style={{
              fontSize: '0.75rem',
              fontWeight: 500,
              padding: '0.5rem 1rem',
            }}
          >
            <span style={{ marginRight: '0.5rem' }}>&#x1F4E1;</span>
            Live Observer
            {isConnected && (
              <span
                style={{
                  marginLeft: '0.5rem',
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  background: 'var(--accent-green)',
                  display: 'inline-block',
                  animation: 'pulse 2s ease-in-out infinite',
                }}
              />
            )}
          </TabsTrigger>
        </TabsList>

        <TabsContent value="lag-analysis" className="mt-0">
          <LagAnalysis lagStats={lagStats} />
        </TabsContent>

        <TabsContent value="backtest" className="mt-0">
          <BacktestResults />
        </TabsContent>

        <TabsContent value="live-observer" className="mt-0">
          <LiveObserver />
        </TabsContent>
      </Tabs>
    </div>
  );
}

export default ResearchDashboard;
