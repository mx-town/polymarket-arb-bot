/**
 * Research API client
 * Provides functions for interacting with the research backend endpoints
 */

import type {
  ProbabilitySurface,
  Signal,
  LagStats,
  BacktestResult,
  ResearchMetrics,
  ObservationStatus,
  EnrichedSnapshot,
  TradingOpportunity,
  ResearchWebSocketMessage,
} from '../types/research.types';

const API_BASE = '/api/research';

/**
 * Generic fetch wrapper with error handling
 */
async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    const errorBody = await response.text().catch(() => 'Unknown error');
    throw new Error(`HTTP ${response.status}: ${response.statusText} - ${errorBody}`);
  }
  return response.json();
}

/**
 * Fetch the current probability surface
 * @returns The probability surface with all buckets and metadata
 */
export async function fetchProbabilitySurface(): Promise<ProbabilitySurface> {
  const data = await fetchJson<{ surface: ProbabilitySurface }>(`${API_BASE}/surface`);
  return data.surface;
}

/**
 * Fetch recent signals
 * @param limit - Maximum number of signals to return (default: 50)
 * @returns Array of recent signals
 */
export async function fetchSignals(limit: number = 50): Promise<Signal[]> {
  const data = await fetchJson<{ signals: Signal[] }>(
    `${API_BASE}/signals?limit=${limit}`
  );
  return data.signals;
}

/**
 * Fetch lag statistics between Binance and Polymarket
 * @returns Lag statistics object
 */
export async function fetchLagStats(): Promise<LagStats> {
  const data = await fetchJson<{ lag_stats: LagStats }>(`${API_BASE}/lag-stats`);
  return data.lag_stats;
}

/**
 * Fetch backtest results
 * @returns Backtest results including trades, equity curve, and metrics
 */
export async function fetchBacktestResults(): Promise<BacktestResult> {
  const data = await fetchJson<{ backtest: BacktestResult }>(`${API_BASE}/backtest`);
  return data.backtest;
}

/**
 * Fetch complete research metrics
 * @returns All research metrics in a single payload
 */
export async function fetchResearchMetrics(): Promise<ResearchMetrics> {
  const data = await fetchJson<{ metrics: ResearchMetrics }>(`${API_BASE}/metrics`);
  return data.metrics;
}

/**
 * Start observation/data collection
 * @param duration_sec - Duration of observation in seconds
 * @returns Updated observation status
 */
export async function startObservation(duration_sec: number): Promise<ObservationStatus> {
  const data = await fetchJson<{ status: ObservationStatus }>(
    `${API_BASE}/observation/start`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ duration_sec }),
    }
  );
  return data.status;
}

/**
 * Stop ongoing observation/data collection
 * @returns Final observation status
 */
export async function stopObservation(): Promise<ObservationStatus> {
  const data = await fetchJson<{ status: ObservationStatus }>(
    `${API_BASE}/observation/stop`,
    {
      method: 'POST',
    }
  );
  return data.status;
}

/**
 * Get current observation status
 * @returns Current observation status
 */
export async function getObservationStatus(): Promise<ObservationStatus> {
  const data = await fetchJson<{ status: ObservationStatus }>(
    `${API_BASE}/observation/status`
  );
  return data.status;
}

/**
 * Callback types for WebSocket events
 */
export interface ResearchWebSocketCallbacks {
  onSnapshot?: (snapshot: EnrichedSnapshot) => void;
  onSignal?: (signal: Signal) => void;
  onOpportunity?: (opportunity: TradingOpportunity) => void;
  onSurfaceUpdate?: (surface: ProbabilitySurface) => void;
  onObservationStatus?: (status: ObservationStatus) => void;
  onError?: (error: Error) => void;
  onClose?: (event: CloseEvent) => void;
  onOpen?: () => void;
}

/**
 * Research WebSocket connection manager
 */
