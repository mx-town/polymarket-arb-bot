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
  measurements: LagMeasurement[];
  p50: number;
  p95: number;
}

const COLORS = {
  green: '#00d4aa',
  amber: '#ffaa00',
  blue: '#3b82f6',
  border: '#2a2a3a',
  card: '#16161f',
  muted: '#6b7280',
};

export function LagTimeSeries({ measurements, p50, p95 }: LagTimeSeriesProps) {
  const formatTime = (timestamp: number) => {
    const date = new Date(timestamp);
    return date.toLocaleTimeString('en-US', {
      hour12: false,
      hour: '2-digit',
      minute: '2-digit',
    });
  };

  const chartData = measurements.map((m) => ({
    time: formatTime(m.timestamp),
    timestamp: m.timestamp,
    lag: m.lag_ms,
  }));

  const hasData = chartData.length >= 2;

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
          Time Series
        </span>
        <span
          style={{
            fontSize: '0.5625rem',
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-muted)',
          }}
        >
          {chartData.length}
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
          Need 2+ points
        </div>
      ) : (
        <div style={{ flex: 1, minHeight: 0, padding: '0.5rem' }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={chartData} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={COLORS.border} opacity={0.4} />
              <XAxis
                dataKey="time"
                tick={{ fontSize: 8, fill: COLORS.muted }}
                stroke={COLORS.border}
                tickLine={false}
                axisLine={{ stroke: COLORS.border }}
                interval="preserveStartEnd"
                height={20}
              />
              <YAxis
                tickFormatter={(v) => `${v}`}
                tick={{ fontSize: 8, fill: COLORS.muted }}
                stroke={COLORS.border}
                tickLine={false}
                axisLine={{ stroke: COLORS.border }}
                domain={[0, 'auto']}
                width={35}
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
                formatter={(value: number) => [`${value.toFixed(0)}ms`, 'lag']}
                labelStyle={{ color: COLORS.muted }}
              />
              <ReferenceLine
                y={p50}
                stroke={COLORS.green}
                strokeDasharray="3 3"
                strokeWidth={1}
                label={{
                  value: 'P50',
                  position: 'right',
                  fill: COLORS.green,
                  fontSize: 8,
                  fontFamily: 'var(--font-mono)',
                }}
              />
              <ReferenceLine
                y={p95}
                stroke={COLORS.amber}
                strokeDasharray="3 3"
                strokeWidth={1}
                label={{
                  value: 'P95',
                  position: 'right',
                  fill: COLORS.amber,
                  fontSize: 8,
                  fontFamily: 'var(--font-mono)',
                }}
              />
              <Line
                type="monotone"
                dataKey="lag"
                stroke={COLORS.blue}
                strokeWidth={1.5}
                dot={false}
                activeDot={{ r: 3, fill: COLORS.blue }}
              />
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export default LagTimeSeries;
