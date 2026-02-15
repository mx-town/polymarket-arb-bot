"use client";

import { useBotStore } from "@/stores/bot-store";
import { cn } from "@/lib/format";

interface FunnelStage {
  label: string;
  count: number;
  color: string;
}

export function PipelineFunnel() {
  const markets = useBotStore((s) => s.markets);
  const tradeEvents = useBotStore((s) => s.tradeEvents);
  const trendRider = useBotStore((s) => s.trendRider);

  const totalMarkets = markets.length;
  const withPosition = markets.filter((m) => m.position !== null).length;
  const hedged = markets.filter(
    (m) =>
      m.position !== null &&
      m.position.hedged > 0 &&
      m.position.up_shares > 0 &&
      m.position.down_shares > 0,
  ).length;
  const merges = tradeEvents.filter((e) => e.type === "merge_complete").length;

  const csStages: FunnelStage[] = [
    { label: "Discovered", count: totalMarkets, color: "bg-accent-blue" },
    { label: "Entered", count: withPosition, color: "bg-accent-green" },
    { label: "Hedged", count: hedged, color: "bg-accent-orange" },
    { label: "Merged", count: merges, color: "bg-accent-purple" },
  ];

  const trEntries = tradeEvents.filter(
    (e) => e.data.strategy === "trend_rider" && e.type === "order_placed",
  ).length;
  const trFills = tradeEvents.filter(
    (e) => e.data.strategy === "trend_rider" && e.type === "order_filled" && e.data.side === "BUY",
  ).length;
  const trHolding = trendRider?.meta.position_count ?? 0;

  const trStages: FunnelStage[] = trendRider?.config.enabled
    ? [
        { label: "TR Signal", count: trEntries, color: "bg-accent-orange" },
        { label: "TR Filled", count: trFills, color: "bg-accent-green" },
        { label: "TR Holding", count: trHolding, color: "bg-accent-blue" },
      ]
    : [];

  const stages = [...csStages, ...trStages];

  const maxCount = Math.max(1, ...stages.map((s) => s.count));

  return (
    <div className="rounded-lg border border-border-primary bg-bg-secondary p-4">
      <h3 className="mb-3 text-sm font-medium text-text-secondary">
        Pipeline
      </h3>
      <div className="space-y-2">
        {stages.map((stage) => {
          const widthPct = Math.max(8, (stage.count / maxCount) * 100);
          return (
            <div key={stage.label} className="flex items-center gap-3">
              <span className="w-20 text-xs text-text-muted">
                {stage.label}
              </span>
              <div className="flex-1">
                <div
                  className={cn(
                    "h-6 rounded-sm transition-all duration-300",
                    stage.color,
                  )}
                  style={{ width: `${widthPct}%`, opacity: 0.85 }}
                />
              </div>
              <span className="w-8 text-right font-mono text-sm text-text-primary">
                {stage.count}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
