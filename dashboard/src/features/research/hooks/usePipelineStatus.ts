/**
 * Hook for pipeline status and control.
 *
 * - Fetches pipeline status on mount
 * - Subscribes to pipeline_progress and pipeline_complete via WebSocket
 * - Exposes: status, currentJob, startCommand(), stopCommand(), refetch()
 * - On pipeline_complete: auto-refetch status
 */

import { useEffect, useState, useCallback, useRef } from 'react';
import type {
  PipelineStatus,
  PipelineJobStatus,
  PipelineProgressEvent,
} from '../types/research.types';
import {
  fetchPipelineStatus,
  startPipelineCommand,
  stopPipelineCommand,
  ResearchWebSocket,
} from '../api/research-client';

export interface UsePipelineStatusReturn {
  /** Filesystem state (model, data, observations) */
  status: PipelineStatus | null;
  /** Currently running job (from WS updates) */
  currentJob: PipelineJobStatus | null;
  /** Start a pipeline command */
  startCommand: (command: string, args?: Record<string, unknown>) => Promise<void>;
  /** Stop the current command */
  stopCommand: () => Promise<void>;
  /** Refresh pipeline status from server */
  refetch: () => Promise<void>;
  /** Whether a command is starting (optimistic) */
  isStarting: boolean;
  /** Error from last operation */
  error: string | null;
}

export function usePipelineStatus(): UsePipelineStatusReturn {
  const [status, setStatus] = useState<PipelineStatus | null>(null);
  const [currentJob, setCurrentJob] = useState<PipelineJobStatus | null>(null);
  const [isStarting, setIsStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<ResearchWebSocket | null>(null);

  const refetch = useCallback(async () => {
    try {
      setError(null);
      const pipelineStatus = await fetchPipelineStatus();
      setStatus(pipelineStatus);
      setCurrentJob(pipelineStatus.current_job);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to fetch pipeline status');
    }
  }, []);

  const startCommand = useCallback(async (command: string, args: Record<string, unknown> = {}) => {
    try {
      setError(null);
      setIsStarting(true);
      const job = await startPipelineCommand(command, args);
      setCurrentJob(job);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to start command');
    } finally {
      setIsStarting(false);
    }
  }, []);

  const stopCommand = useCallback(async () => {
    try {
      setError(null);
      const job = await stopPipelineCommand();
      setCurrentJob(job);
      // Refetch status after stop
      await refetch();
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Failed to stop command');
    }
  }, [refetch]);

  useEffect(() => {
    // Initial fetch
    refetch();

    // Subscribe to pipeline WS events
    const ws = new ResearchWebSocket({
      onInitial: (data) => {
        if (data.pipeline_status) {
          setStatus(data.pipeline_status);
          setCurrentJob(data.pipeline_status.current_job);
        }
      },
      onPipelineProgress: (event: PipelineProgressEvent) => {
        // Update current job's progress trail
        setCurrentJob((prev) => {
          if (!prev) return prev;
          return {
            ...prev,
            progress: [...prev.progress, event],
          };
        });
      },
      onPipelineComplete: (job: PipelineJobStatus) => {
        setCurrentJob(job);
        // Auto-refetch status on completion
        refetch();
      },
    });

    ws.connect();
    wsRef.current = ws;

    return () => {
      ws.disconnect();
    };
  }, [refetch]);

  return {
    status,
    currentJob,
    startCommand,
    stopCommand,
    refetch,
    isStarting,
    error,
  };
}
