import type {
  DeepPartial,
  ChartOptions,
  CandlestickSeriesOptions,
  LineSeriesOptions,
} from "lightweight-charts";

// ─── Shared chart layout matching Polymarket dark theme ───

export const baseChartOptions: DeepPartial<ChartOptions> = {
  layout: {
    background: { color: "#0e1117" },
    textColor: "#8b949e",
    fontSize: 12,
  },
  grid: {
    vertLines: { color: "#1c2333" },
    horzLines: { color: "#1c2333" },
  },
  crosshair: {
    vertLine: { color: "#4a9eff44", width: 1, style: 3, labelBackgroundColor: "#1c2333" },
    horzLine: { color: "#4a9eff44", width: 1, style: 3, labelBackgroundColor: "#1c2333" },
  },
  rightPriceScale: {
    borderColor: "#30363d",
  },
  timeScale: {
    borderColor: "#30363d",
    timeVisible: true,
    secondsVisible: false,
  },
};

// ─── Series style presets ───

export const candlestickColors: DeepPartial<CandlestickSeriesOptions> = {
  upColor: "#2dc96f",
  downColor: "#ff4d4d",
  borderUpColor: "#2dc96f",
  borderDownColor: "#ff4d4d",
  wickUpColor: "#2dc96f",
  wickDownColor: "#ff4d4d",
};

export const probabilityLineStyle: DeepPartial<LineSeriesOptions> = {
  color: "#4a9eff",
  lineWidth: 2,
};

// ─── Event marker styles (for SeriesMarkers) ───

export const eventMarkers = {
  entry: {
    color: "#2dc96f",
    shape: "arrowUp" as const,
    text: "ENTRY",
  },
  fill: {
    color: "#4a9eff",
    shape: "circle" as const,
    text: "FILL",
  },
  hedge: {
    color: "#f97316",
    shape: "square" as const,
    text: "HEDGE",
  },
  merge: {
    color: "#a78bfa",
    shape: "diamond" as const,
    text: "MERGE",
  },
} as const;

// ─── Aliases used by chart components ───

export const chartOptions = baseChartOptions;
export const candlestickSeriesOptions = candlestickColors;
