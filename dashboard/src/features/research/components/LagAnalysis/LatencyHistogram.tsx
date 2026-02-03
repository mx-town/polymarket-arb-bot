import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';

interface LatencyHistogramProps {
  /** Raw lag measurements in milliseconds */
  lagMeasurements: number[];
  /** Median lag (P50) in milliseconds */
  p50: number;
  /** 95th percentile lag in milliseconds */
  p95: number;
  /** 99th percentile lag in milliseconds */
  p99: number;
}

interface HistogramBucket {
  range: string;
  count: number;
  min: number;
  max: number;
}

/**
 * Histogram showing distribution of lag measurements
 * X-axis: lag buckets in milliseconds
 * Y-axis: frequency count
 */
export function LatencyHistogram({ lagMeasurements, p50, p95, p99 }: LatencyHistogramProps) {
  // Create histogram buckets (500ms intervals)
  const bucketSize = 500;
  const maxLag = Math.max(...lagMeasurements, 3000);
  const numBuckets = Math.ceil(maxLag / bucketSize);

  const buckets: HistogramBucket[] = [];
  for (let i = 0; i < numBuckets; i++) {
    const min = i * bucketSize;
    const max = (i + 1) * bucketSize;
    buckets.push({
      range: `${min}-${max}`,
      count: 0,
      min,
      max,
    });
  }

  // Count measurements in each bucket
  lagMeasurements.forEach((lag) => {
    const bucketIndex = Math.min(Math.floor(lag / bucketSize), numBuckets - 1);
    if (bucketIndex >= 0 && bucketIndex < buckets.length) {
      buckets[bucketIndex].count++;
    }
  });

  const hasData = lagMeasurements.length > 0;

  // Custom label for reference lines
  const renderReferenceLabel = (value: number, label: string, color: string) => ({
    value,
    stroke: color,
    strokeDasharray: '4 4',
    strokeWidth: 2,
    label: {
      value: `${label}: ${value.toFixed(0)}ms`,
      position: 'top' as const,
      fill: color,
      fontSize: 10,
      fontFamily: 'var(--font-mono)',
    },
  });

  return (
    <div className="rounded-lg border bg-card">
      {/* Header */}
      <div className="flex items-center gap-2 border-b px-4 py-3 bg-muted/30">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Latency Distribution
        </span>
        <span className="ml-auto text-[11px] text-muted-foreground font-mono">
          {lagMeasurements.length} samples
        </span>
      </div>

      {/* Chart */}
      {!hasData ? (
        <div className="py-12 text-center text-muted-foreground text-sm">
          <div className="mb-1">No lag data available</div>
          <div className="text-xs">Histogram will appear once measurements are collected</div>
        </div>
      ) : (
        <div className="p-4 h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={buckets} margin={{ top: 25, right: 20, left: -10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
              <XAxis
                dataKey="range"
                tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                stroke="hsl(var(--border))"
                tickLine={false}
                axisLine={{ stroke: 'hsl(var(--border))' }}
              />
              <YAxis
                tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                stroke="hsl(var(--border))"
                tickLine={false}
                axisLine={{ stroke: 'hsl(var(--border))' }}
                allowDecimals={false}
              />
              <Tooltip
                contentStyle={{
                  background: 'hsl(var(--card))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '6px',
                  fontSize: '12px',
                  fontFamily: 'var(--font-mono)',
                }}
                formatter={(value: number) => [`${value} samples`, 'Count']}
                labelFormatter={(label) => `Lag: ${label}ms`}
                labelStyle={{ color: 'hsl(var(--muted-foreground))' }}
              />
              {/* P50 reference line */}
              <ReferenceLine {...renderReferenceLabel(p50, 'P50', '#22c55e')} />
              {/* P95 reference line */}
              <ReferenceLine {...renderReferenceLabel(p95, 'P95', '#f59e0b')} />
              {/* P99 reference line */}
              <ReferenceLine {...renderReferenceLabel(p99, 'P99', '#ef4444')} />
              <Bar
                dataKey="count"
                fill="hsl(217.2 91.2% 59.8%)"
                radius={[4, 4, 0, 0]}
                name="Frequency"
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