export class ResearchWebSocket {
  private ws: WebSocket | null = null;
  private callbacks: ResearchWebSocketCallbacks;
  private reconnectAttempts: number = 0;
  private maxReconnectAttempts: number = 5;
  private reconnectDelay: number = 1000;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private isIntentionalClose: boolean = false;

  constructor(callbacks: ResearchWebSocketCallbacks) {
    this.callbacks = callbacks;
  }

  /**
   * Connect to the research WebSocket endpoint
   */
  connect(): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      return;
    }

    this.isIntentionalClose = false;
    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/api/ws/research`;

    try {
      this.ws = new WebSocket(wsUrl);
      this.setupEventHandlers();
    } catch (error) {
      this.callbacks.onError?.(error instanceof Error ? error : new Error(String(error)));
      this.scheduleReconnect();
    }
  }

  /**
   * Set up WebSocket event handlers
   */
  private setupEventHandlers(): void {
    if (!this.ws) return;

    this.ws.onopen = () => {
      this.reconnectAttempts = 0;
      this.callbacks.onOpen?.();
    };

    this.ws.onmessage = (event: MessageEvent) => {
      this.handleMessage(event);
    };

    this.ws.onerror = (event: Event) => {
      console.error('Research WebSocket error:', event);
      this.callbacks.onError?.(new Error('WebSocket connection error'));
    };

    this.ws.onclose = (event: CloseEvent) => {
      this.callbacks.onClose?.(event);
      if (!this.isIntentionalClose) {
        this.scheduleReconnect();
      }
    };
  }

  /**
   * Handle incoming WebSocket messages
   */
  private handleMessage(event: MessageEvent): void {
    try {
      const message = JSON.parse(event.data) as ResearchWebSocketMessage;

      switch (message.type) {
        case 'snapshot':
          this.callbacks.onSnapshot?.(message.data as EnrichedSnapshot);
          break;
        case 'signal':
          this.callbacks.onSignal?.(message.data as Signal);
          break;
        case 'opportunity':
          this.callbacks.onOpportunity?.(message.data as TradingOpportunity);
          break;
        case 'surface_update':
          this.callbacks.onSurfaceUpdate?.(message.data as ProbabilitySurface);
          break;
        case 'observation_status':
          this.callbacks.onObservationStatus?.(message.data as ObservationStatus);
          break;
        default:
          console.warn('Unknown research WebSocket message type:', message.type);
      }
    } catch (error) {
      console.error('Failed to parse research WebSocket message:', error);
    }
  }

  /**
   * Schedule a reconnection attempt
   */
  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      console.error('Max reconnection attempts reached for research WebSocket');
      return;
    }

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
    }

    const delay = this.reconnectDelay * Math.pow(2, this.reconnectAttempts);
    this.reconnectAttempts++;

    this.reconnectTimer = setTimeout(() => {
      console.log(`Attempting research WebSocket reconnection (attempt ${this.reconnectAttempts})`);
      this.connect();
    }, delay);
  }

  /**
   * Send a message through the WebSocket
   */
  send(message: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(message));
    } else {
      console.warn('Cannot send message: WebSocket is not connected');
    }
  }

  /**
   * Close the WebSocket connection
   */
  disconnect(): void {
    this.isIntentionalClose = true;

    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }

    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
  }

  /**
   * Check if WebSocket is connected
   */
  isConnected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /**
   * Get current reconnection attempt count
   */
  getReconnectAttempts(): number {
    return this.reconnectAttempts;
  }

  /**
   * Reset reconnection attempts (useful after manual reconnect)
   */
  resetReconnectAttempts(): void {
    this.reconnectAttempts = 0;
  }
}

/**
 * Create a research WebSocket connection with callbacks
 * @param callbacks - Event callbacks for different message types
 * @returns ResearchWebSocket instance
 */
export function createResearchWebSocket(
  callbacks: ResearchWebSocketCallbacks
): ResearchWebSocket {
  return new ResearchWebSocket(callbacks);
}
