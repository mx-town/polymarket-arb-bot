"use client";

import { useBotStore } from "@/stores/bot-store";
import { formatPrice, formatCountdown } from "@/lib/format";
import type { MarketState } from "@/lib/types";

function MarketTile({ market }: { market: MarketState }) {
  const secondsLeft = market.seconds_to_end;
  const isUrgent = secondsLeft < 60;
  const isWarning = secondsLeft < 120;

  const upPct = market.up_ask !== null ? (market.up_ask * 100).toFixed(0) : "–";
  const downPct =
    market.down_ask !== null ? (market.down_ask * 100).toFixed(0) : "–";

  // Determine position status
  let status = "watching";
  if (market.position) {
    const hasUp = market.position.up_shares > 0;
    const hasDown = market.position.down_shares > 0;
    if (hasUp && hasDown) status = "hedged";
    else if (hasUp || hasDown) status = "one-leg";
  }

  return (
    <div className="rounded-lg border border-border-secondary bg-bg-primary p-3 hover:bg-bg-tertiary transition-colors">
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs text-text-muted truncate max-w-[160px]">
          {market.slug.split("-").slice(0, 3).join("-")}
        </span>
        <span
          className={`font-mono text-xs ${isUrgent ? "text-accent-red" : isWarning ? "text-accent-yellow" : "text-text-secondary"}`}
        >
          {formatCountdown(secondsLeft)}
        </span>
      </div>

      <div className="flex items-center gap-3 mb-2">
        <div className="flex-1">
          <div className="text-xs text-text-muted mb-0.5">UP</div>
          <div className="font-mono text-sm text-accent-green">{upPct}%</div>
        </div>
        <div className="flex-1">
          <div className="text-xs text-text-muted mb-0.5">DOWN</div>
          <div className="font-mono text-sm text-accent-red">{downPct}%</div>
        </div>
        {market.edge !== null && (
          <div className="flex-1">
            <div className="text-xs text-text-muted mb-0.5">Edge</div>
            <div className="font-mono text-sm text-accent-blue">
              {(market.edge * 100).toFixed(1)}%
            </div>
          </div>
        )}
      </div>

      {market.position && (
        <div className="text-xs text-text-muted border-t border-border-secondary pt-1.5 mt-1.5">
          <span className="text-accent-green">
            U{market.position.up_shares.toFixed(0)}
          </span>
          <span className="mx-1">/</span>
          <span className="text-accent-red">
            D{market.position.down_shares.toFixed(0)}
          </span>
          <span className="ml-2">
            h{market.position.hedged.toFixed(0)}
          </span>
        </div>
      )}
    </div>
  );
}

export function MarketSidebar() {
  const markets = useBotStore((s) => s.markets);

  return (
    <div className="space-y-2">
      <h3 className="text-xs font-medium text-text-muted uppercase tracking-wider px-1">
        Active Markets
      </h3>
      {markets.length === 0 ? (
        <div className="text-sm text-text-muted px-1">No active markets</div>
      ) : (
        markets.map((market) => (
          <MarketTile key={market.slug} market={market} />
        ))
      )}
    </div>
  );
}
