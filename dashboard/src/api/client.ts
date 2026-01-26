/**
 * API client for the Polymarket Arb Bot backend
 */

const API_BASE = '/api';

export interface BotStatus {
  running: boolean;
  pid: number | null;
  uptime_sec?: number;
  start_time?: string;
  last_update?: string;
}

export interface ActiveMarket {
  slug: string;
  market_id: string;
  combined_ask: number;
  combined_bid: number;
  up_best_ask: number;
  up_best_bid: number;
  down_best_ask: number;
  down_best_bid: number;
  is_valid: boolean;
  last_updated: string | null;
}

export interface LagWindow {
  symbol: string;
  expected_winner: string;
  direction: string;
  start_time: string;
  remaining_ms: number;
  entry_made: boolean;
  momentum: number;
  spot_price: number;
  candle_open: number;
}

export interface SignalEntry {
  type: string;
  symbol: string;
  timestamp: string;
  direction?: string;
  momentum?: number;
  spot_price?: number;
  candle_open?: number;
  expected_winner?: string;
  confidence?: number;
}

export interface ConfigSummary {
  strategy: string;
  dry_run: boolean;
  lag_arb_enabled: boolean;
  market_types: string[];
  momentum_threshold: number;
  max_lag_window_ms: number;
  max_combined_price: number;
}

export interface BotMetrics {
  cycles: number;
  uptime_sec: number;
  markets_scanned: number;
  opportunities_seen: number;
  opportunities_taken: number;
  trades_filled: number;
  trades_failed: number;
  total_pnl: number;
  daily_pnl: number;
  consecutive_losses: number;
  ws_reconnects: number;
  avg_latency_ms: number;
  timestamp?: string;
  start_time?: string;
  markets_fetched?: number;
  trades_attempted?: number;
  trades_partial?: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  current_exposure?: number;
  ws_message_count?: number;
  error?: string;
  bot_running?: boolean;
  // Dashboard visibility data
  active_markets?: ActiveMarket[];
  active_windows?: LagWindow[];
  recent_signals?: SignalEntry[];
  config_summary?: ConfigSummary;
}

export interface BotConfig {
  trading: {
    dry_run: boolean;
    min_spread: number;
    min_net_profit: number;
    max_position_size: number;
    fee_rate: number;
  };
  polling: {
    interval: number;
    batch_size: number;
    max_markets: number;
    market_refresh_interval: number;
  };
  websocket: {
    ping_interval: number;
    reconnect_delay: number;
  };
  conservative: {
    max_combined_price: number;
    min_time_to_resolution_sec: number;
    exit_on_pump_threshold: number;
  };
  lag_arb: {
    enabled: boolean;
    candle_interval: string;
    spot_momentum_window_sec: number;
    spot_move_threshold_pct: number;
    max_combined_price: number;
    expected_lag_ms: number;
    max_lag_window_ms: number;
    fee_rate: number;
    momentum_trigger_threshold_pct: number;
    pump_exit_threshold_pct: number;
    max_hold_time_sec: number;
  };
  risk: {
    max_consecutive_losses: number;
    max_daily_loss_usd: number;
    cooldown_after_loss_sec: number;
    max_total_exposure: number;
  };
  filters: {
    min_liquidity_usd: number;
    min_book_depth: number;
    max_spread_pct: number;
    max_market_age_hours: number;
    fallback_age_hours: number;
    min_volume_24h: number;
    market_types: string[];
  };
}

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(url, options);
  if (!response.ok) {
    throw new Error(`HTTP ${response.status}: ${response.statusText}`);
  }
  return response.json();
}

export async function getStatus(): Promise<BotStatus> {
  const data = await fetchJson<{ running: boolean; pid: number | null; uptime_sec?: number; start_time?: string; last_update?: string }>(
    `${API_BASE}/status`
  );
  return data;
}

export async function getMetrics(): Promise<BotMetrics> {
  const data = await fetchJson<{ metrics: BotMetrics }>(`${API_BASE}/metrics`);
  return data.metrics;
}

export async function getConfig(): Promise<BotConfig> {
  const data = await fetchJson<{ config: BotConfig }>(`${API_BASE}/config`);
  return data.config;
}

export async function updateConfig(config: Partial<BotConfig>): Promise<BotConfig> {
  const data = await fetchJson<{ config: BotConfig }>(`${API_BASE}/config`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ config }),
  });
  return data.config;
}

export async function restartBot(): Promise<{ status: string; message: string }> {
  return fetchJson(`${API_BASE}/restart`, { method: 'POST' });
}

export function createMetricsWebSocket(onMessage: (metrics: BotMetrics) => void): WebSocket {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  const ws = new WebSocket(`${protocol}//${window.location.host}/api/ws/metrics`);

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);
      onMessage(data.metrics);
    } catch (e) {
      console.error('Failed to parse metrics:', e);
    }
  };

  return ws;
}
