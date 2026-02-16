# Polymarket Arb Bot

## Overview

Multi-strategy Polymarket trading bot targeting crypto Up/Down markets. Three strategies (complete-set arb, trend-rider, observer) as separate packages sharing a src layout.

## Architecture

```
src/complete_set/    → Complete-set arb strategy (buy both sides, merge for profit)
src/trend_rider/     → Trend-following strategy (directional bets on momentum)
src/observer/        → Observation bot (reverse-engineer competitor strategies)
config.yaml          → All tunable parameters
logs/                → Log files, each run has its own file
```

Uses **src layout** with `hatchling` build backend.

## Running

```bash
uv sync
uv run complete-set      # complete-set arb
uv run trend-rider       # trend rider
uv run observer          # observer bot
```

## Env Vars (.env)

- `POLYMARKET_PRIVATE_KEY` — wallet key from reveal.polymarket.com
- `POLYMARKET_FUNDER_ADDRESS` — deposit address
- `DRY_RUN` — override config.yaml dry_run setting
- `ETHERSCAN_API_KEY` — for observer on-chain lookups
- `POLYGON_RPC_URL` — for observer receipt decoding and on-chain operations

## Coding Conventions

- src layout: all code under `src/<package>/`
- `logging` module with descriptive key=value messages
- No classes for strategy logic — plain functions + dicts (dataclasses for models OK)
- Minimal dependencies
