import { useState, useEffect, useCallback } from 'react';
import { Button } from '@/components/ui/button';
import { SnapshotStream } from './SnapshotStream';
import type { EnrichedSnapshot, ObservationStatus } from '../../types/research.types';
import {
  startObservation,
  stopObservation,
  getObservationStatus,
  createResearchWebSocket,
} from '../../api/research-client';

interface StreamHealth {
  binanceConnected: boolean;
  binanceRate: number;
  chainlinkConnected: boolean;
  chainlinkRate: number;
  clobConnected: boolean;
  clobMarketsCount: number;
}

export function LiveObserver() {
  const [observationStatus, setObservationStatus] = useState<ObservationStatus>({
    is_running: false,
    started_at: null,
    duration_sec: null,
    snapshots_collected: 0,
    signals_detected: 0,
    time_remaining_sec: null,
  });
  const [durationInput, setDurationInput] = useState('3600');
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [isConnected, setIsConnected] = useState(false);
  const [snapshots, setSnapshots] = useState<EnrichedSnapshot[]>([]);
  const [streamHealth, setStreamHealth] = useState<StreamHealth>({
    binanceConnected: false,
    binanceRate: 0,
    chainlinkConnected: false,
    chainlinkRate: 0,
    clobConnected: false,
    clobMarketsCount: 0,
  });

  useEffect(() => {
    const ws = createResearchWebSocket({
      onOpen: () => {
        setIsConnected(true);
        setError(null);
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

    getObservationStatus()
      .then(setObservationStatus)
      .catch((err) => console.error('Failed to fetch observation status:', err));

    return () => {
      ws.disconnect();
    };
  }, []);

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
      setSnapshots([]);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to start observation');
    } finally {
      setIsLoading(false);
    }
  }, [durationInput]);

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

  const handleExport = useCallback(() => {
    alert('Export to Parquet - Not yet implemented');
  }, []);

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

  const statusColor = observationStatus.is_running ? '#00d4aa' : '#666';
  const statusLabel = observationStatus.is_running ? 'RECORDING' : 'IDLE';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '0.5rem', height: '100%' }}>
      {/* Compact Header Strip */}
      <div
        style={{
          background: 'var(--bg-card)',
          border: '1px solid var(--border)',
          borderRadius: '6px',
          padding: '0.625rem 1rem',
          display: 'flex',
          alignItems: 'center',
          gap: '1rem',
          borderLeft: `3px solid ${statusColor}`,
        }}
      >
        {/* Status indicator */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
          <div
            style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              background: statusColor,
              animation: observationStatus.is_running ? 'pulse 2s ease-in-out infinite' : 'none',
            }}
          />
          <span
            style={{
              fontSize: '0.5625rem',
              fontWeight: 600,
              fontFamily: 'var(--font-mono)',
              color: statusColor,
              textTransform: 'uppercase',
              letterSpacing: '0.05em',
            }}
          >
            {statusLabel}
          </span>
        </div>

        {/* Separator */}
        <div style={{ width: '1px', height: '24px', background: 'var(--border)' }} />

        {/* Inline stats */}
        <div style={{ display: 'flex', gap: '1.25rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Elapsed
            </span>
            <span
              style={{
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {displayDuration}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Snapshots
            </span>
            <span
              style={{
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {observationStatus.snapshots_collected.toLocaleString()}
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              Signals
            </span>
            <span
              style={{
                fontSize: '0.8125rem',
                fontWeight: 600,
                color: observationStatus.signals_detected > 0 ? '#ffaa00' : 'var(--text-primary)',
                fontFamily: 'var(--font-mono)',
              }}
            >
              {observationStatus.signals_detected}
            </span>
          </div>
        </div>

        {/* Separator */}
        <div style={{ width: '1px', height: '24px', background: 'var(--border)' }} />

        {/* Enrichment indicators */}
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
            <div
              style={{
                width: '5px',
                height: '5px',
                borderRadius: '50%',
                background: observationStatus.is_running ? '#00d4aa' : '#444',
              }}
            />
            <span
              style={{
                fontSize: '0.5625rem',
                fontFamily: 'var(--font-mono)',
                color: observationStatus.is_running ? '#00d4aa' : 'var(--text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.03em',
              }}
            >
              MODEL
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
            <div
              style={{
                width: '5px',
                height: '5px',
                borderRadius: '50%',
                background: observationStatus.is_running ? '#00d4aa' : '#444',
              }}
            />
            <span
              style={{
                fontSize: '0.5625rem',
                fontFamily: 'var(--font-mono)',
                color: observationStatus.is_running ? '#00d4aa' : 'var(--text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.03em',
              }}
            >
              EDGE
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
            <div
              style={{
                width: '5px',
                height: '5px',
                borderRadius: '50%',
                background: observationStatus.is_running ? '#ffaa00' : '#444',
              }}
            />
            <span
              style={{
                fontSize: '0.5625rem',
                fontFamily: 'var(--font-mono)',
                color: observationStatus.is_running ? '#ffaa00' : 'var(--text-muted)',
                textTransform: 'uppercase',
                letterSpacing: '0.03em',
              }}
            >
              SIGNAL
            </span>
          </div>
        </div>

        {/* Separator */}
        <div style={{ width: '1px', height: '24px', background: 'var(--border)' }} />

        {/* Stream health as compact dots */}
        <div style={{ display: 'flex', gap: '0.75rem', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
            <div
              style={{
                width: '5px',
                height: '5px',
                borderRadius: '50%',
                background: streamHealth.binanceConnected ? '#00d4aa' : '#ff4757',
              }}
            />
            <span
              style={{
                fontSize: '0.5625rem',
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
              }}
            >
              BIN
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
            <div
              style={{
                width: '5px',
                height: '5px',
                borderRadius: '50%',
                background: streamHealth.chainlinkConnected ? '#00d4aa' : '#ff4757',
              }}
            />
            <span
              style={{
                fontSize: '0.5625rem',
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
              }}
            >
              CL
            </span>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.25rem' }}>
            <div
              style={{
                width: '5px',
                height: '5px',
                borderRadius: '50%',
                background: streamHealth.clobConnected ? '#00d4aa' : '#ff4757',
              }}
            />
            <span
              style={{
                fontSize: '0.5625rem',
                fontFamily: 'var(--font-mono)',
                color: 'var(--text-muted)',
                textTransform: 'uppercase',
              }}
            >
              CLOB
            </span>
          </div>
        </div>

        {/* Spacer */}
        <div style={{ flex: 1 }} />

        {/* Controls - right aligned */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '0.5rem' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}>
            <span
              style={{
                fontSize: '0.5625rem',
                color: 'var(--text-muted)',
                fontFamily: 'var(--font-mono)',
                textTransform: 'uppercase',
              }}
            >
              Dur
            </span>
            <input
              type="number"
              value={durationInput}
              onChange={(e) => setDurationInput(e.target.value)}
              disabled={observationStatus.is_running || isLoading}
              min="60"
              max="86400"
              style={{
                width: '60px',
                padding: '0.25rem 0.375rem',
                fontSize: '0.6875rem',
                fontFamily: 'var(--font-mono)',
                background: 'var(--bg-elevated)',
                border: '1px solid var(--border)',
                borderRadius: '3px',
                color: 'var(--text-primary)',
              }}
            />
          </div>

          {!observationStatus.is_running ? (
            <Button
              onClick={handleStart}
              disabled={isLoading || !isConnected}
              size="sm"
              className="bg-[hsl(var(--primary))] hover:bg-[hsl(var(--primary))]/90"
              style={{ height: '24px', fontSize: '0.625rem', padding: '0 0.625rem' }}
            >
              {isLoading ? 'Starting...' : 'Start'}
            </Button>
          ) : (
            <Button
              onClick={handleStop}
              disabled={isLoading}
              variant="destructive"
              size="sm"
              style={{ height: '24px', fontSize: '0.625rem', padding: '0 0.625rem' }}
            >
              {isLoading ? 'Stopping...' : 'Stop'}
            </Button>
          )}

          <Button
            onClick={handleExport}
            disabled={snapshots.length === 0}
            variant="outline"
            size="sm"
            style={{ height: '24px', fontSize: '0.625rem', padding: '0 0.625rem' }}
          >
            Export
          </Button>
        </div>
      </div>

      {/* Error Display */}
      {error && (
        <div
          style={{
            padding: '0.375rem 0.75rem',
            background: 'rgba(255, 71, 87, 0.1)',
            border: '1px solid #ff4757',
            borderRadius: '4px',
            fontSize: '0.6875rem',
            color: '#ff4757',
          }}
        >
          {error}
        </div>
      )}

      {/* Snapshot Stream */}
      <div style={{ flex: 1, minHeight: 0 }}>
        <SnapshotStream snapshots={snapshots} maxItems={100} />
      </div>
    </div>
  );
}
