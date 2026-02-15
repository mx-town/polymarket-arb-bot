"use client";

import { useEffect, useMemo } from "react";
import { useWebSocket } from "@/hooks/use-websocket";
import { useBotStore } from "@/stores/bot-store";
import { useSessionStore } from "@/stores/session-store";
import { MetricCard } from "@/components/ui/MetricCard";
import { Badge } from "@/components/ui/Badge";
import { CountdownTimer } from "@/components/ui/CountdownTimer";
import {
  formatUsd,
  formatPct,
  formatPrice,
  formatShares,
  formatCountdown,
  cn,
} from "@/lib/format";

export default function OverviewPage() {
  useWebSocket();

  const { connected, markets, exposure, pnl, bankroll, trendRider } = useBotStore();
  const sessionMode = useSessionStore((s) => s.mode);
  const replayData = useSessionStore((s) => s.replayData);
  const activeSessionId = useSessionStore((s) => s.activeSessionId);

  // In replay mode, derive PnL and trade counts from replayData
  const replayPnl = useMemo(() => {
    if (!replayData?.pnl_curve?.length) return { realized: 0, unrealized: 0, total: 0 };
    const last = replayData.pnl_curve[replayData.pnl_curve.length - 1];
    return { realized: last.realized, unrealized: last.unrealized, total: last.total };
  }, [replayData]);

  const replayStats = useMemo(() => {
    if (!replayData) return { tradeCount: 0, mergeCount: 0, marketCount: 0 };
    return {
      tradeCount: replayData.trades.length,
      mergeCount: replayData.trades.filter((t) => t.event_type === "merge_complete").length,
      marketCount: replayData.market_windows.length,
    };
  }, [replayData]);

  const isReplay = sessionMode === "replay";
  const isLive = sessionMode === "live";

  if (isLive && !connected) {
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

  if (isReplay && !replayData) {
    return (
      <div className="flex h-[60vh] items-center justify-center">
        <p className="text-sm text-text-muted">No replay data loaded</p>
      </div>
    );
  }

  const displayPnl = isReplay ? replayPnl : pnl;
  const roi =
    isReplay
      ? 0 // Can't compute without bankroll in replay
      : bankroll.usd > 0 ? pnl.total / bankroll.usd : 0;
  const hedgeRate =
    exposure.total > 0 ? exposure.hedged / exposure.total : 0;

  const activePositions = isReplay
    ? []
    : markets.filter(
        (m) => m.position !== null && m.position?.up_shares !== undefined,
      );

  return (
    <div className="space-y-6">
      {/* ─── Replay banner ─── */}
      {isReplay && (
        <div className="flex items-center gap-3 rounded-lg border border-accent-blue/30 bg-accent-blue/5 px-4 py-3">
          <div className="h-2 w-2 rounded-full bg-accent-blue" />
          <span className="text-sm text-text-secondary">
            Replaying session{" "}
            <span className="font-mono font-medium text-text-primary">
              {activeSessionId}
            </span>
            {" \u00b7 "}
            {replayStats.tradeCount} trades, {replayStats.mergeCount} merges,{" "}
            {replayStats.marketCount} markets
          </span>
        </div>
      )}

      {/* ─── Metric cards ─── */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <MetricCard
          label="Total PnL"
          value={formatUsd(displayPnl.total)}
          delta={`R: ${formatUsd(displayPnl.realized)} / U: ${formatUsd(displayPnl.unrealized)}`}
          deltaValue={displayPnl.total}
        />
        {isReplay ? (
          <MetricCard
            label="Trades"
            value={String(replayStats.tradeCount)}
            delta={`${replayStats.mergeCount} merges`}
          />
        ) : (
          <MetricCard
            label="ROI"
            value={formatPct(roi)}
            deltaValue={roi}
          />
        )}
        {isReplay ? (
          <MetricCard
            label="Markets"
            value={String(replayStats.marketCount)}
            delta="windows tracked"
          />
        ) : (
          <MetricCard
            label="Exposure"
            value={formatUsd(exposure.total)}
            delta={`${formatPct(bankroll.pct_used)} of bankroll`}
          />
        )}
        {isReplay ? (
          <MetricCard
            label="PnL Points"
            value={String(replayData?.pnl_curve?.length ?? 0)}
            delta="data points"
          />
        ) : (
          <MetricCard
            label="Hedge Rate"
            value={formatPct(hedgeRate)}
            delta={`${formatUsd(exposure.hedged)} hedged`}
            deltaValue={hedgeRate - 0.5}
          />
        )}
      </div>

      {/* ─── Chart placeholder ─── */}
      <div className="rounded-lg border border-border-primary bg-bg-secondary p-6">
        <h2 className="mb-4 text-sm font-medium text-text-secondary">
          PnL Chart
        </h2>
        <div className="flex h-64 items-center justify-center rounded border border-border-secondary bg-bg-primary">
          <span className="text-sm text-text-muted">
            {isReplay
              ? `${replayData?.pnl_curve?.length ?? 0} PnL data points available`
              : "Chart will render here"}
          </span>
        </div>
      </div>

      {/* ─── Replay trade list ─── */}
      {isReplay && replayData && replayData.trades.length > 0 && (
        <div className="rounded-lg border border-border-primary bg-bg-secondary">
          <div className="border-b border-border-primary px-4 py-3">
            <h2 className="text-sm font-medium text-text-secondary">
              Session Trades
              <span className="ml-2 text-text-muted">
                ({replayData.trades.length})
              </span>
            </h2>
          </div>
          <div className="max-h-96 overflow-y-auto">
            <table className="w-full text-left text-sm">
              <thead className="sticky top-0 bg-bg-secondary">
                <tr className="border-b border-border-secondary text-xs font-medium uppercase tracking-wider text-text-muted">
                  <th className="px-4 pb-2 pt-3">Time</th>
                  <th className="px-4 pb-2 pt-3">Market</th>
                  <th className="px-4 pb-2 pt-3">Event</th>
                  <th className="px-4 pb-2 pt-3">Dir</th>
                  <th className="px-4 pb-2 pt-3 text-right">Price</th>
                  <th className="px-4 pb-2 pt-3 text-right">Shares</th>
                  <th className="px-4 pb-2 pt-3">Strategy</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border-secondary">
                {replayData.trades.slice(0, 200).map((t, i) => (
                  <tr key={i} className="hover:bg-bg-tertiary transition-colors">
                    <td className="px-4 py-2 font-mono text-xs text-text-secondary">
                      {new Date(t.ts * 1000).toLocaleTimeString("en-US", { hour12: false })}
                    </td>
                    <td className="px-4 py-2 text-text-primary max-w-[180px] truncate">
                      {t.market_slug}
                    </td>
                    <td className="px-4 py-2">
                      <Badge
                        variant={
                          t.event_type === "merge_complete"
                            ? "info"
                            : t.event_type === "order_filled"
                              ? "success"
                              : "warning"
                        }
                      >
                        {t.event_type}
                      </Badge>
                    </td>
                    <td className="px-4 py-2">
                      <span
                        className={cn(
                          "font-mono text-xs font-medium",
                          t.direction === "UP" ? "text-accent-green" : "text-accent-red",
                        )}
                      >
                        {t.direction}
                      </span>
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-text-primary">
                      {t.price?.toFixed(2) ?? "--"}
                    </td>
                    <td className="px-4 py-2 text-right font-mono text-text-primary">
                      {t.shares?.toFixed(2) ?? "--"}
                    </td>
                    <td className="px-4 py-2 text-xs text-text-muted">
                      {t.strategy}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* ─── Active positions (live mode only) ─── */}
      {!isReplay && (
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
      )}

      {/* ─── Trend Rider (live mode only) ─── */}
      {!isReplay && trendRider?.config.enabled && (
        <div className="space-y-4">
          <h2 className="text-sm font-medium text-text-secondary">
            Trend Rider
            {trendRider.config.dry_run && (
              <span className="ml-2 text-xs text-accent-yellow">(DRY RUN)</span>
            )}
          </h2>

          {/* TR metric cards */}
          <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
            <MetricCard
              label="TR PnL"
              value={formatUsd(trendRider.pnl.realized)}
              delta="Realized"
              deltaValue={trendRider.pnl.realized}
            />
            <MetricCard
              label="TR Exposure"
              value={formatUsd(trendRider.exposure)}
              delta={`$${trendRider.config.bankroll_usd.toFixed(0)} bankroll`}
            />
            <MetricCard
              label="TR Positions"
              value={String(trendRider.meta.position_count)}
              delta={`${trendRider.meta.tick_count} ticks`}
            />
            <MetricCard
              label="TR Tick"
              value={`${trendRider.meta.avg_tick_ms.toFixed(0)}ms`}
              delta="avg tick"
            />
          </div>

          {/* TR positions */}
          <div className="rounded-lg border border-border-primary bg-bg-secondary">
            <div className="border-b border-border-primary px-4 py-3">
              <h3 className="text-sm font-medium text-text-secondary">
                TR Positions
                <span className="ml-2 text-text-muted">
                  ({trendRider.positions.length})
                </span>
              </h3>
            </div>

            {trendRider.positions.length === 0 ? (
              <div className="flex h-24 items-center justify-center">
                <p className="text-sm text-text-muted">No TR positions</p>
              </div>
            ) : (
              <div className="divide-y divide-border-secondary">
                {trendRider.positions.map((pos) => (
                  <div
                    key={pos.slug}
                    className="flex items-center gap-4 px-4 py-3"
                  >
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium text-text-primary">
                        {pos.slug}
                      </p>
                      <p className="text-xs text-text-muted">
                        held {formatCountdown(pos.seconds_held)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-text-muted">Direction</p>
                      <p
                        className={cn(
                          "font-mono text-sm font-semibold",
                          pos.direction === "UP"
                            ? "text-accent-green"
                            : "text-accent-red",
                        )}
                      >
                        {pos.direction === "UP" ? "\u2191" : "\u2193"} {pos.direction}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-text-muted">Entry</p>
                      <p className="font-mono text-sm text-text-primary">
                        {formatPrice(pos.entry_price)}
                      </p>
                    </div>
                    <div className="text-right">
                      <p className="text-xs text-text-muted">Shares</p>
                      <p className="font-mono text-sm text-text-primary">
                        {formatShares(pos.shares)}
                      </p>
                    </div>
                    <div className="w-20 text-right">
                      <p className="text-xs text-text-muted">Cost</p>
                      <p className="font-mono text-sm text-text-primary">
                        {formatUsd(pos.cost)}
                      </p>
                    </div>
                    <Badge variant="success">Holding</Badge>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
