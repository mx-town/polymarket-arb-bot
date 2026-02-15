import { create } from "zustand";
import type {
  MarketState,
  ExposureBreakdown,
  PnLState,
  BankrollState,
  BtcPriceData,
  ConfigState,
  MetaState,
  TradeEvent,
  StateSnapshot,
  TickSnapshot,
  TrendRiderState,
} from "@/lib/types";

// ─── State shape ───

interface BotState {
  connected: boolean;
  markets: MarketState[];
  exposure: ExposureBreakdown;
  pnl: PnLState;
  bankroll: BankrollState;
  btc: BtcPriceData | null;
  config: ConfigState | null;
  meta: MetaState | null;
  tradeEvents: TradeEvent[];
  trendRider: TrendRiderState | null;
}

// ─── Actions ───

interface BotActions {
  setConnected: (v: boolean) => void;
  updateFromSnapshot: (snap: StateSnapshot) => void;
  updateTick: (tick: TickSnapshot) => void;
  updateBtc: (btc: BtcPriceData) => void;
  addTradeEvent: (evt: TradeEvent) => void;
}

// ─── Defaults ───

const defaultExposure: ExposureBreakdown = {
  total: 0,
  orders: 0,
  unhedged: 0,
  hedged: 0,
};

const defaultPnl: PnLState = {
  realized: 0,
  unrealized: 0,
  total: 0,
};

const defaultBankroll: BankrollState = {
  usd: 0,
  pct_used: 0,
  wallet: "",
};

// ─── Store ───

const MAX_TRADE_EVENTS = 200;

export const useBotStore = create<BotState & BotActions>((set) => ({
  // State
  connected: false,
  markets: [],
  exposure: defaultExposure,
  pnl: defaultPnl,
  bankroll: defaultBankroll,
  btc: null,
  config: null,
  meta: null,
  tradeEvents: [],
  trendRider: null,

  // Actions
  setConnected: (v) => set({ connected: v }),

  updateFromSnapshot: (snap) =>
    set({
      markets: snap.markets,
      exposure: snap.exposure,
      pnl: snap.pnl,
      bankroll: snap.bankroll,
      btc: snap.btc,
      config: snap.config,
      meta: snap.meta,
      trendRider: snap.trend_rider ?? null,
    }),

  updateTick: (tick) =>
    set((state) => ({
      markets: tick.data.markets,
      exposure: tick.data.exposure,
      pnl: tick.data.pnl,
      bankroll: tick.data.bankroll,
      trendRider: tick.data.trend_rider ?? state.trendRider,
    })),

  updateBtc: (btc) => set({ btc }),

  addTradeEvent: (evt) =>
    set((state) => ({
      tradeEvents: [evt, ...state.tradeEvents].slice(0, MAX_TRADE_EVENTS),
    })),
}));
