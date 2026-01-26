# Polymarket Arbitrage Bot

A Python arbitrage bot for Polymarket binary prediction markets with real-time WebSocket data feeds, a React dashboard, and Docker-based local development.

## How It Works

### Conservative Strategy
In binary markets, YES + NO shares should always equal $1.00. During volatile events, prices can briefly desync:

```
YES: $0.48
NO:  $0.49
Total: $0.97  ← should be $1.00
```

Buy both sides for $0.97, guarantee $1.00 payout at resolution. **$0.03 profit, zero risk.**

### Lag Arbitrage Strategy (Phase 2)
Polymarket UP/DOWN hourly markets track crypto prices but lag Binance by 1-5 seconds. The bot:

1. Monitors Binance spot prices (BTC/ETH) via WebSocket
2. Calculates momentum from candle OPEN price (0.1% threshold)
3. When momentum triggers, enters Polymarket before repricing
4. Exits aggressively on pump (3%), spread normalization, or timeout

**Key advantage**: 1H markets have 0% fees on Polymarket.

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

## Configuration

Configuration is loaded from multiple sources (priority: CLI > ENV > YAML > defaults):

- `config/default.yaml` - Main configuration file
- `.env` - Environment variables (overrides YAML)
- CLI arguments - Runtime overrides

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
  dry_run: true              # No trades when true
  min_spread: 0.02           # Minimum gross profit (2%)
  min_net_profit: 0.005      # Minimum profit after fees (0.5%)
  max_position_size: 100     # Maximum USDC per trade
  fee_rate: 0.02             # Estimated Polymarket fee (2%)

# Polling/discovery settings
polling:
  interval: 5                # Seconds between market scans
  batch_size: 50             # Markets per API batch
  max_markets: 0             # 0 = unlimited
  market_refresh_interval: 300  # Refresh market list every 5 min

# WebSocket connection settings
websocket:
  ping_interval: 5           # Seconds between pings
  reconnect_delay: 5         # Delay before reconnect attempt

# Conservative strategy (hold to resolution)
conservative:
  max_combined_price: 0.99   # Entry threshold (YES + NO < $0.99)
  min_time_to_resolution_sec: 300  # Minimum 5 min to resolution
  exit_on_pump_threshold: 0.10     # Exit if one side pumps 10%

# Lag arbitrage strategy (momentum-based)
lag_arb:
  enabled: true                     # Enable lag arb strategy
  candle_interval: "1h"             # Use 1H candles (0% fees)
  spot_momentum_window_sec: 10      # Momentum calculation window
  spot_move_threshold_pct: 0.002    # 0.2% move for confirmation
  max_combined_price: 0.995         # Entry threshold for 1H markets
  expected_lag_ms: 2000             # Expected Polymarket lag (2 sec)
  max_lag_window_ms: 5000           # Max time to wait for repricing
  fee_rate: 0.0                     # 1H markets have 0% fees
  momentum_trigger_threshold_pct: 0.001  # PRIMARY: 0.1% momentum trigger
  pump_exit_threshold_pct: 0.03     # Exit if one side pumps 3%
  max_hold_time_sec: 300            # Force exit after 5 minutes

# Risk management
risk:
  max_consecutive_losses: 3    # Stop after 3 consecutive losses
  max_daily_loss_usd: 100      # Stop after $100 daily loss
  cooldown_after_loss_sec: 300 # Pause 5 min after loss
  max_total_exposure: 1000     # Max USDC across all positions

# Market filters
filters:
  min_liquidity_usd: 1000      # Minimum market liquidity
  min_book_depth: 500          # Minimum order book depth
  max_spread_pct: 0.05         # Maximum bid-ask spread (5%)
  max_market_age_hours: 1      # Prefer markets < 1 hour old
  fallback_age_hours: 24       # Fallback to 24h if no recent
  min_volume_24h: 100          # Minimum 24h volume in USDC
  market_types:                # Market slugs to track
    - btc-updown
    - eth-updown
```

### CLI Arguments

```bash
python -m src.main \
  --config config/default.yaml \  # Path to YAML config
  --live \                        # Enable live trading (overrides dry_run)
  --min-spread 0.02 \             # Override min spread
  --min-net-profit 0.005 \
  --max-position 100 \
  --interval 5.0 \
  --max-markets 100 \
  --batch-size 50 \
  --strategy lag_arb \            # "conservative" or "lag_arb"
  -v, --verbose                   # Enable debug logging
```

## Dashboard

The React dashboard provides real-time monitoring at `http://localhost:3000`:

- **Metrics Panel**: Total P&L, trades, opportunities
- **Control Panel**: Start/stop bot, view uptime, PID
- **Config Panel**: View and edit configuration live
- **Markets Panel**: Active markets with bid/ask prices
- **Lag Windows Panel**: Active arbitrage windows (lag_arb only)
- **Signal Feed**: Real-time event stream
- **P&L Chart**: Historical profit/loss
- **Activity Chart**: Trades by exit reason

## API Endpoints

The FastAPI server runs on port 8000:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/status` | GET | Bot status (running, PID, uptime) |
| `/api/metrics` | GET | Full metrics + visibility data |
| `/api/config` | GET | Current configuration |
| `/api/config` | PUT | Update configuration |
| `/api/restart` | POST | Restart bot (SIGTERM) |
| `/api/refresh-markets` | POST | Force market refresh (SIGUSR1) |
| `/api/ws/metrics` | WS | Real-time metrics stream |

## Production Deployment (Kubernetes)

### 1. Add to ArgoCD

In your infra repo, add to `base/argocd/apps.yaml`:

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

### 3. Enable Live Trading

Edit `k8s/configmap.yaml`:

```yaml
data:
  dry_run: "false"
```

### Quick Commands

```bash
# View logs
kubectl logs -f deployment/polymarket-arb-bot

# Check status
kubectl get pods -l app=polymarket-arb-bot

# Restart
kubectl rollout restart deployment/polymarket-arb-bot

# Scale down (pause)
kubectl scale deployment/polymarket-arb-bot --replicas=0
```

## Getting Polymarket Credentials

1. Go to [reveal.polymarket.com](https://reveal.polymarket.com)
2. Connect your wallet
3. Export your private key
4. Your funder address is your Polymarket deposit address

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
├── dashboard/              # React frontend
├── config/                 # YAML configuration
├── docker/                 # Docker support files
├── k8s/                    # Kubernetes manifests
├── Dockerfile              # Production image
└── docker-compose.yaml     # Local development
```

## Risks & Caveats

1. **Execution risk** — Prices can move before orders fill
2. **Fees** — Standard markets charge ~2% fees (1H markets are 0%)
3. **Liquidity** — Low liquidity may prevent fills
4. **Rate limits** — APIs have rate limits
5. **Geographic restrictions** — Polymarket not available everywhere
6. **Lag arbitrage risk** — Momentum may reverse before exit

## License

MIT
