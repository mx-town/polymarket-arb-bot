# Polymarket BTC 15-Minute Arbitrage Bot

Automated arbitrage system for Polymarket's Bitcoin 15-minute UP/DOWN binary prediction markets. Exploits pricing inefficiencies through Dutch Book arbitrage, lag arbitrage, and momentum-based directional trades.

**Target Performance:** 95-98% win rate with minimum 2.5-3% edge after fees.

## How It Works

### Market Mechanics

**Resolution Source:** Chainlink Data Streams on Polygon PoS  
**Resolution Logic:** Market resolves "UP" if `end_price ≥ start_price`  
**Market Identifiers:** Series ID `10192`, Slug `btc-up-or-down-15m`

### Fee Structure

| Probability | Taker Fee | Required Edge |
|-------------|-----------|---------------|
| ~50% | ~3% | 5%+ |
| 10%/90% | ~1% | 2%+ |
| 1%/99% | ~0% | 0.5%+ |

Extreme probabilities offer near-zero fees—key for profitability.

---

## Strategies

### 1. Dutch Book (Zero Risk)

In binary markets, YES + NO shares should always equal $1.00. During volatile events, prices can briefly desync:

```
UP:   $0.48
DOWN: $0.49
Total: $0.97  ← should be $1.00
```

Buy both sides for $0.97, guarantee $1.00 payout at resolution. **$0.03 profit, zero risk.**

**Trigger:** `UP_ask + DOWN_ask < $0.99`

### 2. Lag Arbitrage (Low Risk)

Exploit the 2-5 second delay between Binance spot price movements and Chainlink oracle updates. Buy the direction Binance indicates before Polymarket reprices.

**Trigger:** Binance leads Chainlink by ≥0.1% sustained for 500ms, combined prices below $0.995

### 3. Momentum Directional (Controlled Risk)

Take directional positions when technical indicators align with order book imbalance and sufficient time remains before resolution.

