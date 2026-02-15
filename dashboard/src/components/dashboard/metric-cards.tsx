"use client";

import { useBotStore } from "@/stores/bot-store";
import { formatUsd, formatPct } from "@/lib/format";

function MetricCard({
  label,
  value,
  positive,
}: {
  label: string;
  value: string;
  positive?: boolean | null;
}) {
  const colorClass =
    positive === true
      ? "text-profit"
      : positive === false
        ? "text-loss"
        : "text-text-primary";

  return (
    <div className="rounded-lg border border-border-primary bg-bg-secondary p-4">
      <div className="text-xs text-text-muted mb-1">{label}</div>
      <div className={`font-mono text-xl font-bold ${colorClass}`}>{value}</div>
    </div>
  );
}

export function MetricCards() {
  const pnl = useBotStore((s) => s.pnl);
  const exposure = useBotStore((s) => s.exposure);
  const bankroll = useBotStore((s) => s.bankroll);

  const roi =
    bankroll.usd > 0 ? (pnl.total / bankroll.usd) * 100 : 0;

  return (
    <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
      <MetricCard
        label="Total PnL"
        value={formatUsd(pnl.total)}
        positive={pnl.total >= 0 ? true : false}
      />
      <MetricCard
        label="ROI"
        value={formatPct(roi)}
        positive={roi >= 0 ? true : false}
      />
      <MetricCard label="Exposure" value={formatUsd(exposure.total)} />
      <MetricCard
        label="Bankroll Used"
        value={formatPct(bankroll.pct_used)}
        positive={bankroll.pct_used < 80 ? true : bankroll.pct_used < 95 ? null : false}
      />
    </div>
  );
}
