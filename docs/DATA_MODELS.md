# Data Models Reference

> For agents implementing the dashboard. Shows existing Python models and new persistence schema.

## Existing Python Models (`src/complete_set/models.py`)

### GabagoolMarket
```python
@dataclass(frozen=True)
class GabagoolMarket:
    slug: str                # "btc-updown-15m-{epoch}"
    up_token_id: str         # hex token ID for UP outcome
    down_token_id: str       # hex token ID for DOWN outcome
    end_time: float          # epoch seconds (resolution time)
    market_type: str         # "updown-15m"
    condition_id: str        # for on-chain merge/redeem
    neg_risk: bool           # NegRisk market flag
```

### MarketInventory
```python
@dataclass
class MarketInventory:
    up_shares: Decimal           # on-chain UP balance
    down_shares: Decimal         # on-chain DOWN balance
    up_cost: Decimal             # total USDC spent on UP
    down_cost: Decimal           # total USDC spent on DOWN
    filled_up_shares: Decimal    # from fills only (not chain sync)
    filled_down_shares: Decimal
    last_up_fill_at: float
    last_down_fill_at: float
    last_merge_at: float
    entry_dynamic_edge: Decimal
    prior_merge_pnl: Decimal

    # Properties:
    up_vwap: Decimal      # up_cost / up_shares
    down_vwap: Decimal    # down_cost / down_shares
    imbalance: Decimal    # up_shares - down_shares
```

### OrderState
```python
@dataclass(frozen=True)
class OrderState:
    order_id: str
    market: GabagoolMarket
    token_id: str
    direction: Direction       # UP or DOWN
    price: Decimal
    size: Decimal
    placed_at: float
    side: str                  # "BUY" or "SELL"
    matched_size: Decimal
    seconds_to_end_at_entry: int
    reserved_hedge_notional: Decimal
    entry_dynamic_edge: Decimal
```

### TopOfBook
```python
@dataclass(frozen=True)
class TopOfBook:
    best_bid: Decimal | None
    best_ask: Decimal | None
    best_bid_size: Decimal | None
    best_ask_size: Decimal | None
    updated_at: float
```

## New Persistence Schema (SQLAlchemy Core)

### btc_prices
| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | auto |
| ts | Float | Unix epoch, indexed |
| price | Float | BTC/USD |
| open_price | Float | Window open |
| high | Float | |
| low | Float | |
| deviation | Float | From window open |
| range_pct | Float | (high-low)/open |

### probability_snapshots
| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | auto |
| ts | Float | Unix epoch |
| market_slug | String(120) | Composite index with ts |
| up_bid | Float | |
| up_ask | Float | |
| down_bid | Float | |
| down_ask | Float | |
| edge | Float | 1 - (up_ask + down_ask) |

### trades
| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | auto |
| ts | Float | indexed |
| market_slug | String(120) | indexed |
| event_type | String(30) | entry/fill/hedge/merge/cancel/abandon |
| direction | String(10) | UP/DOWN |
| side | String(10) | BUY/SELL |
| price | Float | |
| shares | Float | |
| reason | String(50) | SH_ENTRY, MR_ENTRY, etc |
| btc_price_at | Float | BTC price at event time |
| order_id | String(80) | |
| tx_hash | String(80) | For merges |

### pnl_snapshots
| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | auto |
| ts | Float | indexed |
| realized | Float | |
| unrealized | Float | |
| total | Float | |
| exposure | Float | |
| exposure_pct | Float | |
| session_id | String(50) | Groups by bot run |

### market_windows
| Column | Type | Notes |
|--------|------|-------|
| id | Integer PK | auto |
| slug | String(120) | unique |
| market_type | String(30) | |
| end_time | Float | |
| up_token_id | String(120) | |
| down_token_id | String(120) | |
| entered_at | Float | |
| exited_at | Float | |
| outcome | String(30) | merged/unhedged_loss/partial/no_activity |
| total_pnl | Float | |

### sessions
| Column | Type | Notes |
|--------|------|-------|
| id | String(50) PK | UUID |
| started_at | Float | |
| ended_at | Float | |
| mode | String(10) | dry/live |
| config_snapshot | Text | JSON |
| user_id | String(50) | Future: multi-tenant |

## WebSocket Payload Shapes (TypeScript)

```typescript
interface TickSnapshot {
  type: 'tick_snapshot';
  ts: number;
  data: {
    markets: MarketState[];
    exposure: ExposureBreakdown;
    pnl: PnLState;
    bankroll: BankrollState;
  };
}

interface MarketState {
  slug: string;
  seconds_to_end: number;
  up_bid: number; up_ask: number;
  down_bid: number; down_ask: number;
  edge: number;
  position: {
    up_shares: number; down_shares: number;
    up_vwap: number; down_vwap: number;
    hedged: number; imbalance: number;
    unrealized_pnl: number;
  } | null;
  orders: OrderInfo[];
}

interface BtcPrice {
  type: 'btc_price';
  ts: number;
  data: {
    price: number;
    open: number; high: number; low: number;
    deviation: number;
    range_pct: number;
  };
}

interface TradeEvent {
  type: 'order_filled' | 'order_placed' | 'hedge_complete' | 'merge_complete';
  ts: number;
  data: {
    slug: string;
    direction: 'UP' | 'DOWN';
    side?: 'BUY' | 'SELL';
    price?: number;
    shares?: number;
    edge?: number;
    tx_hash?: string;
  };
}
```
