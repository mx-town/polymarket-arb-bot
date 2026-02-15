"use client";

import { useBotStore } from "@/stores/bot-store";
import { formatPrice, formatShares } from "@/lib/format";

export function OrderTable() {
  const markets = useBotStore((s) => s.markets);
  const orders = markets.flatMap(
    (m) =>
      m.orders?.map((o) => ({ ...o, slug: m.slug })) ?? []
  );

  return (
    <div className="rounded-lg border border-border-primary bg-bg-secondary">
      <div className="px-3 py-2 border-b border-border-secondary">
        <h3 className="text-xs font-medium text-text-muted uppercase tracking-wider">
          Open Orders ({orders.length})
        </h3>
      </div>
      {orders.length === 0 ? (
        <div className="p-4 text-sm text-text-muted text-center">
          No open orders
        </div>
      ) : (
        <table className="w-full text-xs">
          <thead>
            <tr className="text-text-muted border-b border-border-secondary">
              <th className="px-3 py-1.5 text-left font-medium">Market</th>
              <th className="px-3 py-1.5 text-left font-medium">Side</th>
              <th className="px-3 py-1.5 text-right font-medium">Price</th>
              <th className="px-3 py-1.5 text-right font-medium">Size</th>
              <th className="px-3 py-1.5 text-right font-medium">Filled</th>
            </tr>
          </thead>
          <tbody>
            {orders.map((order, i) => (
              <tr
                key={`${order.token_id}-${i}`}
                className="border-b border-border-secondary last:border-0 hover:bg-bg-tertiary"
              >
                <td className="px-3 py-1.5 text-text-secondary truncate max-w-[120px]">
                  {order.slug.split("-").slice(0, 3).join("-")}
                </td>
                <td className="px-3 py-1.5">
                  <span
                    className={
                      order.direction === "UP"
                        ? "text-accent-green"
                        : order.direction === "DOWN"
                          ? "text-accent-red"
                          : "text-text-secondary"
                    }
                  >
                    {order.side} {order.direction || ""}
                  </span>
                </td>
                <td className="px-3 py-1.5 text-right font-mono">
                  {formatPrice(order.price)}
                </td>
                <td className="px-3 py-1.5 text-right font-mono">
                  {formatShares(order.size)}
                </td>
                <td className="px-3 py-1.5 text-right font-mono text-text-muted">
                  {formatShares(order.matched)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
