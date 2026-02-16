# Polymarket Arb Bot

## Overview

Multi-strategy Polymarket trading bot targeting crypto Up/Down markets on 5m/15m/1h timeframes. Three strategies (rebate-maker, grid-maker, observer) as separate packages sharing a src layout.

## Architecture

```
src/rebate_maker/    → Rebate-only market maker (post grids both sides, merge for rebates)
src/grid_maker/      → Grid market maker (configurable grid levels, compound mode)
src/observer/        → Observation bot (reverse-engineer competitor strategies)
src/shared/          → Shared modules (order_mgr, market_data, redeem, events, models)
config.yaml          → All tunable parameters
logs/                → Log files, each run has its own file
```

Uses **src layout** with `hatchling` build backend.

## Running

```bash
uv sync
uv run rebate-maker      # rebate-only market maker
uv run grid-maker        # grid market maker
uv run observer          # observer bot
```

## Env Vars (.env)

- `POLYMARKET_PRIVATE_KEY` — wallet key from reveal.polymarket.com
- `POLYMARKET_FUNDER_ADDRESS` — deposit address
- `DRY_RUN` — override config.yaml dry_run setting
- `ETHERSCAN_API_KEY` — for observer on-chain lookups
- `POLYGON_RPC_URL` — for observer receipt decoding and on-chain operations

## Rebate-Maker Strategy

Dual-sided passive GTC maker strategy (0% maker fee):
1. **Grid posting**: post GTC BUY grids on both Up and Down sides simultaneously
2. **Fill collection**: collect maker fills on both sides through grid levels
3. **Merge**: when both sides filled and balanced → on-chain merge for $1/pair, profit = rebate + (1 - up_vwap - down_vwap - gas)
4. **Repricing**: every tick, if best_bid changed → cancel + repost at new level (downward only)
- All orders are GTC maker (never FOK/taker)
- No signal-based entries — pure rebate collection

## Coding Conventions

- src layout: all code under `src/<package>/`
- `logging` module with descriptive key=value messages
- No classes for strategy logic — plain functions + dicts (dataclasses for models OK)
- Minimal dependencies

## Gabagool Reverse Engineering

Observing competitor "gabagool" (`0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d`) via `src/observer/`.
Data stored in `data/observer.db` (tables: `obs_sessions`, `obs_trades`, `obs_merges`, `obs_positions`, `obs_position_changes`, `obs_market_windows`, `obs_prices`, `obs_redemptions`, `obs_book_snapshots`).

**Confirmed findings** (2 sessions, 40K trades, 147 markets, $168K volume, 6 hours):
- **Static full-range grid**: $0.01-$0.99 at every cent, BOTH Up+Down simultaneously (not ~30 levels — full book)
- **Fixed 26 shares/level**: max fill always 26.0, notional scales with price naturally
- **88% MAKER** ($3.85 avg fill), 12% TAKER ($6.89 avg) — taker fills used for rebalancing
- Enters both sides within **2-5 seconds** of market discovery (fire-and-forget, no repricing)
- **100% BUY**, exit only via merge/redemption. Zero sell trades observed.
- **Batch merges** every ~60 min (4-5 markets per batch, not per-market eager)
- Combined VWAP ~0.986 → **1.38% net edge** → ~$2,227 gross in 6 hrs
- Win rate: **72%** of markets. Winners avg +3%, losers avg -1.7%
- **BTC:ETH ratio 4.1:1**. All timeframes (5m:79, 15m:54, 1h:14 markets)
- Position scale: $500-$2K per market

**Analysis artifacts**: Deep dive script (`src/observer/deep_dive.py`), HTML report (`data/analysis/deep_dive_report.html`), session reports (`data/analysis/session_*.md`), strategy plan (`docs/STRATEGY_PLAN.md`).
