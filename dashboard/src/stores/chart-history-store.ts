import { create } from "zustand";

const WINDOW_SEC = 10_800; // 3 hours

interface ProbPoint {
  time: number; // UTCTimestamp (unix seconds)
  up_ask: number;
  down_ask: number;
}

interface BtcPoint {
  time: number; // UTCTimestamp (unix seconds)
  price: number;
  open: number;
}

interface ChartHistoryState {
  probSeries: Record<string, ProbPoint[]>;
  btcSeries: BtcPoint[];

  pushMarketTick: (slug: string, upAsk: number | null, downAsk: number | null) => void;
  pushBtcTick: (price: number, open: number) => void;
}

export type { ProbPoint, BtcPoint };

export const useChartHistoryStore = create<ChartHistoryState>((set) => ({
  probSeries: {},
  btcSeries: [],

  pushMarketTick: (slug, upAsk, downAsk) =>
    set((state) => {
      if (upAsk === null && downAsk === null) return state;

      const now = Math.floor(Date.now() / 1000);
      const cutoff = now - WINDOW_SEC;
      const existing = state.probSeries[slug] ?? [];

      const point: ProbPoint = {
        time: now,
        up_ask: upAsk ?? 0,
        down_ask: downAsk ?? 0,
      };

      // Dedup: overwrite if last point has same timestamp
      let updated: ProbPoint[];
      if (existing.length > 0 && existing[existing.length - 1].time === now) {
        updated = [...existing.slice(0, -1), point];
      } else {
        updated = [...existing, point];
      }

      // Trim to rolling window
      const trimmed = updated.filter((p) => p.time > cutoff);

      // Prune empty series from other slugs while we're here
      const next: Record<string, ProbPoint[]> = {};
      for (const [k, v] of Object.entries(state.probSeries)) {
        if (k === slug) continue;
        const filtered = v.filter((p) => p.time > cutoff);
        if (filtered.length > 0) next[k] = filtered;
      }
      if (trimmed.length > 0) next[slug] = trimmed;

      return { probSeries: next };
    }),

  pushBtcTick: (price, open) =>
    set((state) => {
      const now = Math.floor(Date.now() / 1000);
      const cutoff = now - WINDOW_SEC;
      const point: BtcPoint = { time: now, price, open };

      // Dedup: overwrite if last point has same timestamp
      let updated: BtcPoint[];
      if (state.btcSeries.length > 0 && state.btcSeries[state.btcSeries.length - 1].time === now) {
        updated = [...state.btcSeries.slice(0, -1), point];
      } else {
        updated = [...state.btcSeries, point];
      }

      return { btcSeries: updated.filter((p) => p.time > cutoff) };
    }),
}));
