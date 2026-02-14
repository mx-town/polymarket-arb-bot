# Polymarket Late-Entry Bot

## Overview

~400-line Python bot that buys the favorite side of 15m crypto Up/Down markets in the last 4 minutes before resolution. Polling-based, no WebSocket, no dashboard.

## Architecture

```
src/late_entry/
├── __init__.py   → Version + public API
├── bot.py        → Main polling loop (load config, tick every 10s)
├── data.py       → Market discovery (Gamma API) + CLOB price fetching
├── strategy.py   → Entry/exit logic (late-entry + take-profit)
└── executor.py   → ClobClient init + order placement
config.yaml       → All tunable parameters
logs/             → Log files, ever run has its own file
```

Uses **src layout** with `hatchling` build backend. Package is `late_entry`.

## How It Works

1. Every 10s, fetch active 15m markets from Gamma API (`/events?series_id=...`)
2. For each market in the last 4 minutes: fetch order book prices
3. If favorite leads by 10%+ and price < 0.75, buy the favorite
4. Exit on 15% take-profit or 30s before resolution

## Config

- `trading.dry_run` — no real orders (default: true)
- `trading.max_position_size` — max USDC per trade
- `late_entry.entry_window_sec` — how early to enter (240 = 4 min)
- `late_entry.min_favorite_spread` — minimum lead for favorite
- `late_entry.max_favorite_price` — don't overpay
- `late_entry.take_profit_pct` — exit target

## Running

```bash
uv sync
uv run late-entry          # dry-run mode
DRY_RUN=false uv run late-entry  # live (requires .env credentials)
```

## Env Vars (.env)

- `POLYMARKET_PRIVATE_KEY` — wallet key from reveal.polymarket.com
- `POLYMARKET_FUNDER_ADDRESS` — deposit address
- `DRY_RUN` — override config.yaml dry_run setting

## Coding Conventions

- src layout: all code under `src/late_entry/`
- `logging` module with descriptive key=value messages
- No classes — plain functions + dicts
- Minimal dependencies
