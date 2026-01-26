# Polymarket Arbitrage Bot - Development Guidelines

## Project Overview

Python arbitrage bot connecting to Polymarket CLOB and Binance via WebSocket for real-time price data and trading. Features a React dashboard for monitoring and control.

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────┐
│                              DATA SOURCES                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Polymarket CLOB WS ─────────────────────────────────────────────────┐ │
│  wss://ws-subscriptions-clob.polymarket.com/ws/market                │ │
│  └─ Order book updates (book events), price changes                  │ │
│                                                                       │ │
│  Binance Spot WS ────────────────────────────────────────────────────┤ │
│  wss://stream.binance.com:9443/stream?streams=btcusdt@aggTrade/...   │ │
│  └─ Real-time trades for momentum calculation                        │ │
│                                                                       │ │
│  Gamma API (REST) ───────────────────────────────────────────────────┤ │
│  https://gamma-api.polymarket.com/markets                            │ │
│  └─ Market discovery (btc-updown, eth-updown)                        │ │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                              BOT PROCESS                                │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  MarketStateManager ─── Tracks all active markets (YES/DOWN prices)    │
│         │                                                               │
│         ▼                                                               │
│  PriceTracker ───────── Calculates momentum from Binance vs candle     │
│         │               open, emits DirectionSignal when threshold      │
│         │               crossed (0.1%)                                  │
│         ▼                                                               │
│  Strategy ───────────── Conservative: hold to resolution               │
│         │               LagArb: aggressive exit on pump/timeout        │
│         ▼                                                               │
│  OrderExecutor ──────── CLOB API orders (dry-run or live)              │
│         │                                                               │
│         ▼                                                               │
│  PositionManager ────── Tracks open/closed positions                   │
│  RiskManager ────────── Consecutive loss, daily P&L limits             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                          IPC (/tmp/*.json)
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                            API SERVER                                   │
├─────────────────────────────────────────────────────────────────────────┤
│  FastAPI on :8000                                                       │
│  - GET/PUT /api/config                                                  │
│  - GET /api/metrics (reads /tmp/polymarket_metrics.json)               │
│  - WS /api/ws/metrics (pushes every 1 sec)                             │
│  - POST /api/restart (SIGTERM), /api/refresh-markets (SIGUSR1)         │
└─────────────────────────────────────────────────────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                          REACT DASHBOARD                                │
├─────────────────────────────────────────────────────────────────────────┤
│  :3000 (dev) / served by API (prod)                                    │
│  Components: MetricsDisplay, ControlPanel, ConfigPanel,                │
│              MarketsPanel, LagWindowsPanel, SignalFeed,                │
│              PnlChart, ActivityChart                                   │
└─────────────────────────────────────────────────────────────────────────┘
```

### Inter-Process Communication (IPC)

Bot and API server communicate via filesystem:

| File | Purpose | Writer | Reader |
|------|---------|--------|--------|
| `/tmp/polymarket_bot.pid` | Bot process ID | Bot | API |
| `/tmp/polymarket_metrics.json` | Full metrics + events | Bot (every 10s) | API |

Signal handling:
- `SIGTERM` → Graceful shutdown
- `SIGUSR1` → Force refresh markets

## Configuration Reference

Configuration sources (priority: CLI > ENV > YAML > defaults):

### Trading (`config.trading.*`)

| Parameter | Type | Default | Env Var | Description |
|-----------|------|---------|---------|-------------|
| `dry_run` | bool | `true` | `DRY_RUN` | Read-only mode, no trades executed |
| `min_spread` | float | `0.02` | `MIN_SPREAD` | Minimum gross profit (2%) |
| `min_net_profit` | float | `0.005` | — | Minimum profit after fees (0.5%) |
| `max_position_size` | float | `100` | `MAX_POSITION_SIZE` | Maximum USDC per trade |
| `fee_rate` | float | `0.02` | — | Estimated Polymarket fee |

### Polling (`config.polling.*`)

| Parameter | Type | Default | Env Var | Description |
|-----------|------|---------|---------|-------------|
| `interval` | int | `5` | `POLL_INTERVAL` | Seconds between market scans |
| `batch_size` | int | `50` | — | Markets per API batch |
| `max_markets` | int | `0` | — | 0 = unlimited |
| `market_refresh_interval` | int | `300` | — | Refresh market list every N seconds |

### WebSocket (`config.websocket.*`)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `ping_interval` | int | `5` | Seconds between pings |
| `reconnect_delay` | int | `5` | Delay before reconnect attempt |

### Conservative Strategy (`config.conservative.*`)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_combined_price` | float | `0.99` | Entry threshold (YES + NO) |
| `min_time_to_resolution_sec` | int | `300` | Minimum time to resolution |
| `exit_on_pump_threshold` | float | `0.10` | Exit if one side pumps 10% |

### Lag Arbitrage Strategy (`config.lag_arb.*`)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `enabled` | bool | `true` | Enable lag arb strategy |
| `candle_interval` | str | `"1h"` | Use 1H candles (0% fees) |
| `spot_momentum_window_sec` | int | `10` | Momentum calculation window |
| `spot_move_threshold_pct` | float | `0.002` | 0.2% move for confirmation |
| `max_combined_price` | float | `0.995` | Entry threshold for 1H markets |
| `expected_lag_ms` | int | `2000` | Expected Polymarket lag |
| `max_lag_window_ms` | int | `5000` | Max time to wait for repricing |
| `fee_rate` | float | `0.0` | 1H markets have 0% fees |
| `momentum_trigger_threshold_pct` | float | `0.001` | PRIMARY: 0.1% momentum trigger |
| `pump_exit_threshold_pct` | float | `0.03` | Exit if one side pumps 3% |
| `max_hold_time_sec` | int | `300` | Force exit after 5 minutes |

### Risk Management (`config.risk.*`)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `max_consecutive_losses` | int | `3` | Stop after N consecutive losses |
| `max_daily_loss_usd` | float | `100` | Stop after daily loss limit |
| `cooldown_after_loss_sec` | int | `300` | Pause after loss |
| `max_total_exposure` | float | `1000` | Max USDC across all positions |

### Market Filters (`config.filters.*`)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `min_liquidity_usd` | float | `1000` | Minimum market liquidity |
| `min_book_depth` | float | `500` | Minimum order book depth |
| `max_spread_pct` | float | `0.05` | Maximum bid-ask spread |
| `max_market_age_hours` | int | `1` | Prefer recent markets |
| `fallback_age_hours` | int | `24` | Fallback if no recent markets |
| `min_volume_24h` | float | `100` | Minimum 24h volume in USDC |
| `market_types` | list | `["btc-updown", "eth-updown"]` | Market slugs to track |

## File Structure

```
src/
├── main.py                 # Bot orchestrator, signal handlers
├── config.py               # Configuration loading (YAML + ENV + CLI)
├── api/
│   ├── server.py           # FastAPI app, static file serving
│   └── routes/
│       ├── config.py       # GET/PUT /api/config
│       ├── metrics.py      # GET /api/metrics, WS /api/ws/metrics
│       └── control.py      # POST /api/restart, /api/refresh-markets
├── data/
│   ├── polymarket_ws.py    # Polymarket CLOB WebSocket client
│   ├── binance_ws.py       # Binance aggTrade WebSocket client
│   └── price_tracker.py    # Momentum calc, DirectionSignal emission
├── market/
│   ├── discovery.py        # Gamma API market fetching
│   ├── state.py            # MarketState, MarketStateManager
│   └── filters.py          # Market filtering logic
├── strategy/
│   ├── signals.py          # Signal data structures
│   ├── conservative.py     # Hold-to-resolution strategy
│   └── lag_arb.py          # Momentum-based lag arbitrage
├── execution/
│   ├── orders.py           # CLOB order execution
│   ├── position.py         # Position tracking
│   └── risk.py             # Risk management
└── utils/
    ├── logging.py          # Component-based logging
    └── metrics.py          # Metrics tracking + file export

dashboard/
├── src/
│   ├── App.tsx             # Main layout (3-column grid)
│   ├── components/
│   │   ├── MetricsDisplay.tsx
│   │   ├── ControlPanel.tsx
│   │   ├── ConfigPanel.tsx
│   │   ├── MarketsPanel.tsx
│   │   ├── LagWindowsPanel.tsx
│   │   ├── SignalFeed.tsx
│   │   ├── PnlChart.tsx
│   │   └── ActivityChart.tsx
│   ├── hooks/
│   │   └── useMetrics.ts   # WebSocket connection to /api/ws/metrics
│   └── api/
│       └── client.ts       # HTTP/WS API client
├── package.json
└── vite.config.ts
```

## Coding Conventions

### Logging
- Use descriptive log messages with key-value pairs for easier parsing
- Format: `logger.info("ACTION_NAME", "key=value key2=value2")`
- Examples:
  ```python
  logger.info("CONNECTING", POLYMARKET_WS_URL)
  logger.info("SUBSCRIBED", f"tokens={len(token_ids)}")
  logger.warning("RECONNECTING", f"attempt={self.reconnect_count}")
  ```

### WebSocket Handling
- Always check data type after JSON parsing (heartbeats may send raw integers)
- Use separate ping threads to avoid blocking
- See `.claude/rules/websocket.md` for patterns

### Error Handling
- Catch specific exceptions, not generic `Exception`
- Validate types before accessing attributes
- See `.claude/rules/error-handling.md` for patterns

## Key Patterns

### Momentum-First Signal (Lag Arb)
The lag arb strategy uses momentum as the PRIMARY trigger:
1. Calculate momentum = (current_price - candle_open) / candle_open
2. When momentum crosses 0.1%, emit DirectionSignal
3. Enter position if combined_ask < threshold
4. Exit aggressively (don't wait for resolution)

### Atomic Metrics Export
Bot writes metrics atomically:
```python
temp_path = f"{path}.tmp"
with open(temp_path, "w") as f:
    json.dump(data, f)
os.rename(temp_path, path)  # Atomic on POSIX
```

### Event-Driven Updates
Bot triggers on WebSocket updates, not polling (except market discovery).

## Communication Preferences
- Provide clear explanations of identified issues and proposed solutions
- Confirm fixes via logs or code snippets
- Prompt for confirmation before making changes
- Confirm when PRs have been successfully created

## Best Practices

### Root Cause Analysis
- Thoroughly investigate error logs and code to pinpoint exact causes
- Apply minimal necessary code changes to resolve specific bugs
- Verify fixes by re-checking logs or code
- Communicate: explain the problem, the solution, and how to verify

### PR Workflow
- Create focused PRs with clear descriptions
- Include test verification in PR descriptions
- Confirm PR creation with the user
