# Dashboard Design Specification

> **Reference**: Matches Polymarket's dark-theme aesthetic with bot analytics overlay.

## Color Palette

| Token | Hex | Usage |
|-------|-----|-------|
| `--bg-primary` | `#0e1117` | Main background |
| `--bg-secondary` | `#161b22` | Cards, sidebar, panels |
| `--bg-tertiary` | `#1c2333` | Hover states, elevated surfaces |
| `--border` | `#30363d` | Borders, dividers |
| `--text-primary` | `#e6edf3` | Primary text |
| `--text-secondary` | `#8b949e` | Secondary labels |
| `--text-muted` | `#484f58` | Disabled, muted |
| `--accent-blue` | `#4a9eff` | Primary accent, links, active tabs |
| `--accent-green` | `#2dc96f` | Up/positive, Polymarket "Up" button |
| `--accent-red` | `#ff4d4d` | Down/negative |
| `--accent-yellow` | `#fbbf24` | Warnings, BTC price line |
| `--accent-purple` | `#a78bfa` | Merge events |
| `--accent-orange` | `#f97316` | Hedge events |

## Typography

| Context | Font | Weight | Size |
|---------|------|--------|------|
| UI text | Inter | 400/500/600 | 13-16px |
| Data/numbers | JetBrains Mono | 400/500 | 12-14px |
| Headings | Inter | 600/700 | 18-28px |
| Chart labels | JetBrains Mono | 400 | 10-11px |

## Chart Configuration (TradingView Lightweight Charts v5)

### Shared Options
```typescript
const chartOptions: DeepPartial<ChartOptions> = {
  layout: {
    background: { type: ColorType.Solid, color: '#0e1117' },
    textColor: '#8b949e',
    fontFamily: "'JetBrains Mono', monospace",
    fontSize: 11,
  },
  grid: {
    vertLines: { color: '#1c2333' },
    horzLines: { color: '#1c2333' },
  },
  crosshair: {
    mode: CrosshairMode.Normal,
    vertLine: { color: '#4a9eff44', width: 1, style: LineStyle.Dashed },
    horzLine: { color: '#4a9eff44', width: 1, style: LineStyle.Dashed },
  },
  rightPriceScale: {
    borderColor: '#30363d',
    scaleMargins: { top: 0.1, bottom: 0.1 },
  },
  timeScale: {
    borderColor: '#30363d',
    timeVisible: true,
    secondsVisible: false,
    tickMarkFormatter: (time) => formatTime(time),
  },
};
```

### Candlestick Series (BTC)
```typescript
const candlestickOptions: DeepPartial<CandlestickSeriesOptions> = {
  upColor: '#2dc96f',
  downColor: '#ff4d4d',
  wickUpColor: '#2dc96f',
  wickDownColor: '#ff4d4d',
  borderVisible: false,
};
```

### Probability Line Series
```typescript
const probabilityOptions: DeepPartial<LineSeriesOptions> = {
  color: '#4a9eff',
  lineWidth: 2,
  crosshairMarkerVisible: true,
  crosshairMarkerRadius: 4,
  priceFormat: { type: 'percent' },
};
```

### Event Markers
```typescript
const markerConfig = {
  entry:  { shape: 'arrowUp',   color: '#2dc96f', size: 2 },
  fill:   { shape: 'circle',    color: '#4a9eff', size: 1.5 },
  hedge:  { shape: 'square',    color: '#f97316', size: 1.5 },
  merge:  { shape: 'arrowDown', color: '#a78bfa', size: 2 },
};
```

## Layout Structure

### Dashboard (Main View)
```
┌──────────────────────────────────────────────────────────────┐
│  Header: Logo │ Market Selector │ PnL │ Mode Badge │ Timer  │
├──────────────────────────────────────────┬───────────────────┤
│                                          │ Market Sidebar    │
│  Chart Area (switchable)                 │ ┌───────────────┐ │
│  ┌────────────────────────────────────┐  │ │ BTC Up/Down   │ │
│  │  BTC Candlestick / Probability    │  │ │ 15 min  94% ● │ │
│  │  [Candle] [Prob] [Both]           │  │ ├───────────────┤ │
│  │                                    │  │ │ ETH Up/Down   │ │
│  │  ████ ██ █ ████ █                 │  │ │ 15 min  67% ● │ │
│  │  ████ ██ █ ████ █     $69,034     │  │ ├───────────────┤ │
│  │                                    │  │ │ SOL Up/Down   │ │
│  └────────────────────────────────────┘  │ │ 15 min  45% ● │ │
│                                          │ └───────────────┘ │
│  Metrics Row                             │                   │
│  ┌─────┐ ┌─────┐ ┌─────┐ ┌─────┐       │ Order Book        │
│  │ PnL │ │ ROI │ │Expos│ │Hedge│       │ ┌───────────────┐ │
│  │$5.23│ │1.2% │ │$120 │ │ 65% │       │ │ Bid  │  Ask   │ │
│  └─────┘ └─────┘ └─────┘ └─────┘       │ │ 0.45 │  0.46  │ │
│                                          │ └───────────────┘ │
│  ┌──────────────────┐ ┌───────────────┐  │                   │
│  │ Pipeline Funnel   │ │ Trade Feed    │  │ Quick Actions     │
│  │ Entry→Fill→Hedge  │ │ FILL UP @0.45│  │ [Start] [Stop]   │
│  │ →Merge            │ │ HEDGE DN @54 │  │ [Config]          │
│  └──────────────────┘ └───────────────┘  │                   │
└──────────────────────────────────────────┴───────────────────┘
```

## WebSocket Message Types

| Type | Frequency | Payload |
|------|-----------|---------|
| `tick_snapshot` | 2/sec | markets[], exposure{}, pnl{}, bankroll{} |
| `btc_price` | 1/sec | price, open, high, low, deviation |
| `volume_state` | 1/sec | short/medium_imbalance, volume |
| `order_placed` | event | slug, direction, side, price, shares |
| `order_filled` | event | slug, direction, shares, price |
| `hedge_complete` | event | slug, hedged_shares, edge |
| `merge_complete` | event | slug, shares, tx_hash |
| `pnl_snapshot` | every 30s | realized, unrealized, total, exposure |

## Responsive Breakpoints

| Breakpoint | Layout |
|------------|--------|
| `≥1280px` | Full 3-column (chart + metrics + sidebar) |
| `1024-1279px` | 2-column (chart+metrics, sidebar overlay) |
| `768-1023px` | Single column, sidebar as drawer |
| `<768px` | Mobile: stacked, chart full-width, metrics horizontal scroll |
