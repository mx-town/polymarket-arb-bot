"use client";

import { useWebSocket } from "@/hooks/use-websocket";
import { useBotStore } from "@/stores/bot-store";
import { MetricCard } from "@/components/ui/MetricCard";
import { Badge } from "@/components/ui/Badge";
import { CountdownTimer } from "@/components/ui/CountdownTimer";
import {
  formatUsd,
  formatPct,
  formatPrice,
  formatShares,
  cn,
} from "@/lib/format";

export default function OverviewPage() {
  useWebSocket();

  const { connected, markets, exposure, pnl, bankroll } = useBotStore();

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

  const roi =
    bankroll.usd > 0 ? pnl.total / bankroll.usd : 0;
  const hedgeRate =
    exposure.total > 0 ? exposure.hedged / exposure.total : 0;

  const activePositions = markets.filter((m) => m.position !== null);

  return (
    <div className="space-y-6">
      {/* ─── Metric cards ─── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard
          label="Total PnL"
          value={formatUsd(pnl.total)}
          delta={`R: ${formatUsd(pnl.realized)} / U: ${formatUsd(pnl.unrealized)}`}
          deltaValue={pnl.total}
        />
        <MetricCard
          label="ROI"
          value={formatPct(roi)}
          deltaValue={roi}
        />
        <MetricCard
          label="Exposure"
          value={formatUsd(exposure.total)}
          delta={`${formatPct(bankroll.pct_used)} of bankroll`}
        />
        <MetricCard
          label="Hedge Rate"
          value={formatPct(hedgeRate)}
          delta={`${formatUsd(exposure.hedged)} hedged`}
          deltaValue={hedgeRate - 0.5}
        />
      </div>

      {/* ─── Chart placeholder ─── */}
      <div className="rounded-lg border border-border-primary bg-bg-secondary p-6">
        <h2 className="mb-4 text-sm font-medium text-text-secondary">
          PnL Chart
        </h2>
        <div className="flex h-64 items-center justify-center rounded border border-border-secondary bg-bg-primary">
          <span className="text-sm text-text-muted">
            Chart will render here
          </span>
        </div>
      </div>

      {/* ─── Active positions ─── */}
      <div className="rounded-lg border border-border-primary bg-bg-secondary">
        <div className="border-b border-border-primary px-4 py-3">
          <h2 className="text-sm font-medium text-text-secondary">
            Active Positions
            <span className="ml-2 text-text-muted">
              ({activePositions.length})
            </span>
          </h2>
        </div>

        {activePositions.length === 0 ? (
          <div className="flex h-32 items-center justify-center">
            <p className="text-sm text-text-muted">No active positions</p>
          </div>
        ) : (
          <div className="divide-y divide-border-secondary">
            {activePositions.map((m) => {
              const pos = m.position!;
              return (
                <div
                  key={m.slug}
                  className="flex items-center gap-4 px-4 py-3"
                >
                  {/* Market slug + countdown */}
                  <div className="min-w-0 flex-1">
                    <p className="truncate text-sm font-medium text-text-primary">
                      {m.slug}
                    </p>
                    <CountdownTimer seconds_to_end={m.seconds_to_end} />
                  </div>

                  {/* Shares */}
                  <div className="text-right">
                    <p className="text-xs text-text-muted">UP / DOWN</p>
                    <p className="font-mono text-sm text-text-primary">
                      {formatShares(pos.up_shares)} / {formatShares(pos.down_shares)}
                    </p>
                  </div>

                  {/* Edge */}
                  <div className="text-right">
                    <p className="text-xs text-text-muted">Edge</p>
                    <p className="font-mono text-sm text-text-primary">
                      {m.edge !== null ? formatPct(m.edge) : "--"}
                    </p>
                  </div>

                  {/* Unrealized PnL */}
                  <div className="w-20 text-right">
                    <p className="text-xs text-text-muted">uPnL</p>
                    <p
                      className={cn(
                        "font-mono text-sm font-semibold",
                        pos.unrealized_pnl >= 0 ? "text-profit" : "text-loss",
                      )}
                    >
                      {formatUsd(pos.unrealized_pnl)}
                    </p>
                  </div>

                  {/* Hedge badge */}
                  <Badge
                    variant={
                      pos.hedged >= pos.up_shares && pos.hedged >= pos.down_shares
                        ? "success"
                        : pos.hedged > 0
                          ? "warning"
                          : "danger"
                    }
                  >
                    {pos.hedged > 0 ? "Hedged" : "Unhedged"}
                  </Badge>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
