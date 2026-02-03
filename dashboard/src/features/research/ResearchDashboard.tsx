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

import { useResearchMetrics } from './hooks/useResearchMetrics';
import { ProbabilitySurface } from './components/ProbabilitySurface';
import { SignalDetector } from './components/SignalDetector';
import { EdgeCalculator } from './components/EdgeCalculator';
import { LagAnalysis } from './components/LagAnalysis';
import { BacktestResults } from './components/BacktestResults';
import { LiveObserver } from './components/LiveObserver';
import { PipelineStatusBar } from './components/PipelineControl';

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
    refresh,
  } = useResearchMetrics();

  const [activeTab, setActiveTab] = useState('lag-analysis');

  // Loading state
  if (isLoading) {
    return (
      <div
        style={{
          minHeight: '400px',
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

  // Show warning banner instead of blocking error state
  const showOfflineBanner = error && !isConnected;

  return (
    <div>
      {/* Offline Banner */}
      {showOfflineBanner && (
        <div
          style={{
            background: 'var(--accent-amber-dim)',
            border: '1px solid var(--accent-amber)',
            borderRadius: 'var(--radius-md)',
            padding: '0.75rem 1rem',
            marginBottom: '1rem',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
            <span style={{ fontSize: '1rem' }}>&#x26A0;</span>
            <span style={{ fontSize: '0.75rem', color: 'var(--accent-amber)' }}>
              <strong>Offline Mode:</strong> Research API not connected. Showing UI preview with empty data.
            </span>
          </div>
          <span
            style={{
              fontSize: '0.625rem',
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-muted)',
            }}
          >
            Start API server to enable live data
          </span>
        </div>
      )}

      {/* Pipeline Status Bar */}
      <PipelineStatusBar onPipelineComplete={() => refresh()} />

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
