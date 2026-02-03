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
  lagMeasurements: number[];
  p50: number;
  p95: number;
  p99: number;
}

interface HistogramBucket {
  range: string;
  count: number;
  min: number;
  max: number;
}

const COLORS = {
  green: '#00d4aa',
  amber: '#ffaa00',
  red: '#ff4757',
  blue: '#3b82f6',
  border: '#2a2a3a',
  card: '#16161f',
  muted: '#6b7280',
};

export function LatencyHistogram({ lagMeasurements, p50, p95, p99 }: LatencyHistogramProps) {
  const bucketSize = 500;
  const maxLag = Math.max(...lagMeasurements, 3000);
  const numBuckets = Math.ceil(maxLag / bucketSize);

  const buckets: HistogramBucket[] = [];
  for (let i = 0; i < numBuckets; i++) {
    const min = i * bucketSize;
    const max = (i + 1) * bucketSize;
    buckets.push({ range: `${min}-${max}`, count: 0, min, max });
  }

  lagMeasurements.forEach((lag) => {
    const bucketIndex = Math.min(Math.floor(lag / bucketSize), numBuckets - 1);
    if (bucketIndex >= 0 && bucketIndex < buckets.length) {
      buckets[bucketIndex].count++;
    }
  });

  const hasData = lagMeasurements.length > 0;

  return (
    <div
      style={{
        background: 'var(--bg-card)',
        border: '1px solid var(--border)',
        borderRadius: '6px',
        height: '100%',
        display: 'flex',
        flexDirection: 'column',
        minHeight: 0,
      }}
    >
      {/* Minimal header */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '0.5rem 0.75rem',
          borderBottom: '1px solid var(--border)',
          flexShrink: 0,
        }}
      >
        <span
          style={{
            fontSize: '0.5625rem',
            fontFamily: 'var(--font-mono)',
            textTransform: 'uppercase',
            letterSpacing: '0.08em',
            color: 'var(--text-muted)',
          }}
        >
          Distribution
        </span>
        <span
          style={{
            fontSize: '0.5625rem',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-muted)',
          }}
        >
          {lagMeasurements.length}
        </span>
      </div>

      {/* Chart - maximize this */}
      {!hasData ? (
        <div
          style={{
            flex: 1,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-muted)',
            fontSize: '0.6875rem',
          }}
        >
          Collecting...
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0, padding: '0.5rem' }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={buckets} margin={{ top: 16, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.border} opacity={0.4} />
              <XAxis
                dataKey="range"
                tick={{ fontSize: 8, fill: COLORS.muted }}
                stroke={COLORS.border}
                tickLine={false}
                axisLine={{ stroke: COLORS.border }}
                interval={0}
                angle={-45}
                textAnchor="end"
                height={40}
              />
              <YAxis
                tick={{ fontSize: 8, fill: COLORS.muted }}
                stroke={COLORS.border}
                tickLine={false}
                axisLine={{ stroke: COLORS.border }}
                allowDecimals={false}
                width={30}
              />
              <Tooltip
                contentStyle={{
                  background: COLORS.card,
                  border: `1px solid ${COLORS.border}`,
                  borderRadius: '4px',
                  fontSize: '10px',
                  fontFamily: 'var(--font-mono)',
                  padding: '4px 8px',
                }}
                formatter={(value: number) => [`${value}`, 'n']}
                labelFormatter={(label) => `${label}ms`}
                labelStyle={{ color: COLORS.muted }}
              />
              <ReferenceLine
                x={`${Math.floor(p50 / bucketSize) * bucketSize}-${(Math.floor(p50 / bucketSize) + 1) * bucketSize}`}
                stroke={COLORS.green}
                strokeDasharray="3 3"
                strokeWidth={1}
              />
              <ReferenceLine
                x={`${Math.floor(p95 / bucketSize) * bucketSize}-${(Math.floor(p95 / bucketSize) + 1) * bucketSize}`}
                stroke={COLORS.amber}
                strokeDasharray="3 3"
                strokeWidth={1}
              />
              <ReferenceLine
                x={`${Math.floor(p99 / bucketSize) * bucketSize}-${(Math.floor(p99 / bucketSize) + 1) * bucketSize}`}
                stroke={COLORS.red}
                strokeDasharray="3 3"
                strokeWidth={1}
              />
              <Bar dataKey="count" fill={COLORS.blue} radius={[2, 2, 0, 0]} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export default LatencyHistogram;
