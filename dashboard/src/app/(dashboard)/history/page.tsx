"use client";

import { useState } from "react";
import { cn } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";

// ─── Tab definitions ───

const tabs = ["Trades", "PnL", "Sessions"] as const;
type Tab = (typeof tabs)[number];

// ─── Mock trade data ───

const mockTrades = [
  {
    id: "1",
    ts: "2026-02-15 14:32:08",
    market: "btc-15m-2026-02-15-1430",
    event: "BUY",
    direction: "UP" as const,
    price: 0.45,
    shares: 11.75,
  },
  {
    id: "2",
    ts: "2026-02-15 14:33:12",
    market: "btc-15m-2026-02-15-1430",
    event: "BUY",
    direction: "DOWN" as const,
    price: 0.48,
    shares: 11.0,
  },
  {
    id: "3",
    ts: "2026-02-15 14:44:30",
    market: "btc-15m-2026-02-15-1430",
    event: "MERGE",
    direction: "UP" as const,
    price: 1.0,
    shares: 11.0,
  },
  {
    id: "4",
    ts: "2026-02-15 15:02:15",
    market: "btc-15m-2026-02-15-1500",
    event: "BUY",
    direction: "UP" as const,
    price: 0.42,
    shares: 12.5,
  },
  {
    id: "5",
    ts: "2026-02-15 15:04:45",
    market: "btc-15m-2026-02-15-1500",
    event: "BUY",
    direction: "DOWN" as const,
    price: 0.51,
    shares: 10.25,
  },
];

// ─── Trades tab ───

function TradesTab() {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border-secondary text-xs font-medium uppercase tracking-wider text-text-muted">
            <th className="pb-3 pr-4">Timestamp</th>
            <th className="pb-3 pr-4">Market</th>
            <th className="pb-3 pr-4">Event</th>
            <th className="pb-3 pr-4">Direction</th>
            <th className="pb-3 pr-4 text-right">Price</th>
            <th className="pb-3 text-right">Shares</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border-secondary">
          {mockTrades.map((trade) => (
            <tr key={trade.id} className="hover:bg-bg-tertiary transition-colors">
              <td className="py-3 pr-4 font-mono text-text-secondary">
                {trade.ts}
              </td>
              <td className="py-3 pr-4 text-text-primary">
                <span className="truncate max-w-[180px] inline-block">
                  {trade.market}
                </span>
              </td>
              <td className="py-3 pr-4">
                <Badge
                  variant={
                    trade.event === "MERGE"
                      ? "info"
                      : trade.event === "BUY"
                        ? "success"
                        : "danger"
                  }
                >
                  {trade.event}
                </Badge>
              </td>
              <td className="py-3 pr-4">
                <span
                  className={cn(
                    "font-mono text-sm font-medium",
                    trade.direction === "UP"
                      ? "text-accent-green"
                      : "text-accent-red",
                  )}
                >
                  {trade.direction}
                </span>
              </td>
              <td className="py-3 pr-4 text-right font-mono text-text-primary">
                {trade.price.toFixed(2)}
              </td>
              <td className="py-3 text-right font-mono text-text-primary">
                {trade.shares.toFixed(2)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── PnL tab ───

function PnLTab() {
  return (
    <div className="space-y-4">
      {/* Chart placeholder */}
      <div className="flex h-64 items-center justify-center rounded-lg border border-border-secondary bg-bg-primary">
        <div className="text-center">
          <p className="text-sm font-medium text-text-secondary">
            PnL Chart
          </p>
          <p className="mt-1 text-xs text-text-muted">
            Cumulative PnL over time will render here once TanStack Query is
            wired
          </p>
        </div>
      </div>

      {/* Summary placeholders */}
      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-lg border border-border-secondary bg-bg-primary p-4 text-center">
          <p className="text-xs text-text-muted">Today</p>
          <p className="mt-1 font-mono text-lg font-semibold text-text-muted">
            --
          </p>
        </div>
        <div className="rounded-lg border border-border-secondary bg-bg-primary p-4 text-center">
          <p className="text-xs text-text-muted">This Week</p>
          <p className="mt-1 font-mono text-lg font-semibold text-text-muted">
            --
          </p>
        </div>
        <div className="rounded-lg border border-border-secondary bg-bg-primary p-4 text-center">
          <p className="text-xs text-text-muted">All Time</p>
          <p className="mt-1 font-mono text-lg font-semibold text-text-muted">
            --
          </p>
        </div>
      </div>
    </div>
  );
}

// ─── Sessions tab ───

function SessionsTab() {
  return (
    <div>
      <table className="w-full text-left text-sm">
        <thead>
          <tr className="border-b border-border-secondary text-xs font-medium uppercase tracking-wider text-text-muted">
            <th className="pb-3 pr-4">Session</th>
            <th className="pb-3 pr-4">Started</th>
            <th className="pb-3 pr-4">Duration</th>
            <th className="pb-3 pr-4">Trades</th>
            <th className="pb-3 pr-4">Merges</th>
            <th className="pb-3 text-right">PnL</th>
          </tr>
        </thead>
        <tbody>
          <tr>
            <td
              colSpan={6}
              className="py-12 text-center text-sm text-text-muted"
            >
              No session history available yet. Session data will appear once
              the backend API is connected.
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

// ─── Main page ───

export default function HistoryPage() {
  const [activeTab, setActiveTab] = useState<Tab>("Trades");

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-text-primary">History</h1>
        <p className="mt-1 text-sm text-text-secondary">
          Trade history, performance, and session logs
        </p>
      </div>

      {/* Tab bar */}
      <div className="border-b border-border-primary">
        <div className="flex gap-0">
          {tabs.map((tab) => (
            <button
              key={tab}
              type="button"
              onClick={() => setActiveTab(tab)}
              className={cn(
                "relative px-4 py-2.5 text-sm font-medium transition-colors",
                activeTab === tab
                  ? "text-text-primary"
                  : "text-text-secondary hover:text-text-primary",
              )}
            >
              {tab}
              {activeTab === tab && (
                <span className="absolute inset-x-0 bottom-0 h-0.5 bg-accent-blue" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* Tab content */}
      <div className="rounded-lg border border-border-primary bg-bg-secondary p-6">
        {activeTab === "Trades" && <TradesTab />}
        {activeTab === "PnL" && <PnLTab />}
        {activeTab === "Sessions" && <SessionsTab />}
      </div>
    </div>
  );
}
