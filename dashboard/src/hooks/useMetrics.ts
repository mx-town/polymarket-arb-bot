import { useEffect, useState, useRef } from 'react';
import type { BotMetrics } from '../api/client';
import { createMetricsWebSocket, getMetrics } from '../api/client';

export function useMetrics() {
  const [metrics, setMetrics] = useState<BotMetrics | null>(null);
  const [connected, setConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  useEffect(() => {
    // Initial fetch
    getMetrics()
      .then(setMetrics)
      .catch((e) => setError(e.message));

    // Set up WebSocket for live updates
    const ws = createMetricsWebSocket((data) => {
      setMetrics(data);
      setError(null);
    });

    ws.onopen = () => setConnected(true);
    ws.onclose = () => setConnected(false);
    ws.onerror = () => setError('WebSocket connection failed');

    wsRef.current = ws;

    return () => {
      ws.close();
    };
  }, []);

  const refresh = async () => {
    try {
      const data = await getMetrics();
      setMetrics(data);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Unknown error');
    }
  };

  return { metrics, connected, error, refresh };
}
