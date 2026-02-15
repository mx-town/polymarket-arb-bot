"use client";

import { useBotStore } from "@/stores/bot-store";
import type { TradeEvent } from "@/lib/types";

const EVENT_COLORS: Record<string, string> = {
  order_placed: "text-accent-blue",
  order_filled: "text-accent-green",
  hedge_complete: "text-accent-orange",
  merge_complete: "text-accent-purple",
  order_cancelled: "text-text-muted",
};

const EVENT_LABELS: Record<string, string> = {
  order_placed: "PLACED",
  order_filled: "FILLED",
  hedge_complete: "HEDGED",
  merge_complete: "MERGED",
  order_cancelled: "CANCEL",
};

function TradeRow({ event }: { event: TradeEvent }) {
  const color = EVENT_COLORS[event.type] || "text-text-secondary";
  const label = EVENT_LABELS[event.type] || event.type.toUpperCase();
  const time = new Date(event.ts * 1000).toLocaleTimeString([], {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });

  return (
    <div className="flex items-center gap-2 px-2 py-1.5 text-xs border-b border-border-secondary last:border-0">
      <span className="font-mono text-text-muted w-16">{time}</span>
      <span className={`font-semibold w-14 ${color}`}>{label}</span>
      <span className="text-text-secondary truncate flex-1">
        {event.data.direction && (
          <span
            className={
              event.data.direction === "UP"
                ? "text-accent-green"
                : "text-accent-red"
            }
          >
            {event.data.direction}
          </span>
        )}
        {event.data.price && (
          <span className="ml-1 font-mono">@{event.data.price.toFixed(2)}</span>
        )}
        {event.data.shares && (
          <span className="ml-1 font-mono">×{event.data.shares.toFixed(0)}</span>
        )}
      </span>
    </div>
  );
}

export function TradeFeed() {
  const tradeEvents = useBotStore((s) => s.tradeEvents);
  const recent = tradeEvents.slice(-20).reverse();

  return (
    <div className="rounded-lg border border-border-primary bg-bg-secondary">
      <div className="px-3 py-2 border-b border-border-secondary">
        <h3 className="text-xs font-medium text-text-muted uppercase tracking-wider">
          Trade Feed
        </h3>
      </div>
      <div className="max-h-[300px] overflow-y-auto">
        {recent.length === 0 ? (
          <div className="p-4 text-sm text-text-muted text-center">
            No trades yet
          </div>
        ) : (
          recent.map((event, i) => <TradeRow key={`${event.ts}-${i}`} event={event} />)
        )}
      </div>
    </div>
  );
}
