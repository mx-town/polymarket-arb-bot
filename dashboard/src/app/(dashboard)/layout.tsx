"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useBotStore } from "@/stores/bot-store";
import { cn, formatUsd, formatCountdown } from "@/lib/format";
import { Badge } from "@/components/ui/Badge";

const navItems = [
  { href: "/overview", label: "Overview" },
  { href: "/markets", label: "Markets" },
  { href: "/history", label: "History" },
  { href: "/settings", label: "Settings" },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const pathname = usePathname();
  const { connected, pnl, btc, meta } = useBotStore();

  const uptimeDisplay = meta
    ? formatCountdown(meta.uptime_sec)
    : "--:--";

  return (
    <div className="flex min-h-screen">
      {/* ─── Sidebar ─── */}
      <aside className="fixed inset-y-0 left-0 z-30 flex w-[280px] flex-col border-r border-border-primary bg-bg-secondary">
        {/* Logo / title */}
        <div className="flex h-14 items-center gap-2 border-b border-border-primary px-5">
          <div className="h-2.5 w-2.5 rounded-full bg-accent-blue" />
          <span className="text-sm font-semibold text-text-primary">
            Polymarket Bot
          </span>
        </div>

        {/* Nav links */}
        <nav className="flex-1 space-y-1 px-3 py-4">
          {navItems.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center rounded-md px-3 py-2 text-sm font-medium transition-colors",
                  active
                    ? "bg-bg-hover text-text-primary"
                    : "text-text-secondary hover:bg-bg-tertiary hover:text-text-primary",
                )}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>

        {/* Bot status */}
        <div className="border-t border-border-primary px-5 py-4">
          <div className="flex items-center gap-2">
            <div
              className={cn(
                "h-2 w-2 rounded-full",
                connected ? "bg-accent-green" : "bg-accent-red",
              )}
            />
            <span className="text-xs text-text-secondary">
              {connected ? "Connected" : "Disconnected"}
            </span>
          </div>
        </div>
      </aside>

      {/* ─── Main content ─── */}
      <div className="ml-[280px] flex flex-1 flex-col">
        {/* Header bar */}
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-border-primary bg-bg-primary/80 px-6 backdrop-blur-sm">
          {/* BTC price */}
          <div className="flex items-center gap-3">
            <span className="text-xs font-medium uppercase text-text-muted">BTC</span>
            <span className="font-mono text-sm text-text-primary">
              {btc ? formatUsd(btc.price) : "---"}
            </span>
            {btc && (
              <Badge variant={btc.deviation >= 0 ? "success" : "danger"}>
                {btc.deviation >= 0 ? "+" : ""}
                {(btc.deviation * 100).toFixed(2)}%
              </Badge>
            )}
          </div>

          {/* PnL summary */}
          <div className="flex items-center gap-6">
            <div className="text-right">
              <span className="text-xs text-text-muted">PnL</span>
              <p
                className={cn(
                  "font-mono text-sm font-semibold",
                  pnl.total >= 0 ? "text-profit" : "text-loss",
                )}
              >
                {formatUsd(pnl.total)}
              </p>
            </div>

            {/* Session timer */}
            <div className="text-right">
              <span className="text-xs text-text-muted">Uptime</span>
              <p className="font-mono text-sm text-text-primary">
                {uptimeDisplay}
              </p>
            </div>
          </div>
        </header>

        {/* Page content */}
        <main className="flex-1 p-6">{children}</main>
      </div>
    </div>
  );
}
