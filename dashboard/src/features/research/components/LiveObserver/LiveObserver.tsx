import { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { SnapshotStream } from './SnapshotStream';
import { EnrichmentBadges, type EnrichmentStatus } from './EnrichmentBadges';
import type { EnrichedSnapshot, ObservationStatus } from '../../types/research.types';
import {
  startObservation,
  stopObservation,
  getObservationStatus,
  createResearchWebSocket,
} from '../../api/research-client';

interface StreamHealth {
  binanceConnected: boolean;
  binanceRate: number; // updates per second
  chainlinkConnected: boolean;
  chainlinkRate: number;
  clobConnected: boolean;
  clobMarketsCount: number;
}

/**
 * LiveObserver - Main component for real-time market observation
 * Displays live snapshots, controls, and stream health indicators
 */
export function LiveObserver() {
  // Observation state
  const [observationStatus, setObservationStatus] = useState<ObservationStatus>({
    is_running: false,
    started_at: null,
    duration_sec: null,
    snapshots_collected: 0,
    signals_detected: 0,
    time_remaining_sec: null,
  });
  const [durationInput, setDurationInput] = useState('3600'); // Default 1 hour
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // WebSocket and data state
  const [isConnected, setIsConnected] = useState(false);
  const [snapshots, setSnapshots] = useState<EnrichedSnapshot[]>([]);

  // Stream health (simulated for now - would come from WebSocket)
  const [streamHealth, setStreamHealth] = useState<StreamHealth>({
    binanceConnected: false,
    binanceRate: 0,
    chainlinkConnected: false,
    chainlinkRate: 0,
    clobConnected: false,
    clobMarketsCount: 0,
  });

  // Enrichment status derived from observation
  const enrichmentStatus: EnrichmentStatus = {
    modelLoaded: observationStatus.is_running,
    modelVersion: 'v1.0',
    candleInterval: '1H',
    isTrackingCandles: observationStatus.is_running,
    signalDetectionActive: observationStatus.is_running,
    signalsDetectedCount: observationStatus.signals_detected,
  };

  // Initialize WebSocket connection
  useEffect(() => {
    const ws = createResearchWebSocket({
      onOpen: () => {
        setIsConnected(true);
        setError(null);
        // Update stream health on connect
        setStreamHealth((prev) => ({
          ...prev,
          binanceConnected: true,
          chainlinkConnected: true,
          clobConnected: true,
        }));
      },
      onClose: () => {
        setIsConnected(false);
        setStreamHealth({
          binanceConnected: false,
          binanceRate: 0,
          chainlinkConnected: false,
          chainlinkRate: 0,
          clobConnected: false,
          clobMarketsCount: 0,
        });
      },
      onError: (err) => {
        setError(err.message);
      },
      onSnapshot: (snapshot) => {
        setSnapshots((prev) => [...prev.slice(-99), snapshot]);
        // Update rates (simplified)
        setStreamHealth((prev) => ({
          ...prev,
          binanceRate: Math.min(prev.binanceRate + 0.5, 10),
          chainlinkRate: Math.min(prev.chainlinkRate + 0.1, 1),
        }));
      },
      onObservationStatus: (status) => {
        setObservationStatus(status);
      },
    });

    ws.connect();

    // Fetch initial status
    getObservationStatus()
      .then(setObservationStatus)
      .catch((err) => console.error('Failed to fetch observation status:', err));

    return () => {
      ws.disconnect();
    };
  }, []);

  // Handle start observation
  const handleStart = useCallback(async () => {
    const duration = parseInt(durationInput, 10);
    if (isNaN(duration) || duration <= 0) {
      setError('Please enter a valid duration in seconds');
      return;
    }

    setIsLoading(true);
    setError(null);
    try {
      const status = await startObservation(duration);
      setObservationStatus(status);
      setSnapshots([]); // Clear previous snapshots
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start observation');
    } finally {
      setIsLoading(false);
    }
  }, [durationInput]);

  // Handle stop observation
  const handleStop = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const status = await stopObservation();
      setObservationStatus(status);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to stop observation');
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Handle export to parquet (placeholder)
  const handleExport = useCallback(() => {
    // TODO: Implement export API call
    alert('Export to Parquet - Not yet implemented');
  }, []);

  // Format duration for display
  const formatDuration = (startedAt: string | null): string => {
    if (!startedAt) return '00:00:00';
    const start = new Date(startedAt).getTime();
    const now = Date.now();
    const elapsed = Math.floor((now - start) / 1000);
    const hours = Math.floor(elapsed / 3600);
    const minutes = Math.floor((elapsed % 3600) / 60);
    const seconds = elapsed % 60;
    return `${hours.toString().padStart(2, '0')}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  };

  // Update duration display every second when running
  const [displayDuration, setDisplayDuration] = useState('00:00:00');
  useEffect(() => {
    if (!observationStatus.is_running) {
      setDisplayDuration('00:00:00');
      return;
    }

    const interval = setInterval(() => {
      setDisplayDuration(formatDuration(observationStatus.started_at));
    }, 1000);

    return () => clearInterval(interval);
  }, [observationStatus.is_running, observationStatus.started_at]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1rem', height: '100%' }}>
      {/* Header Card - Status & Controls */}
      <Card>
        <CardHeader className="pb-3">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem' }}>
              <CardTitle className="text-base">Live Observer</CardTitle>
              {/* Recording indicator */}
              {observationStatus.is_running && (
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '0.375rem',
                    padding: '0.25rem 0.625rem',
                    background: 'rgba(0, 212, 170, 0.15)',
                    borderRadius: '9999px',
                    border: '1px solid var(--color-accent-green)',
                  }}
                >
                  <div
                    style={{
                      width: '8px',
                      height: '8px',
                      borderRadius: '50%',
                      background: 'var(--color-accent-green)',
                      animation: 'pulse 2s ease-in-out infinite',
                    }}
                  />
                  <span
                    style={{
                      fontSize: '0.6875rem',
                      fontWeight: 600,
                      color: 'var(--color-accent-green)',
                      textTransform: 'uppercase',
                      letterSpacing: '0.05em',
                    }}
                  >
                    Recording
                  </span>
                </div>
              )}
            </div>

            {/* Connection status */}
            <div
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: '0.375rem',
                padding: '0.25rem 0.5rem',
                background: isConnected
                  ? 'rgba(0, 212, 170, 0.1)'
                  : 'rgba(255, 71, 87, 0.1)',
                borderRadius: 'var(--radius-sm)',
                border: `1px solid ${isConnected ? 'var(--color-accent-green)' : 'var(--color-accent-red)'}`,
              }}
            >
              <div
                style={{
                  width: '6px',
                  height: '6px',
                  borderRadius: '50%',
                  background: isConnected
                    ? 'var(--color-accent-green)'
                    : 'var(--color-accent-red)',
                }}
              />
              <span
                style={{
                  fontSize: '0.625rem',
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 500,
                  color: isConnected
                    ? 'var(--color-accent-green)'
                    : 'var(--color-accent-red)',
                }}
              >
                {isConnected ? 'CONNECTED' : 'DISCONNECTED'}
              </span>
            </div>
          </div>
        </CardHeader>

        <CardContent className="space-y-4">
          {/* Status Row */}
          <div
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(3, 1fr)',
              gap: '1rem',
              padding: '0.75rem',
              background: 'var(--color-bg-elevated)',
              borderRadius: 'var(--radius-sm)',
            }}
          >
            <StatusItem label="Duration" value={displayDuration} />
            <StatusItem
              label="Snapshots"
              value={observationStatus.snapshots_collected.toLocaleString()}
            />
            <StatusItem
              label="Signals"
              value={observationStatus.signals_detected.toString()}
              highlight={observationStatus.signals_detected > 0}
            />
          </div>

          {/* Controls Row */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.75rem', flexWrap: 'wrap' }}>
            {/* Duration Input */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
              <label
                style={{
                  fontSize: '0.6875rem',
                  color: 'var(--color-text-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                Duration (sec):
              </label>
              <input
                type="number"
                value={durationInput}
                onChange={(e) => setDurationInput(e.target.value)}
                disabled={observationStatus.is_running || isLoading}
                min="60"
                max="86400"
                style={{
                  width: '80px',
                  padding: '0.375rem 0.5rem',
                  fontSize: '0.75rem',
                  fontFamily: 'var(--font-mono)',
                  background: 'var(--color-bg-primary)',
                  border: '1px solid var(--color-border-main)',
                  borderRadius: 'var(--radius-sm)',
                  color: 'var(--color-text-primary)',
                }}
              />
            </div>

            {/* Action Buttons */}
            <div style={{ display: 'flex', gap: '0.5rem' }}>
              {!observationStatus.is_running ? (
                <Button
                  onClick={handleStart}
                  disabled={isLoading || !isConnected}
                  size="sm"
                  className="bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary))]/90"
                >
                  {isLoading ? 'Starting...' : 'Start'}
                </Button>
              ) : (
                <Button
                  onClick={handleStop}
                  disabled={isLoading}
                  variant="destructive"
                  size="sm"
                >
                  {isLoading ? 'Stopping...' : 'Stop'}
                </Button>
              )}

              <Button
                onClick={handleExport}
                disabled={snapshots.length === 0}
                variant="outline"
                size="sm"
              >
                Export Parquet
              </Button>
            </div>
          </div>

          {/* Error Display */}
          {error && (
            <div
              style={{
                padding: '0.5rem 0.75rem',
                background: 'rgba(255, 71, 87, 0.1)',
                border: '1px solid var(--color-accent-red)',
                borderRadius: 'var(--radius-sm)',
                fontSize: '0.75rem',
                color: 'var(--color-accent-red)',
              }}
            >
              {error}
            </div>
          )}

          {/* Stream Health Indicators */}
          <div
            style={{
              display: 'flex',
              gap: '1rem',
              padding: '0.5rem 0.75rem',
              background: 'var(--color-bg-primary)',
              borderRadius: 'var(--radius-sm)',
              border: '1px solid var(--color-border-subtle)',
            }}
          >
            <StreamHealthIndicator
              label="Binance"
              connected={streamHealth.binanceConnected}
              rate={streamHealth.binanceRate}
              unit="/s"
            />
            <StreamHealthIndicator
              label="Chainlink"
              connected={streamHealth.chainlinkConnected}
              rate={streamHealth.chainlinkRate}
              unit="/s"
            />
            <StreamHealthIndicator
              label="CLOB"
              connected={streamHealth.clobConnected}
              rate={streamHealth.clobMarketsCount}
              unit=" mkts"
            />
          </div>

          {/* Enrichment Badges */}
          <EnrichmentBadges status={enrichmentStatus} />
        </CardContent>
      </Card>

      {/* Snapshot Stream */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <SnapshotStream snapshots={snapshots} maxItems={100} />
      </div>
    </div>
  );
}

// Helper Components

interface StatusItemProps {
  label: string;
  value: string;
  highlight?: boolean;
}

function StatusItem({ label, value, highlight }: StatusItemProps) {
  return (
    <div style={{ textAlign: 'center' }}>
      <div
        style={{
          fontSize: '0.5625rem',
          textTransform: 'uppercase',
          letterSpacing: '0.1em',
          color: 'var(--color-text-muted)',
          marginBottom: '0.25rem',
        }}
      >
        {label}
      </div>
      <div
        style={{
          fontSize: '1.125rem',
          fontFamily: 'var(--font-mono)',
          fontWeight: 600,
          color: highlight ? 'var(--color-accent-amber)' : 'var(--color-text-primary)',
        }}
      >
        {value}
      </div>
    </div>
  );
}

interface StreamHealthIndicatorProps {
  label: string;
  connected: boolean;
  rate: number;
  unit: string;
}

function StreamHealthIndicator({ label, connected, rate, unit }: StreamHealthIndicatorProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
      <div
        style={{
          width: '6px',
          height: '6px',
          borderRadius: '50%',
          background: connected ? 'var(--color-accent-green)' : 'var(--color-accent-red)',
        }}
      />
      <span
        style={{
          fontSize: '0.625rem',
          color: 'var(--color-text-muted)',
          textTransform: 'uppercase',
        }}
      >
        {label}:
      </span>
      <span
        style={{
          fontSize: '0.6875rem',
          fontFamily: 'var(--font-mono)',
          color: connected ? 'var(--color-text-secondary)' : 'var(--color-text-muted)',
        }}
      >
        {connected ? `${rate.toFixed(1)}${unit}` : 'offline'}
      </span>
    </div>
  );
}
