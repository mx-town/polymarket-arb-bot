import type { StateSnapshot } from "@/lib/types";

const BASE_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function apiFetch<T>(path: string, params?: Record<string, string>): Promise<T> {
  const url = new URL(path, BASE_URL);
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      url.searchParams.set(k, v);
    }
  }
  const res = await fetch(url.toString());
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${res.statusText} — ${path}`);
  }
  return res.json() as Promise<T>;
}

/** Fetch full bot state snapshot */
export function fetchState(): Promise<StateSnapshot> {
  return apiFetch<StateSnapshot>("/api/v1/state");
}

/** Fetch BTC price history */
export function fetchBtcHistory(
  params?: Record<string, string>,
): Promise<{ ts: number; price: number }[]> {
  return apiFetch("/api/v1/btc/history", params);
}

/** Fetch probability history for a market */
export function fetchProbabilityHistory(
  params?: Record<string, string>,
): Promise<{ ts: number; up: number; down: number }[]> {
  return apiFetch("/api/v1/probability/history", params);
}

/** Fetch trade log */
export function fetchTrades(
  params?: Record<string, string>,
): Promise<{ ts: number; slug: string; side: string; price: number; shares: number }[]> {
  return apiFetch("/api/v1/trades", params);
}

/** Fetch PnL time-series */
export function fetchPnlHistory(
  params?: Record<string, string>,
): Promise<{ ts: number; realized: number; unrealized: number; total: number }[]> {
  return apiFetch("/api/v1/pnl/history", params);
}
