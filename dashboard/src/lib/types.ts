// ─── Wire types (match Python event schema exactly) ───

export interface TickSnapshot {
  type: "tick_snapshot";
  ts: number;
  data: {
    markets: MarketState[];
    exposure: ExposureBreakdown;
    pnl: PnLState;
    bankroll: BankrollState;
  };
}

export interface MarketState {
  slug: string;
  seconds_to_end: number;
  up_bid: number | null;
  up_ask: number | null;
  down_bid: number | null;
  down_ask: number | null;
  edge: number | null;
  position: PositionState | null;
  orders?: OrderInfo[];
}

export interface PositionState {
  up_shares: number;
  down_shares: number;
  up_vwap: number | null;
  down_vwap: number | null;
  hedged: number;
  imbalance: number;
  unrealized_pnl: number;
}

export interface ExposureBreakdown {
  total: number;
  orders: number;
  unhedged: number;
  hedged: number;
}

export interface PnLState {
  realized: number;
  unrealized: number;
  total: number;
}

export interface BankrollState {
  usd: number;
  pct_used: number;
  wallet: string;
}

export interface BtcPrice {
  type: "btc_price";
  ts: number;
  data: BtcPriceData;
}

export interface BtcPriceData {
  price: number;
  open: number;
  high: number;
  low: number;
  deviation: number;
  range_pct: number;
}

export interface TradeEvent {
  type: string;
  ts: number;
  data: {
    slug: string;
    direction: "UP" | "DOWN";
    side?: string;
    price?: number;
    shares?: number;
    edge?: number;
    tx_hash?: string;
    reason?: string;
  };
  slug?: string;
}

export interface OrderInfo {
  token_id: string;
  side: string;
  direction: string | null;
  price: number;
  size: number;
  matched: number;
}

export interface WsMessage {
  type: string;
  ts: number;
  data: any;
  slug?: string;
}

export interface StateSnapshot {
  markets: MarketState[];
  exposure: ExposureBreakdown;
  pnl: PnLState;
  bankroll: BankrollState;
  btc: BtcPriceData;
  config: ConfigState;
  meta: MetaState;
}

export interface ConfigState {
  dry_run: boolean;
  min_edge: number;
  bankroll_usd: number;
  assets: string[];
}

export interface MetaState {
  tick_count: number;
  avg_tick_ms: number;
  uptime_sec: number;
}
