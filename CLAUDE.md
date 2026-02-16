# Polymarket Arb Bot

## Overview

Polymarket trading bot targeting crypto Up/Down markets on 5m/15m/1h timeframes. Two packages (grid-maker, observer) sharing a src layout. Grid-maker is a reverse-engineered clone of competitor "gabagool".

## Architecture

```
src/grid_maker/      → Grid market maker (static penny-grid, gabagool clone)
src/observer/        → Observation bot (reverse-engineer competitor strategies)
src/shared/          → Shared modules (order_mgr, market_data, redeem, events, models)
config.yaml          → All tunable parameters
logs/                → Log files, each run has its own file
```

Uses **src layout** with `hatchling` build backend.

## Running

```bash
uv sync
uv run grid-maker        # grid market maker
uv run observer          # observer bot
```

## Env Vars (.env)

- `POLYMARKET_PRIVATE_KEY` — wallet key from reveal.polymarket.com
- `POLYMARKET_FUNDER_ADDRESS` — deposit address
- `DRY_RUN` — override config.yaml dry_run setting
- `ETHERSCAN_API_KEY` — for observer on-chain lookups
- `POLYGON_RPC_URL` — for observer receipt decoding and on-chain operations

## Grid-Maker Strategy (Gabagool Clone)

Static full-range penny-grid market maker:
1. **Grid posting**: post GTC BUY grids $0.01-$0.99 at every cent, both Up+Down, 26 shares/level
2. **Fill collection**: collect fills passively; replenish consumed levels (fire-and-forget, no repricing)
3. **Batch merge**: sweep all markets every ~60 min, merge balanced pairs on-chain for $1/pair
4. **Redemption**: redeem winning positions after market expiry
- All orders are GTC (no post_only) — organic taker fills happen when GTC crosses the ask
- No deliberate taker/FOK orders, no dynamic grid, no eager merge
- Entry delay: 5s after first seeing a market
- Orders ride through market expiry — no TIME_UP cancellation

## Coding Conventions

- src layout: all code under `src/<package>/`
- `logging` module with descriptive key=value messages
- No classes for strategy logic — plain functions + dicts (dataclasses for models OK)
- Minimal dependencies

## Gabagool Reverse Engineering

Observing competitor "gabagool" (`0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d`) via `src/observer/`.
Data stored in `data/observer.db` (tables: `obs_sessions`, `obs_trades`, `obs_merges`, `obs_positions`, `obs_position_changes`, `obs_market_windows`, `obs_prices`, `obs_redemptions`, `obs_book_snapshots`).

**Confirmed findings** (3 sessions, 65K trades, 242 markets, $280K volume, 10.8 hours):
- **Static full-range grid**: $0.01-$0.99 at every cent, BOTH Up+Down simultaneously
- **Fixed 26 shares/level**: max fill always 26.0, notional scales with price naturally
- **87% MAKER** ($3.86 avg fill), 13% TAKER ($6.98 avg) — taker fills are organic GTC crossings
- Enters both sides within **10-30 seconds** of market discovery (fire-and-forget, no repricing)
- **100% BUY**, exit only via merge/redemption. Zero sell trades observed.
- **Batch merges** every ~60 min (4-5 markets per batch, not per-market eager)
- Combined VWAP ~0.9812 → **1.88% avg edge**, win rate 74%
- **BTC:ETH ratio 3.3:1**. Timeframes: 5m, 15m, 1h
- Position scale: $500-$2K per market

**Analysis artifacts**: Deep dive script (`src/observer/deep_dive.py`), HTML report (`data/analysis/deep_dive_report.html`), session reports (`data/analysis/session_*.md`), strategy plan (`docs/STRATEGY_PLAN.md`).
