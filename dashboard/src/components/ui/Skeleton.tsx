export function Skeleton({ className }: { className?: string }) {
  return (
    <div className={`animate-pulse rounded bg-bg-tertiary ${className ?? ""}`} />
  );
}

export function ChartSkeleton({ height = 350 }: { height?: number }) {
  return (
    <div className="rounded-lg border border-border-primary bg-bg-secondary">
      <div className="flex items-center justify-between border-b border-border-secondary px-4 py-2">
        <Skeleton className="h-4 w-24" />
      </div>
      <div style={{ height }} className="relative flex items-center justify-center">
        <Skeleton className="h-3/4 w-11/12" />
      </div>
    </div>
  );
}

export function MetricCardSkeleton() {
  return (
    <div className="rounded-lg border border-border-primary bg-bg-secondary p-4">
      <Skeleton className="mb-2 h-3 w-16" />
      <Skeleton className="h-7 w-28" />
    </div>
  );
}
