"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useBotStore } from "@/stores/bot-store";
import { useWebSocket } from "@/hooks/use-websocket";
import { cn, formatPrice, formatPct, formatShares, formatUsd } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";
import { CountdownTimer } from "@/components/ui/CountdownTimer";
import { ChartContainer } from "@/components/charts/chart-container";
import { LazyMarketProbabilityChart, LazyMarketBtcChart } from "@/components/charts/lazy-charts";

type ChartMode = "probability" | "btc";

export default function MarketDetailPage() {
  useWebSocket();

  const params = useParams<{ slug: string }>();
  const slug = decodeURIComponent(params.slug);

  const market = useBotStore((s) => s.markets.find((m) => m.slug === slug));
  const allTradeEvents = useBotStore((s) => s.tradeEvents);
  const tradeEvents = useMemo(
    () => allTradeEvents.filter((e) => (e.data?.slug ?? e.slug) === slug),
    [allTradeEvents, slug],
  );

  const [chartMode, setChartMode] = useState<ChartMode>("probability");

  if (!market) {
    return (
      <div className="space-y-4">
        <Link
          href="/markets"
          className="inline-flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary transition-colors"
        >
          &larr; Back to Markets
        </Link>
        <div className="flex h-64 items-center justify-center rounded-lg border border-border-primary bg-bg-secondary">
          <div className="text-center">
            <p className="text-sm font-medium text-text-secondary">Market not found</p>
            <p className="mt-1 text-xs text-text-muted">
              {slug} is not currently active
            </p>
          </div>
        </div>
      </div>
    );
  }

  const pos = market.position;
  const upPct = market.up_ask !== null ? (market.up_ask * 100).toFixed(0) : "--";
  const downPct = market.down_ask !== null ? (market.down_ask * 100).toFixed(0) : "--";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-4">
          <Link
            href="/markets"
            className="inline-flex items-center gap-1 text-sm text-text-secondary hover:text-text-primary transition-colors"
          >
            &larr; Back
          </Link>
          <div>
            <h1 className="text-lg font-semibold text-text-primary">{slug}</h1>
            <div className="mt-1 flex items-center gap-3">
              <CountdownTimer seconds_to_end={market.seconds_to_end} />
              {market.edge !== null && (
                <Badge variant={market.edge > 0.03 ? "success" : "info"}>
                  Edge {formatPct(market.edge)}
                </Badge>
              )}
            </div>
          </div>
        </div>

        {/* Probability summary */}
        <div className="flex items-center gap-4">
          <div className="text-right">
            <span className="text-xs text-text-muted">UP</span>
            <p className="font-mono text-lg font-semibold text-accent-green">{upPct}%</p>
          </div>
          <div className="text-right">
            <span className="text-xs text-text-muted">DOWN</span>
            <p className="font-mono text-lg font-semibold text-accent-red">{downPct}%</p>
          </div>
        </div>
      </div>

      {/* Chart */}
      <ChartContainer
        title={chartMode === "probability" ? "Probability" : "BTC/USD"}
        height={400}
        toolbar={
          <div className="flex gap-1">
            <button
              type="button"
              onClick={() => setChartMode("probability")}
              className={cn(
                "rounded px-2 py-1 text-xs font-medium transition-colors",
                chartMode === "probability"
                  ? "bg-accent-blue/20 text-accent-blue"
                  : "text-text-muted hover:text-text-secondary",
              )}
            >
              Prob
            </button>
            <button
              type="button"
              onClick={() => setChartMode("btc")}
              className={cn(
                "rounded px-2 py-1 text-xs font-medium transition-colors",
                chartMode === "btc"
                  ? "bg-accent-yellow/20 text-accent-yellow"
                  : "text-text-muted hover:text-text-secondary",
              )}
            >
              BTC
            </button>
          </div>
        }
      >
        {chartMode === "probability" ? (
          <LazyMarketProbabilityChart slug={slug} />
        ) : (
          <LazyMarketBtcChart slug={slug} />
        )}
      </ChartContainer>

      {/* Info panels */}
      <div className="grid gap-4 md:grid-cols-3">
        {/* Position */}
        <div className="rounded-lg border border-border-primary bg-bg-secondary p-5">
          <p className="mb-3 text-xs font-medium uppercase tracking-wider text-text-muted">
            Position
          </p>
          {pos ? (
            <div className="space-y-3">
              <div className="flex justify-between">
                <span className="text-xs text-text-secondary">UP Shares</span>
                <span className="font-mono text-sm text-text-primary">
                  {formatShares(pos.up_shares)}
                </span>
              </div>
              {pos.up_vwap !== null && (
                <div className="flex justify-between">
                  <span className="text-xs text-text-secondary">UP VWAP</span>
                  <span className="font-mono text-sm text-accent-green">
                    {formatPrice(pos.up_vwap)}
                  </span>
                </div>
              )}
              <div className="flex justify-between">
                <span className="text-xs text-text-secondary">DOWN Shares</span>
                <span className="font-mono text-sm text-text-primary">
                  {formatShares(pos.down_shares)}
                </span>
              </div>
              {pos.down_vwap !== null && (
                <div className="flex justify-between">
                  <span className="text-xs text-text-secondary">DOWN VWAP</span>
                  <span className="font-mono text-sm text-accent-red">
                    {formatPrice(pos.down_vwap)}
                  </span>
                </div>
              )}
              <div className="border-t border-border-secondary pt-2">
                <div className="flex justify-between">
                  <span className="text-xs text-text-secondary">Hedged</span>
                  <span className="font-mono text-sm text-text-primary">
                    {formatShares(pos.hedged)}
                  </span>
                </div>
                <div className="flex justify-between mt-1">
                  <span className="text-xs text-text-secondary">uPnL</span>
                  <span
                    className={cn(
                      "font-mono text-sm font-semibold",
                      pos.unrealized_pnl >= 0 ? "text-profit" : "text-loss",
                    )}
                  >
                    {formatUsd(pos.unrealized_pnl)}
                  </span>
                </div>
              </div>
            </div>
          ) : (
            <p className="text-xs text-text-muted">No position</p>
          )}
        </div>

        {/* Orders */}
        <div className="rounded-lg border border-border-primary bg-bg-secondary p-5">
          <p className="mb-3 text-xs font-medium uppercase tracking-wider text-text-muted">
            Open Orders
          </p>
          {market.orders && market.orders.length > 0 ? (
            <div className="space-y-2">
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
          ) : (
            <p className="text-xs text-text-muted">No open orders</p>
          )}
        </div>

        {/* Trade Events */}
        <div className="rounded-lg border border-border-primary bg-bg-secondary p-5">
          <p className="mb-3 text-xs font-medium uppercase tracking-wider text-text-muted">
            Trade Events ({tradeEvents.length})
          </p>
          {tradeEvents.length > 0 ? (
            <div className="max-h-64 space-y-2 overflow-y-auto">
              {tradeEvents.map((evt, idx) => (
                <div
                  key={idx}
                  className="flex items-start justify-between border-b border-border-secondary pb-2 last:border-0"
                >
                  <div>
                    <Badge
                      variant={
                        evt.type.includes("merge")
                          ? "info"
                          : evt.type.includes("hedge")
                            ? "warning"
                            : evt.type.includes("fill")
                              ? "success"
                              : "neutral"
                      }
                    >
                      {evt.type.replace(/_/g, " ").toUpperCase()}
                    </Badge>
                    {evt.data?.direction && (
                      <span
                        className={cn(
                          "ml-2 text-xs font-mono",
                          evt.data.direction === "UP"
                            ? "text-accent-green"
                            : "text-accent-red",
                        )}
                      >
                        {evt.data.direction}
                      </span>
                    )}
                  </div>
                  <div className="text-right">
                    {evt.data?.price != null && (
                      <p className="font-mono text-xs text-text-primary">
                        @{formatPrice(evt.data.price)}
                      </p>
                    )}
                    {evt.data?.shares != null && (
                      <p className="text-xs text-text-muted">
                        {evt.data.shares.toFixed(1)} shares
                      </p>
                    )}
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <p className="text-xs text-text-muted">No events yet</p>
          )}
        </div>
      </div>
    </div>
  );
}
