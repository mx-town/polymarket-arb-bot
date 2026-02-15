/**
 * Formatting utilities for dashboard display values.
 */

/** Format a number as USD: "$1,234.56" */
export function formatUsd(n: number): string {
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  return `${sign}$${abs.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  })}`;
}

/** Format a decimal as percentage: "12.3%" */
export function formatPct(n: number): string {
  return `${(n * 100).toFixed(1)}%`;
}

/** Format a CLOB price: "0.45" (2 decimal places) */
export function formatPrice(n: number): string {
  return n.toFixed(2);
}

/** Format share count: "11.75" (2 decimal places) */
export function formatShares(n: number): string {
  return n.toFixed(2);
}

/** Format epoch timestamp as "HH:MM:SS" (local time) */
export function formatTime(epoch: number): string {
  const d = new Date(epoch * 1000);
  return d.toLocaleTimeString("en-US", {
    hour12: false,
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

/** Format seconds as countdown: "4:32" or "0:08" */
export function formatCountdown(seconds: number): string {
  const s = Math.max(0, Math.floor(seconds));
  const mins = Math.floor(s / 60);
  const secs = s % 60;
  return `${mins}:${secs.toString().padStart(2, "0")}`;
}

/** Merge class names, filtering out falsy values */
export function cn(...classes: (string | false | null | undefined)[]): string {
  return classes.filter(Boolean).join(" ");
}