**Confirmation Required:** Velocity above threshold, positive acceleration, order book imbalance >0.3, time remaining >60s

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Docker Compose                              │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐   │
│  │  Backend Container (Python)                                  │   │
│  │                                                              │   │
│  │   ┌──────────────┐         ┌─────────────────────────────┐  │   │
│  │   │   Bot        │◀───────▶│  Polymarket CLOB WebSocket  │  │   │
│  │   │  (main.py)   │         │  (order books, prices)      │  │   │
│  │   │              │◀───────▶│  Polymarket RTDS WebSocket  │  │   │
│  │   │              │         │  (Chainlink prices)         │  │   │
│  │   │              │◀───────▶│  Binance WebSocket          │  │   │
│  │   │              │         │  (spot trades, momentum)    │  │   │
│  │   └──────┬───────┘         └─────────────────────────────┘  │   │
│  │          │ IPC (/tmp/*.json)                                 │   │
│  │   ┌──────▼───────┐                                          │   │
│  │   │  API Server  │◀──────── HTTP/WS :8000                   │   │
│  │   │  (FastAPI)   │                                          │   │
│  │   └──────────────┘                                          │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              ▲                                      │
│                              │                                      │
│  ┌───────────────────────────┴─────────────────────────────────┐   │
│  │  Frontend Container (Node)                                   │   │
│  │  React Dashboard :3000                                       │   │
│  │  - Real-time metrics via WebSocket                          │   │
│  │  - Market prices, lag windows, P&L charts                   │   │
│  │  - Bot control (start/stop, config)                         │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Data Architecture

### Price Feeds (Priority Order)

1. **Binance WebSocket** — Leading indicator, fastest signal
2. **Polymarket RTDS Chainlink** — Resolution source (truth)
3. **Polymarket RTDS Binance** — Reference feed
4. **Chainlink On-Chain RPC** — Fallback verification

### WebSocket Endpoints

```
Polymarket RTDS:   wss://ws-live-data.polymarket.com/ws
Polymarket CLOB:   wss://ws-subscriptions-clob.polymarket.com/ws/
Binance Trades:    wss://stream.binance.com:9443/ws/btcusdt@trade
Polygon WSS:       wss://polygon-bor-rpc.publicnode.com
```

### REST APIs

```
CLOB API:    https://clob.polymarket.com
Gamma API:   https://gamma-api.polymarket.com
```

### Contract Addresses (Polygon)

```
Chainlink BTC/USD:   0xc907E116054Ad103354f2D350FD2514433D57F6f
USDC:                0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
CTF Exchange:        0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
```

---

## Signal Thresholds

| Signal | Threshold |
|--------|-----------|
| Dutch Book trigger | UP + DOWN < $0.99 |
| Lag arb deviation | 0.1% sustained 500ms |
| Momentum velocity | 0.1% in 5 seconds |
| Flash crash | 30% drop in 10 seconds |
| Minimum edge | 3% after fees |

**Execution:** Always use Fill-or-Kill (FOK) orders for arbitrage.

---

## Bitcoin Statistical Properties

**Mean Reversion:** Autocorrelation of -0.0575 at 15-minute intervals. Price moves tend to reverse, not continue—favors contrarian signals.

**Turn-of-Candle Anomaly:** Positive returns concentrate at candle boundaries (phase 0.0-0.1 and 0.9-1.0).

### Session Volatility

| Session | UTC Hours | Volatility |
|---------|-----------|------------|
| ASIA | 00:00-08:00 | Low |
| EUROPE | 08:00-13:00 | Medium |
| US_EU_OVERLAP | 13:00-17:00 | **High** (optimal) |
| US | 17:00-21:00 | Medium-High |
| LATE_US | 21:00-00:00 | Low |

---

## Quick Start (Docker)

```bash
# 1. Clone and setup
git clone https://github.com/mx-town/polymarket-arb-bot.git
cd polymarket-arb-bot

# 2. Create environment file
cp .env.example .env

# 3. Start services
docker compose up -d

# 4. View dashboard
open http://localhost:3000

# 5. View logs
docker compose logs -f backend
```

## Local Development

### Prerequisites

- Python 3.11+ with [uv](https://github.com/astral-sh/uv) package manager
- Node.js 20+ with [pnpm](https://pnpm.io/) package manager

### Setup

```bash
# Install Python dependencies
uv sync

# Install frontend dependencies
cd dashboard && pnpm install && cd ..

# Run backend
uv run python -m src.main

# Run frontend (in another terminal)
cd dashboard && pnpm run dev
```

---

## Research & Observation Tools

The `arb-capture` CLI provides tools for data collection, model building, and live observation.

### Commands

| Command | Description |
|---------|-------------|
| `uv run arb-capture init` | Download 6 months of Binance data and build probability model |
| `uv run arb-capture rebuild` | Rebuild model from existing data |
| `uv run arb-capture observe` | Run live observation with model predictions |
| `uv run arb-capture verify` | 5-minute stream health check |

### First-Time Setup

```bash
# Download data + build probability surface model (~5 min)
uv run arb-capture init

# Or if you already have data, just rebuild the model (~2 min)
uv run arb-capture rebuild
```

### Live Observation

Run observation mode to see what the bot would do without trading:

```bash
# 1-hour observation (default)
uv run arb-capture observe

# Custom duration (30 minutes)
uv run arb-capture observe --duration 1800

# With debug logging
uv run arb-capture --debug observe --duration 300
```

Observation mode:
- Connects to all price streams (Binance, Chainlink, CLOB)
- Tracks 15-minute candle windows
- Calculates model P(UP) predictions
- Detects signals (Dutch Book, Lag Arb, Momentum)
- Exports snapshots to Parquet for analysis

### Verify Stream Connections

```bash
# 5-minute health check (default)
uv run arb-capture verify

# Shorter verification
uv run arb-capture verify --duration 60
```

### Output Files

| File | Location | Content |
|------|----------|---------|
| Raw candles | `research/data/raw/BTCUSDT_1m.parquet` | 1-minute Binance candles |
| Features | `research/data/raw/BTCUSDT_15m_features.parquet` | Extracted window features |
| Model | `research/models/probability_surface.json` | Probability surface buckets |
| Observations | `research/data/observations/snapshots_*.parquet` | Live capture snapshots |

---

## Configuration

Configuration is loaded from multiple sources (priority: CLI > ENV > YAML > defaults).

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DRY_RUN` | `true` | Read-only mode, no trades executed |
| `MIN_SPREAD` | `0.02` | Minimum profit to trigger trade (2%) |
| `MAX_POSITION_SIZE` | `50` | Maximum USDC per trade |
| `POLL_INTERVAL` | `2.0` | Seconds between market discovery scans |
| `POLYMARKET_PRIVATE_KEY` | — | Wallet private key (live trading only) |
| `POLYMARKET_FUNDER_ADDRESS` | — | Wallet deposit address (live trading only) |

### YAML Configuration Reference

```yaml
# Trading settings
trading:
  dry_run: true
  min_spread: 0.02
  min_net_profit: 0.005
  max_position_size: 100
  fee_rate: 0.02

# Polling/discovery settings
polling:
  interval: 5
  batch_size: 50
  market_refresh_interval: 300

# WebSocket connection settings
websocket:
  ping_interval: 5
  reconnect_delay: 5

# Dutch Book strategy (hold to resolution)
dutch_book:
  max_combined_price: 0.99
  min_time_to_resolution_sec: 300
  exit_on_pump_threshold: 0.10

# Lag arbitrage strategy
lag_arb:
  enabled: true
  candle_interval: "15m"
  spot_momentum_window_sec: 5
  spot_move_threshold_pct: 0.001
  max_combined_price: 0.995
  expected_lag_ms: 2000
  max_lag_window_ms: 5000
  momentum_trigger_threshold_pct: 0.001
  pump_exit_threshold_pct: 0.03
  max_hold_time_sec: 300

# Momentum strategy
momentum:
  enabled: true
  velocity_threshold_pct: 0.001
  min_book_imbalance: 0.3
  min_time_remaining_sec: 60
  require_positive_acceleration: true

# Risk management
risk:
  max_consecutive_losses: 3
  max_daily_loss_usd: 100
  cooldown_after_loss_sec: 300
  max_total_exposure: 1000

# Market filters
filters:
  min_liquidity_usd: 1000
  min_book_depth: 500
  max_spread_pct: 0.05
  market_types:
    - btc-up-or-down-15m
```

### CLI Arguments

```bash
python -m src.main \
  --config config/default.yaml \
  --live \
  --min-spread 0.02 \
  --strategy dutch_book \
  -v, --verbose
```

---

## Dashboard

The React dashboard provides real-time monitoring at `http://localhost:3000`:

- **Metrics Panel**: Total P&L, trades, opportunities
- **Control Panel**: Start/stop bot, view uptime
- **Markets Panel**: Active markets with bid/ask prices
- **Lag Windows Panel**: Active arbitrage windows
- **Signal Feed**: Real-time event stream
- **P&L Chart**: Historical profit/loss

---

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/status` | GET | Bot status (running, PID, uptime) |
| `/api/metrics` | GET | Full metrics + visibility data |
| `/api/config` | GET | Current configuration |
| `/api/config` | PUT | Update configuration |
| `/api/restart` | POST | Restart bot |
| `/api/ws/metrics` | WS | Real-time metrics stream |

---

## Production Deployment (Kubernetes)

### 1. Add to ArgoCD

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: polymarket-arb-bot
  namespace: argocd
spec:
  project: default
  source:
    repoURL: https://github.com/mx-town/polymarket-arb-bot.git
    targetRevision: main
    path: k8s
  destination:
    server: https://kubernetes.default.svc
    namespace: default
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
```

### 2. Create Credentials Secret

```bash
kubectl create secret generic polymarket-credentials \
  --from-literal=private_key=YOUR_PRIVATE_KEY \
  --from-literal=funder_address=YOUR_WALLET_ADDRESS
```

---

## Rate Limits

| Endpoint | Limit |
|----------|-------|
| Order placement | 3000 requests / 10 minutes |
| Public endpoints | 100 requests / minute |
| Trading endpoints | 60 orders / minute |

---

## Project Structure

```
├── src/                    # Python source
│   ├── main.py             # Bot orchestrator
│   ├── config.py           # Configuration management
│   ├── api/                # FastAPI server
│   ├── data/               # WebSocket clients
│   ├── market/             # Market discovery & state
│   ├── strategy/           # Trading strategies
│   ├── execution/          # Order execution
│   └── utils/              # Logging, metrics
├── research/               # Probability model & backtesting
│   ├── run_research.py     # Main orchestration
│   ├── data/               # Historical data fetcher
│   ├── models/             # Probability surface
│   └── analysis/           # Volatility, session, lag analysis
├── dashboard/              # React frontend
├── config/                 # YAML configuration
├── k8s/                    # Kubernetes manifests
└── docker-compose.yaml     # Local development
```

---

## Key Insights

1. **Binary framing:** This is betting on outcomes, not trend trading. Question is "where will price be at resolution" not "where is price trending."

2. **Early exit preferred:** Sell the repriced side within minutes rather than holding to resolution.

3. **Chainlink is truth:** All other feeds are signals. Resolution depends only on Chainlink Data Streams.

4. **Lag window:** 2-5 seconds between Binance movement and Chainlink update is the primary arbitrage opportunity.

5. **Fee sensitivity:** 3% taker fee at 50/50 requires 5%+ edge. Target extreme probabilities where fees approach zero.

6. **Session selection:** US-EU overlap (13:00-17:00 UTC) offers highest volatility and best opportunities.

---

## Risks & Caveats

- **Execution risk** — Prices can move before orders fill
- **Fees** — ~3% at 50/50 probability, near-zero at extremes
- **Liquidity** — Low liquidity may prevent fills
- **Rate limits** — APIs have rate limits
- **Geographic restrictions** — Polymarket not available everywhere

---

## Reference Repositories

| Repository | Focus |
|------------|-------|
| gabagool222/15min-btc-polymarket-trading-bot | FOK execution, ask book traversal |
| vladmeer/polymarket-arbitrage-bot | Flash crash strategy, WebSocket patterns |
| simone46b/polymarket-trading-bot | Oracle price arbitrage |
| Polymarket/py-clob-client | Official Python client |

---

## Getting Polymarket Credentials

1. Go to [reveal.polymarket.com](https://reveal.polymarket.com)
2. Connect your wallet
3. Export your private key
4. Your funder address is your Polymarket deposit address

---

## License

MIT