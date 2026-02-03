import {
  LineChart,
  Line,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  ReferenceLine,
} from 'recharts';

interface LagMeasurement {
  timestamp: number;
  lag_ms: number;
}

interface LagTimeSeriesProps {
  /** Array of lag measurements with timestamps */
  measurements: LagMeasurement[];
  /** Median lag (P50) in milliseconds */
  p50: number;
  /** 95th percentile lag in milliseconds */
  p95: number;
}

/**
 * Time series chart showing lag measurements over time
 * X-axis: timestamp
 * Y-axis: lag in milliseconds
 */
export function LagTimeSeries({ measurements, p50, p95 }: LagTimeSeriesProps) {
  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  };

  const chartData = measurements.map((m) => ({
    time: formatTime(m.timestamp),
    timestamp: m.timestamp,
    lag: m.lag_ms,
  }));

  const hasData = chartData.length >= 2;

  return (
    <div className="rounded-lg border bg-card">
      {/* Header */}
      <div className="flex items-center gap-2 border-b px-4 py-3 bg-muted/30">
        <span className="text-xs font-semibold uppercase tracking-wider text-muted-foreground">
          Lag Over Time
        </span>
        <span className="ml-auto text-[11px] text-muted-foreground font-mono">
          {chartData.length} points
        </span>
      </div>

      {/* Chart */}
      {!hasData ? (
        <div className="py-12 text-center text-muted-foreground text-sm">
          <div className="mb-1">Collecting data...</div>
          <div className="text-xs">Time series will appear after 2+ measurements</div>
        </div>
      ) : (
        <div className="p-4 h-[280px]">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 10, right: 20, left: -10, bottom: 5 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.5} />
              <XAxis
                dataKey="time"
                tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                stroke="hsl(var(--border))"
                tickLine={false}
                axisLine={{ stroke: 'hsl(var(--border))' }}
                interval="preserveStartEnd"
              />
              <YAxis
                tickFormatter={(v) => `${v}ms`}
                tick={{ fontSize: 10, fill: 'hsl(var(--muted-foreground))' }}
                stroke="hsl(var(--border))"
                tickLine={false}
                axisLine={{ stroke: 'hsl(var(--border))' }}
                domain={[0, 'auto']}
              />
              <Tooltip
                contentStyle={{
                  background: 'hsl(var(--card))',
                  border: '1px solid hsl(var(--border))',
                  borderRadius: '6px',
                  fontSize: '12px',
                  fontFamily: 'var(--font-mono)',
                }}
                formatter={(value: number) => [`${value.toFixed(0)}ms`, 'Lag']}
                labelStyle={{ color: 'hsl(var(--muted-foreground))' }}
              />
              {/* P50 reference line */}
              <ReferenceLine
                y={p50}
                stroke="#22c55e"
                strokeDasharray="4 4"
                strokeWidth={1.5}
                label={{
                  value: `P50: ${p50.toFixed(0)}ms`,
                  position: 'right',
                  fill: '#22c55e',
                  fontSize: 10,
                  fontFamily: 'var(--font-mono)',
                }}
              />
              {/* P95 reference line */}
              <ReferenceLine
                y={p95}
                stroke="#f59e0b"
                strokeDasharray="4 4"
                strokeWidth={1.5}
                label={{
                  value: `P95: ${p95.toFixed(0)}ms`,
                  position: 'right',
                  fill: '#f59e0b',
                  fontSize: 10,
                  fontFamily: 'var(--font-mono)',
                }}
              />
              <Line
                type="monotone"
                dataKey="lag"
                stroke="hsl(217.2 91.2% 59.8%)"
                strokeWidth={2}
                dot={false}
                activeDot={{ r: 4, fill: 'hsl(217.2 91.2% 59.8%)' }}
                name="Lag"
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}
