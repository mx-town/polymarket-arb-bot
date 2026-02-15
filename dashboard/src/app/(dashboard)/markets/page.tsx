"use client";

import Link from "next/link";
import { useBotStore } from "@/stores/bot-store";
import { useWebSocket } from "@/hooks/use-websocket";
import { cn, formatPrice, formatPct, formatShares, formatUsd } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";
import { CountdownTimer } from "@/components/ui/CountdownTimer";
import type { MarketState } from "@/lib/types";

function MarketCard({ market, strategy }: { market: MarketState; strategy?: "CS" | "TR" }) {
  const pos = market.position;

  // Determine position status
  let posStatus: "none" | "one-leg" | "hedged" = "none";
  if (pos) {
    const hasUp = pos.up_shares > 0;
    const hasDown = pos.down_shares > 0;
    if (hasUp && hasDown) posStatus = "hedged";
    else if (hasUp || hasDown) posStatus = "one-leg";
  }

  return (
    <div className="rounded-lg border border-border-primary bg-bg-secondary transition-colors hover:border-accent-blue/40">
      {/* Header */}
      <div className="flex items-start justify-between border-b border-border-secondary px-5 py-4">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-text-primary">
            {market.slug}
          </p>
          <div className="mt-1 flex items-center gap-3">
            <CountdownTimer seconds_to_end={market.seconds_to_end} />
            {market.edge !== null && (
              <Badge variant={market.edge > 0.03 ? "success" : "info"}>
                Edge {formatPct(market.edge)}
              </Badge>
            )}
          </div>
        </div>
        {strategy && (
          <Badge variant={strategy === "CS" ? "info" : "warning"}>
            {strategy}
          </Badge>
        )}
        <Badge
          variant={
            posStatus === "hedged"
              ? "success"
              : posStatus === "one-leg"
                ? "warning"
                : "neutral"
          }
        >
          {posStatus === "hedged"
            ? "Hedged"
            : posStatus === "one-leg"
              ? "One Leg"
              : "Watching"}
        </Badge>
      </div>

      {/* Probabilities grid */}
      <div className="grid grid-cols-2 divide-x divide-border-secondary border-b border-border-secondary">
        {/* UP side */}
        <div className="px-5 py-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-text-muted">
            UP
          </p>
          <div className="space-y-1">
            <div className="flex justify-between">
              <span className="text-xs text-text-secondary">Bid</span>
              <span className="font-mono text-sm text-accent-green">
                {market.up_bid !== null ? formatPrice(market.up_bid) : "--"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-xs text-text-secondary">Ask</span>
              <span className="font-mono text-sm text-accent-green">
                {market.up_ask !== null ? formatPrice(market.up_ask) : "--"}
              </span>
            </div>
          </div>
        </div>

        {/* DOWN side */}
        <div className="px-5 py-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-text-muted">
            DOWN
          </p>
          <div className="space-y-1">
            <div className="flex justify-between">
              <span className="text-xs text-text-secondary">Bid</span>
              <span className="font-mono text-sm text-accent-red">
                {market.down_bid !== null ? formatPrice(market.down_bid) : "--"}
              </span>
            </div>
            <div className="flex justify-between">
              <span className="text-xs text-text-secondary">Ask</span>
              <span className="font-mono text-sm text-accent-red">
                {market.down_ask !== null ? formatPrice(market.down_ask) : "--"}
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Position summary (if any) */}
      {pos && (
        <div className="px-5 py-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-text-muted">
            Position
          </p>
          <div className="grid grid-cols-3 gap-3">
            <div>
              <p className="text-xs text-text-secondary">UP Shares</p>
              <p className="font-mono text-sm text-text-primary">
                {formatShares(pos.up_shares)}
              </p>
              {pos.up_vwap !== null && (
                <p className="text-xs text-text-muted">
                  VWAP {formatPrice(pos.up_vwap)}
                </p>
              )}
            </div>
            <div>
              <p className="text-xs text-text-secondary">DOWN Shares</p>
              <p className="font-mono text-sm text-text-primary">
                {formatShares(pos.down_shares)}
              </p>
              {pos.down_vwap !== null && (
                <p className="text-xs text-text-muted">
                  VWAP {formatPrice(pos.down_vwap)}
                </p>
              )}
            </div>
            <div>
              <p className="text-xs text-text-secondary">uPnL</p>
              <p
                className={cn(
                  "font-mono text-sm font-semibold",
                  pos.unrealized_pnl >= 0 ? "text-profit" : "text-loss",
                )}
              >
                {formatUsd(pos.unrealized_pnl)}
              </p>
              <p className="text-xs text-text-muted">
                Hedged {formatShares(pos.hedged)}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Orders (if any) */}
      {market.orders && market.orders.length > 0 && (
        <div className="border-t border-border-secondary px-5 py-3">
          <p className="mb-2 text-xs font-medium uppercase tracking-wider text-text-muted">
            Open Orders ({market.orders.length})
          </p>
          <div className="space-y-1">
            {market.orders.map((order, idx) => (
              <div
                key={idx}
                className="flex items-center justify-between text-xs"
              >
                <span className="text-text-secondary">
                  {order.side}{" "}
                  <span
                    className={cn(
                      order.direction === "UP"
                        ? "text-accent-green"
                        : "text-accent-red",
                    )}
                  >
                    {order.direction ?? "?"}
                  </span>
                </span>
                <span className="font-mono text-text-primary">
                  {formatPrice(order.price)} x {order.size.toFixed(1)}
                </span>
                <span className="text-text-muted">
                  filled {order.matched.toFixed(1)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function MarketsPage() {
  useWebSocket();

  const markets = useBotStore((s) => s.markets);
  const connected = useBotStore((s) => s.connected);
  const trendRider = useBotStore((s) => s.trendRider);

  const trSlugs = new Set(trendRider?.positions.map((p) => p.slug) ?? []);

  if (!connected) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <div className="text-center">
          <div className="mx-auto mb-4 h-3 w-3 animate-pulse rounded-full bg-accent-yellow" />
          <p className="text-sm text-text-secondary">
            Connecting to bot...
          </p>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Markets</h1>
          <p className="mt-1 text-sm text-text-secondary">
            All active 15-minute crypto markets
          </p>
        </div>
        <Badge variant="info">{markets.length} active</Badge>
      </div>

      {markets.length === 0 ? (
        <div className="flex h-64 items-center justify-center rounded-lg border border-border-primary bg-bg-secondary">
          <div className="text-center">
            <p className="text-sm font-medium text-text-secondary">
              No active markets
            </p>
            <p className="mt-1 text-xs text-text-muted">
              Markets will appear here when the bot discovers them
            </p>
          </div>
        </div>
      ) : (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          {markets.map((market) => (
            <Link key={market.slug} href={`/markets/${encodeURIComponent(market.slug)}`} className="block">
              <MarketCard market={market} strategy={trSlugs.has(market.slug) ? "TR" : market.position ? "CS" : undefined} />
            </Link>
          ))}
        </div>
      )}
    </div>
  );
}
