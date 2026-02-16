# Polymarket Arb Bot

## Overview

Multi-strategy Polymarket trading bot targeting crypto Up/Down markets on 5m/15m/1h timeframes. Three strategies (complete-set arb, trend-rider, observer) as separate packages sharing a src layout.

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

## CS Strategy Mechanics

Two-phase asymmetric GTC maker strategy (0% maker fee):
1. **First leg**: signal (stop-hunt or mean-reversion) fires → post GTC BUY at `bid+0.01` on cheap side
2. **Hedge leg**: after first fill, post GTC BUY at `bid+0.01` on opposite side if `first_vwap + maker_price < 1 - edge`
3. **Merge**: when both legs filled and balanced → on-chain merge for $1/pair, profit = `1 - up_vwap - down_vwap - gas`
4. **Repricing**: every tick, if best_bid changed → cancel + repost at new `bid+0.01` (downward only; upward = chase cancel)
- All orders are GTC maker (never FOK/taker for entries or hedges)
- Entry signals: stop-hunt (BTC range deviation, early window) and mean-reversion (price deviation, late window)
- Chase protection: upward reprices cancelled, price cap set; only downward reprices allowed
- Abandon sell: deeply negative unhedged positions sold at bid in last 60s

## Coding Conventions

- src layout: all code under `src/<package>/`
- `logging` module with descriptive key=value messages
- No classes for strategy logic — plain functions + dicts (dataclasses for models OK)
- Minimal dependencies

## Gabagool Reverse Engineering

Observing competitor "gabagool" (`0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d`) via `src/observer/`.
Data stored in `data/observer.db` (tables: `obs_sessions`, `obs_trades`, `obs_merges`, `obs_positions`, `obs_position_changes`, `obs_market_windows`).

**Current hypothesis** (from 1 session, 33K trades, 136 markets, $166K volume):
- Dual-sided passive market maker + complete-set merge
- 86% MAKER fills, posts limit grids on both Up and Down simultaneously (~30 price levels per side)
- Builds $1K-2K positions through 200+ small fills per market (avg $4-5 each)
- Enters both sides within 5-10 seconds, combined VWAP averaging ~0.985
- 100% BUY (never sells), exits via merge/redemption only
- 3:1 BTC preference over ETH, trades all timeframes (5m/15m/1h)
- Operates at ~50-100x our scale

**Still needed**: multiple sessions across days, proper merge tx capture (`obs_merges` currently empty), order book snapshots to see his full ladder shape.
