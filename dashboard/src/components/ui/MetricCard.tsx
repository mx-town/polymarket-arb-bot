"use client";

import { cn } from "@/lib/format";

interface MetricCardProps {
  label: string;
  value: string;
  delta?: string;
  deltaValue?: number;
}

export function MetricCard({ label, value, delta, deltaValue }: MetricCardProps) {
  const deltaColor =
    deltaValue === undefined || deltaValue === 0
      ? "text-text-secondary"
      : deltaValue > 0
        ? "text-profit"
        : "text-loss";

  return (
    <div className="rounded-lg border border-border-primary bg-bg-secondary p-4">
      <p className="text-xs font-medium uppercase tracking-wider text-text-secondary">
        {label}
      </p>
      <p className="mt-1 font-mono text-2xl font-semibold text-text-primary">
        {value}
      </p>
      {delta !== undefined && (
        <p className={cn("mt-1 font-mono text-sm", deltaColor)}>{delta}</p>
      )}
    </div>
  );
}
