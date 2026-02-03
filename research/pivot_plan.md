# Polymarket BTC 15-Minute Binary Arbitrage Bot
## Infrastructure & Data Layer Specification v2.0

**Objective:** Automated arbitrage on Polymarket's BTC 15-minute UP/DOWN binary markets via lag exploitation, Dutch Book opportunities, and momentum-based directional trades.

**Target Win Rate:** 95-98% (benchmark from documented successful bots)
**Minimum Edge Required:** 2.5-3% after fees

---

## 1. Market Mechanics

### 1.1 Resolution Source
```
Primary: Chainlink Data Streams (NOT traditional Data Feeds)
Mechanism: Market resolves "UP" if end_price ≥ start_price
Settlement: Chainlink Automation triggers on-chain at preset intervals
Chain: Polygon PoS
```

### 1.2 Fee Structure
| Probability | Taker Fee | Break-even Edge |
|-------------|-----------|-----------------|
| 50% | ~3% | 5%+ |
| 10%/90% | ~1% | 2%+ |
| 1%/99% | ~0% | 0.5%+ |

**Implication:** Opportunities near 50/50 require larger edges. Exploit extremes where fees approach zero.

### 1.3 Contract Addresses (Polygon)
```
Chainlink BTC/USD Aggregator: 0xc907E116054Ad103354f2D350FD2514433D57F6f
USDC: 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
CTF Exchange: 0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
Neg Risk CTF Exchange: 0xC5d563A36AE78145C45a50134d48A1215220f80a
Settlement (Legacy): 0x56C79347e95530c01A2FC76E732f9566dA16E113
```

### 1.4 Market Identifiers
```
Series ID: 10192
Series Slug: btc-up-or-down-15m
```

---

## 2. Data Layer Architecture

### 2.1 WebSocket Feeds

#### 2.1.1 Polymarket RTDS (Real-Time Data Stream)
```
Endpoint: wss://ws-live-data.polymarket.com/ws
Protocol: JSON over WebSocket
```

**Subscription format:**
```json
{
  "action": "subscribe",
  "subscriptions": [
    {"topic": "crypto_prices", "type": "update", "filters": "btcusdt"},
    {"topic": "crypto_prices_chainlink", "type": "*", "filters": ""}
  ]
}
```

**Critical constraint:** `crypto_prices` channel supports only ONE symbol per connection. Multiple symbols require multiple connections.

**Channels:**
| Channel | Source | Purpose |
|---------|--------|---------|
| `crypto_prices` | Binance spot | Real-time reference (NOT resolution) |
| `crypto_prices_chainlink` | Chainlink oracle | Resolution source - THIS IS TRUTH |

#### 2.1.2 CLOB WebSocket (Order Book)
```
Endpoint: wss://ws-subscriptions-clob.polymarket.com/ws/
Auth: Required for user channel
```

**Subscription format:**
```json
{
  "type": "subscribe",
  "channel": "market",
  "markets": ["<condition_id>"]
}
```

**Events:**
- `book` - Full order book snapshot
- `price_change` - Best bid/ask updates
- `tick_size_change` - Minimum tick updates
- `last_trade_price` - Recent trades

#### 2.1.3 Binance Direct (Reference Signal)
```
Endpoint: wss://stream.binance.com:9443/ws/btcusdt@trade
Backup: wss://stream.binance.com:9443/ws/btcusdt@aggTrade
```

**Use case:** Leading indicator. Binance moves BEFORE Chainlink updates. Lag window: 2-5 seconds.

#### 2.1.4 Chainlink On-Chain (Fallback/Verification)
```
Aggregator: 0xc907E116054Ad103354f2D350FD2514433D57F6f
RPC: https://polygon-rpc.com (primary)
     https://rpc.ankr.com/polygon (backup)
     wss://polygon-bor-rpc.publicnode.com (WSS)
```

**Aggregator interface:**
```solidity
function latestRoundData() returns (
  uint80 roundId,
  int256 answer,      // Price * 10^8
  uint256 startedAt,
  uint256 updatedAt,
  uint80 answeredInRound
)
```

**Update triggers:**
- Deviation threshold: 0.1%
- Heartbeat: ~60 seconds (Polygon-specific)

### 2.2 REST APIs

#### 2.2.1 CLOB API
```
Base: https://clob.polymarket.com
```

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/book` | GET | No | Order book snapshot |
| `/midpoint` | GET | No | Current midpoint price |
| `/price` | GET | No | Best bid/ask |
| `/orders` | POST | L2 | Place order |
| `/orders/{id}` | DELETE | L2 | Cancel order |

#### 2.2.2 Gamma API (Market Discovery)
```
Base: https://gamma-api.polymarket.com
```

| Endpoint | Purpose |
|----------|---------|
| `/events` | List all events |
| `/events?slug=btc-up-or-down-15m` | Current 15-min BTC markets |
| `/markets` | Market details with condition IDs |

### 2.3 Rate Limits
| Endpoint | Limit |
|----------|-------|
| `/order` | 3000 requests / 10 minutes |
| Public endpoints | 100 requests / minute |
| Trading endpoints | 60 orders / minute |

### 2.4 Data Flow Diagram
```
┌─────────────────────────────────────────────────────────────────┐
│                        DATA INGESTION                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Binance WS ──────┐                                             │
│  (btcusdt@trade)  │     ┌──────────────────┐                    │
│                   ├────►│                  │                    │
│  RTDS WS ─────────┤     │  Price Aligner   │                    │
│  (crypto_prices)  │     │  & Normalizer    │                    │
│                   ├────►│                  │                    │
│  RTDS WS ─────────┤     │  - Timestamp     │     ┌───────────┐  │
│  (chainlink)      ├────►│  - Deduplication │────►│  Feature  │  │
│                   │     │  - Validation    │     │  Store    │  │
│  Chainlink RPC ───┘     └──────────────────┘     │  (Ring    │  │
│  (fallback)                                      │  Buffer)  │  │
│                                                  └─────┬─────┘  │
│  CLOB WS ─────────────────────────────────────────────►│        │
│  (order book)                                          │        │
│                                                        ▼        │
└────────────────────────────────────────────────────────┴────────┘
                                                         │
                                                         ▼
┌─────────────────────────────────────────────────────────────────┐
│                      FEATURE EXTRACTION                         │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐              │
│  │   Price     │  │   Order     │  │   Time      │              │
│  │   Features  │  │   Book      │  │   Features  │              │
│  │             │  │   Features  │  │             │              │
│  │ • deviation │  │ • spread    │  │ • t_remain  │              │
│  │ • momentum  │  │ • depth     │  │ • t_elapsed │              │
│  │ • velocity  │  │ • imbalance │  │ • session   │              │
│  │ • lag_delta │  │ • vwap_ask  │  │ • candle_   │              │
│  └──────┬──────┘  └──────┬──────┘  │   phase     │              │
│         │                │         └──────┬──────┘              │
│         └────────────────┼────────────────┘                     │
│                          ▼                                      │
│                 ┌─────────────────┐                             │
│                 │  Feature Vector │                             │
│                 │  (normalized)   │                             │
│                 └────────┬────────┘                             │
│                          │                                      │
└──────────────────────────┼──────────────────────────────────────┘
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│                      SIGNAL GENERATION                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌───────────────┐  ┌───────────────┐  ┌───────────────┐        │
│  │  Dutch Book   │  │  Lag Arb      │  │  Momentum     │        │
│  │  Detector     │  │  Detector     │  │  Detector     │        │
│  │               │  │               │  │               │        │
│  │ UP+DOWN<$1.00 │  │ Binance leads │  │ Directional   │        │
│  │ guaranteed    │  │ Chainlink     │  │ with edge     │        │
│  │ profit        │  │ by 2-5s       │  │ confirmation  │        │
│  └───────┬───────┘  └───────┬───────┘  └───────┬───────┘        │
│          │                  │                  │                │
│          └──────────────────┼──────────────────┘                │
│                             ▼                                   │
│                    ┌─────────────────┐                          │
│                    │ Signal Arbiter  │                          │
│                    │ (priority queue)│                          │
│                    └────────┬────────┘                          │
│                             │                                   │
└─────────────────────────────┼───────────────────────────────────┘
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       EXECUTION LAYER                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                    Order Manager                        │    │
│  │                                                         │    │
│  │  • FOK (Fill-or-Kill) orders only                       │    │
│  │  • Ask-book traversal for execution pricing             │    │
│  │  • Depth-aware position sizing                          │    │
│  │  • Paired execution verification                        │    │
│  │  • Automatic unwind on partial fills                    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                             │                                   │
│                             ▼                                   │
│                    ┌─────────────────┐                          │
│                    │   py-clob-client│                          │
│                    │   (web3==6.14.0)│                          │
│                    └─────────────────┘                          │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. Feature Extraction Pipeline

### 3.1 Price Features

#### 3.1.1 Deviation from Open
```python
deviation_pct = (current_price - open_price) / open_price * 100
```
**Resolution relevance:** Direct input to P(UP) calculation. Positive deviation → higher P(UP).

#### 3.1.2 Binance-Chainlink Lag Delta
```python
lag_delta = binance_price - chainlink_price
lag_pct = lag_delta / chainlink_price * 100
```
**Signal:** When |lag_pct| > 0.05% and sustained for >500ms, Chainlink update imminent.

#### 3.1.3 Price Velocity (5-second window)
```python
velocity = (price_t - price_t_minus_5s) / 5.0  # $/second
acceleration = (velocity_t - velocity_t_minus_5s) / 5.0
```
**Momentum signal:** velocity > threshold AND acceleration > 0 → trend continuation likely.

#### 3.1.4 Realized Volatility
```python
returns = [log(p[i]/p[i-1]) for i in range(1, len(prices))]
realized_vol = std(returns) * sqrt(intervals_per_15min)
```
**Use:** Adjusts position sizing and probability model confidence.

### 3.2 Order Book Features

#### 3.2.1 Spread Analysis
```python
spread = best_ask - best_bid
spread_bps = spread / midpoint * 10000
```

#### 3.2.2 Ask Book Traversal (Critical for Execution)
```python
def get_executable_price(book_asks, target_size):
    """
    Walk the ask book to find actual execution price.
    DO NOT use last_trade_price or best_ask alone.
    """
    filled = 0
    total_cost = 0
    for price, size in sorted(book_asks):
        take = min(size, target_size - filled)
        total_cost += take * price
        filled += take
        if filled >= target_size:
            break
    return total_cost / filled if filled > 0 else None
```

#### 3.2.3 Book Imbalance
```python
bid_depth = sum(size for price, size in bids[:5])
ask_depth = sum(size for price, size in asks[:5])
imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)
```
**Range:** [-1, 1]. Positive → buy pressure. Negative → sell pressure.

#### 3.2.4 VWAP (Ask-side for buying)
```python
def vwap_ask(book_asks, depth_usd):
    """Volume-weighted average price for buying depth_usd worth."""
    filled_value = 0
    filled_size = 0
    for price, size in sorted(book_asks):
        value_at_level = size * price
        if filled_value + value_at_level >= depth_usd:
            remaining = depth_usd - filled_value
            filled_size += remaining / price
            filled_value = depth_usd
            break
        filled_value += value_at_level
        filled_size += size
    return filled_value / filled_size if filled_size > 0 else None
```

### 3.3 Time Features

#### 3.3.1 Time Remaining
```python
t_remaining_sec = resolution_timestamp - current_timestamp
t_remaining_pct = t_remaining_sec / 900  # 900s = 15min
```

#### 3.3.2 Candle Phase
```python
t_elapsed_sec = current_timestamp - open_timestamp
candle_phase = t_elapsed_sec / 900  # 0.0 = open, 1.0 = close
```

**Turn-of-candle anomaly:** Positive returns concentrate at candle boundaries (phase ~0.0 and ~1.0).

#### 3.3.3 Trading Session
```python
def get_session(utc_hour):
    if 0 <= utc_hour < 8:
        return "ASIA"
    elif 8 <= utc_hour < 13:
        return "EUROPE"
    elif 13 <= utc_hour < 17:
        return "US_EU_OVERLAP"  # Peak volatility
    elif 17 <= utc_hour < 21:
        return "US"
    else:
        return "LATE_US"
```

### 3.4 Composite Features

#### 3.4.1 Empirical P(UP) Lookup
```python
def lookup_p_up(deviation_pct, t_remaining_sec, volatility_tercile, session):
    """
    Lookup from pre-computed probability table.
    Built from 6+ months of Binance historical data.
    
    Returns: (p_up, confidence, sample_size)
    """
    bucket = get_bucket(deviation_pct, t_remaining_sec, volatility_tercile, session)
    return probability_table[bucket]
```

**Bucket dimensions:**
- Deviation: 0.05% increments from -2% to +2%
- Time remaining: 30-second increments
- Volatility: terciles (low/medium/high)
- Session: 5 categories

**Minimum sample size per bucket:** 50 observations for statistical validity.

#### 3.4.2 Fair Value vs Market Price
```python
p_up_empirical, confidence, n = lookup_p_up(...)
fair_value_up = p_up_empirical  # In $, since shares pay $1
market_price_up = get_executable_price(up_asks, target_size)
market_price_down = get_executable_price(down_asks, target_size)

edge_up = fair_value_up - market_price_up
edge_down = (1 - p_up_empirical) - market_price_down
```

---

## 4. Signal Generation

### 4.1 Strategy Tier 1: Dutch Book Arbitrage (Zero Risk)

**Trigger condition:**
```python
up_ask = get_executable_price(up_book_asks, size)
down_ask = get_executable_price(down_book_asks, size)
total_cost = up_ask + down_ask

if total_cost < 0.99:  # Guaranteed profit >1%
    signal = DUTCH_BOOK_ARB
    expected_profit = (1.0 - total_cost) * size
```

**Execution requirements:**
- Simultaneous FOK orders for both sides
- Verify both fills before marking success
- Unwind immediately if one leg fails

**Expected frequency:** Rare (milliseconds duration when occurs). Requires sub-100ms detection.

### 4.2 Strategy Tier 2: Lag Arbitrage (Low Risk)

**Trigger condition:**
```python
binance_deviation = (binance_price - open_price) / open_price
chainlink_deviation = (chainlink_price - open_price) / open_price
lag = binance_deviation - chainlink_deviation

# Binance has moved but Chainlink hasn't updated yet
if abs(lag) > 0.001 and lag_sustained_ms > 500:  # 0.1% lag for 500ms
    if lag > 0:  # Binance UP, Chainlink will follow
        signal = LAG_ARB_BUY_UP
    else:
        signal = LAG_ARB_BUY_DOWN
```

**Edge calculation:**
```python
# If Binance is 0.15% above open but market prices UP at only 52%
p_up_implied_by_binance = lookup_p_up(binance_deviation, t_remaining, ...)
market_price_up = 0.52
edge = p_up_implied_by_binance - market_price_up

if edge > 0.03:  # 3% minimum edge
    execute_signal()
```

**Optimal lag window:** 2-5 seconds (from empirical research).

### 4.3 Strategy Tier 3: Momentum/Directional (Medium Risk)

**Trigger condition:**
```python
velocity_5s = calculate_velocity(prices, window=5)
acceleration = calculate_acceleration(velocities, window=5)

# Strong momentum with confirmation
if velocity_5s > VELOCITY_THRESHOLD:
    if acceleration > 0:  # Accelerating
        if book_imbalance > 0.3:  # Buy pressure
            signal = MOMENTUM_UP
```

**Additional filters:**
- Minimum time remaining: 60 seconds (avoid late-market noise)
- Volatility check: Don't trade in extreme volatility spikes
- Session filter: Prefer US_EU_OVERLAP for liquidity

### 4.4 Strategy Tier 4: Flash Crash Contrarian (High Risk/Reward)

**Trigger condition:**
```python
price_10s_ago = get_price(t - 10)
current_price = get_price(t)
drop_pct = (price_10s_ago - current_price) / price_10s_ago

if drop_pct > 0.30:  # >30% drop in 10 seconds
    signal = FLASH_CRASH_CONTRARIAN
    # Buy the crashed side expecting mean reversion
```

**From vladmeer repo:** Uses 10-second windows, 30% drop threshold.

### 4.5 Asymmetric Hedging (Gabagool Method)

**Different from Dutch Book:** Does NOT buy both sides simultaneously.

**Logic:**
```python
# Track prices over time
if up_price_now < up_price_5min_ago * 0.95:  # UP side dropped 5%
    buy_up_position()
    # Wait for DOWN to misprice
    
if down_price_now < down_price_5min_ago * 0.95:  # DOWN dropped
    buy_down_position()

# Profit if combined cost < $1.00 (even if bought at different times)
total_cost = up_entry + down_entry
if total_cost < 1.00:
    guaranteed_profit = 1.00 - total_cost
```

**Advantage:** More opportunities than simultaneous Dutch Book.
**Risk:** Market can move against first leg before second leg fills.

---

## 5. Execution Layer

### 5.1 Order Types

**MANDATORY: Fill-or-Kill (FOK)**
```python
order = {
    "order_type": "FOK",  # CRITICAL: Never use GTC for arb
    "side": "BUY",
    "token_id": condition_id,
    "price": executable_price,
    "size": position_size
}
```

**Why FOK:**
- Prevents single-leg exposure in Dutch Book arb
- Ensures immediate fill or no fill
- Avoids stale orders in fast-moving markets

### 5.2 Position Sizing

**Depth-aware sizing:**
```python
def calculate_position_size(book_asks, max_slippage_bps=10):
    """
    Find maximum size that can execute within slippage tolerance.
    """
    best_ask = book_asks[0][0]
    max_price = best_ask * (1 + max_slippage_bps / 10000)
    
    executable_size = 0
    for price, size in book_asks:
        if price <= max_price:
            executable_size += size
        else:
            break
    
    return executable_size
```

### 5.3 Paired Execution (Dutch Book)

```python
async def execute_dutch_book(up_order, down_order):
    """
    Execute both legs. Unwind if either fails.
    """
    # Submit both simultaneously
    up_result, down_result = await asyncio.gather(
        submit_fok_order(up_order),
        submit_fok_order(down_order),
        return_exceptions=True
    )
    
    # Verify both filled
    up_filled = up_result.get('status') == 'FILLED'
    down_filled = down_result.get('status') == 'FILLED'
    
    if up_filled and down_filled:
        return SUCCESS
    
    # Partial fill - UNWIND
    if up_filled and not down_filled:
        await sell_position(up_result['position'])
    elif down_filled and not up_filled:
        await sell_position(down_result['position'])
    
    return FAILED_UNWOUND
```

### 5.4 Authentication Levels

| Level | Capability | Credential |
|-------|------------|------------|
| L0 | Public data only | None |
| L1 | API key creation | Private key |
| L2 | Trading | API key + secret |

**API Key Generation:**
```python
from py_clob_client.client import ClobClient

client = ClobClient(
    host="https://clob.polymarket.com",
    chain_id=137,  # Polygon
    key=private_key,
    signature_type=1  # EOA
)

# Creates API credentials derived from private key
api_creds = client.create_or_derive_api_creds()
```

### 5.5 Gasless Transactions (Builder Program)

Polymarket's Builder Program enables gasless order submission:
- Orders signed off-chain
- Relayer submits to chain
- No gas costs for traders

**Requires enrollment:** https://docs.polymarket.com

---

## 6. Latency Considerations

### 6.1 Latency Hierarchy
| Component | Typical Latency |
|-----------|-----------------|
| Binance WS → local | 10-50ms |
| Decision logic | 1-5ms |
| Order submission | 20-50ms |
| CLOB matching | 10-30ms |
| Polygon block | ~2000ms (floor) |
| **Total retail** | ~2650ms |
| **Total optimized** | ~2040ms |

### 6.2 VPS Requirements

**Location:** Closest to Polymarket infrastructure
- Primary: US East (AWS us-east-1, GCP us-east4)
- Polygon RPC: Use dedicated node or premium RPC

**Specs:**
- CPU: 2+ cores (async processing)
- RAM: 4GB+ (order book caching)
- Network: <10ms to Polygon RPC
- Uptime: 99.9%+

### 6.3 Detection Latency Targets

| Strategy | Detection Target | Execution Window |
|----------|------------------|------------------|
| Dutch Book | <50ms | Milliseconds |
| Lag Arb | <500ms | 2-5 seconds |
| Momentum | <1000ms | Seconds |
| Flash Crash | <100ms | 10+ seconds |

---

## 7. Risk Management

### 7.1 Position Limits
```python
MAX_POSITION_PER_MARKET = 1000  # USDC
MAX_TOTAL_EXPOSURE = 5000  # USDC
MAX_CONCURRENT_TRADES = 3
```

### 7.2 Loss Limits
```python
MAX_LOSS_PER_TRADE = 0.025  # 2.5% stop-loss
MAX_DAILY_LOSS = 0.10  # 10% of capital
HOLDING_TIME_LIMIT = 3600  # 1 hour max hold
```

### 7.3 Circuit Breakers
```python
# Halt trading if:
if consecutive_losses >= 5:
    halt("5 consecutive losses")

if daily_pnl < -MAX_DAILY_LOSS:
    halt("Daily loss limit reached")

if spread_bps > 500:  # 5% spread
    halt("Abnormal spread - market stress")
```

---

## 8. Dependencies

### 8.1 Python Packages
```
py-clob-client>=0.1.0
web3==6.14.0  # CRITICAL: Pin this version
websockets>=10.0
aiohttp>=3.8.0
numpy>=1.21.0
pandas>=1.3.0
python-dotenv>=0.19.0
cryptography>=3.4.0  # For Fernet key encryption
```

### 8.2 Key Version Constraints
- **web3 must be 6.14.0** - Later versions break py-clob-client
- Python 3.9+ required

---

## 9. Repos to Study

### 9.1 High Priority (Direct Relevance)

| Repo | URL | Study Focus |
|------|-----|-------------|
| gabagool222/15min-btc-polymarket-trading-bot | https://github.com/gabagool222/15min-btc-polymarket-trading-bot | FOK execution, ask book traversal, paired verification |
| vladmeer/polymarket-arbitrage-bot | https://github.com/vladmeer/polymarket-arbitrage-bot | Flash crash strategy, WebSocket patterns, 5-40ms detection |
| simone46b/polymarket-trading-bot | https://github.com/simone46b/polymarket-trading-bot | Oracle price arbitrage, TypeScript patterns, external signal integration |
| Trust412/Polymarket-spike-bot-v1 | https://github.com/Trust412/Polymarket-spike-bot-v1 | Multi-threaded architecture, spike detection thresholds |

### 9.2 Reference (Patterns & Libraries)

| Repo | URL | Study Focus |
|------|-----|-------------|
| Polymarket/py-clob-client | https://github.com/Polymarket/py-clob-client | Official Python client, auth patterns |
| Polymarket/clob-client | https://github.com/Polymarket/clob-client | TypeScript reference |
| warproxxx/poly-maker | https://github.com/warproxxx/poly-maker | Market making (note: author says "not profitable" now) |
| 0xalberto/polymarket-arbitrage-bot | https://github.com/0xalberto/polymarket-arbitrage-bot | Multi-market arb detection |

### 9.3 Chainlink Integration

| Repo | URL | Study Focus |
|------|-----|-------------|
| smartcontractkit/data-streams-sdk | https://github.com/smartcontractkit/data-streams-sdk | Official Data Streams SDK |
| NethermindEth/chainlink-push-engine | https://github.com/NethermindEth/chainlink-push-engine | Data Streams to on-chain bridge |

---

## 10. Empirical Probability Model

### 10.1 Data Collection

**Source:** Binance API historical klines
**Period:** 6+ months
**Granularity:** 1-second or tick data preferred, 1-minute minimum

**Collection script requirements:**
```python
# For each 15-minute candle:
# - Record open price, close price
# - Track price every second (or as available)
# - Calculate deviation at each timestamp
# - Record outcome (UP if close >= open, else DOWN)
```

### 10.2 Bucketing Strategy

**Dimensions:**
1. **Deviation:** -2.0% to +2.0% in 0.05% increments (80 buckets)
2. **Time remaining:** 0-900s in 30s increments (30 buckets)
3. **Volatility:** Low/Medium/High terciles (3 buckets)
4. **Session:** ASIA/EUROPE/US_EU_OVERLAP/US/LATE_US (5 buckets)

**Total buckets:** 80 × 30 × 3 × 5 = 36,000

**Sparse handling:** Many buckets will have <50 samples. Use smoothing or hierarchical fallback.

### 10.3 Probability Calculation

```python
def calculate_bucket_probability(observations):
    """
    Calculate P(UP) with Wilson confidence interval.
    """
    n = len(observations)
    if n < 50:
        return None, None, n  # Insufficient data
    
    wins = sum(1 for o in observations if o.outcome == 'UP')
    p = wins / n
    
    # Wilson score interval
    z = 1.96  # 95% confidence
    denominator = 1 + z**2/n
    center = (p + z**2/(2*n)) / denominator
    spread = z * sqrt((p*(1-p) + z**2/(4*n)) / n) / denominator
    
    return center, spread, n
```

### 10.4 Output Format

```csv
deviation_min,deviation_max,time_min,time_max,vol_tercile,session,p_up,confidence,sample_size
-0.05,0.00,0,30,low,US_EU_OVERLAP,0.48,0.03,156
0.00,0.05,0,30,low,US_EU_OVERLAP,0.52,0.03,162
...
```

---

## 11. Bitcoin Statistical Properties

### 11.1 Mean Reversion
- **Autocorrelation (15-min):** -0.0575
- **Interpretation:** Price moves tend to reverse, not continue
- **Strategy implication:** Contrarian signals have statistical backing

### 11.2 Turn-of-Candle Anomaly
- Positive returns concentrate at candle open/close boundaries
- **Phase 0.0-0.1 and 0.9-1.0:** Higher probability of directional moves
- **Strategy implication:** Weight signals higher near candle boundaries

### 11.3 Session Volatility
| Session | Relative Volatility |
|---------|---------------------|
| ASIA | Low |
| EUROPE | Medium |
| US_EU_OVERLAP | **High** (best for trading) |
| US | Medium-High |
| LATE_US | Low |

---

## 12. Monitoring & Logging

### 12.1 Metrics to Track

**Performance:**
- Win rate by strategy
- Average edge captured vs theoretical
- Execution slippage (expected vs actual fill)
- Latency percentiles (p50, p95, p99)

**Data quality:**
- WebSocket disconnection frequency
- Price feed staleness
- Order book depth over time

**Risk:**
- Current exposure
- Daily P&L
- Drawdown from peak

### 12.2 Alerting

**Critical alerts:**
- WebSocket disconnection >5 seconds
- API rate limit approaching (>80%)
- Execution failure
- Loss limit triggered

---

## 13. Implementation Phases

### Phase 1: Data Infrastructure
1. Implement multi-feed WebSocket manager
2. Build price alignment and normalization
3. Create feature extraction pipeline
4. Validate data quality

### Phase 2: Signal Generation
1. Implement Dutch Book detector
2. Implement Lag Arb detector
3. Build empirical probability model
4. Backtest on historical data

### Phase 3: Execution
1. Implement FOK order execution
2. Build paired execution for Dutch Book
3. Add position and risk management
4. Paper trade validation

### Phase 4: Production
1. Deploy to VPS
2. Start with minimal capital
3. Monitor and tune thresholds
4. Scale gradually

---

## Appendix A: Quick Reference

### WebSocket Endpoints
```
Polymarket RTDS: wss://ws-live-data.polymarket.com/ws
Polymarket CLOB: wss://ws-subscriptions-clob.polymarket.com/ws/
Binance Trades:  wss://stream.binance.com:9443/ws/btcusdt@trade
Polygon WSS:     wss://polygon-bor-rpc.publicnode.com
```

### REST Endpoints
```
CLOB API:  https://clob.polymarket.com
Gamma API: https://gamma-api.polymarket.com
Binance:   https://api.binance.com
```

### Contract Addresses (Polygon)
```
Chainlink BTC/USD: 0xc907E116054Ad103354f2D350FD2514433D57F6f
USDC:              0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174
CTF Exchange:      0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E
```

### Key Thresholds
```
Dutch Book trigger:    UP + DOWN < $0.99
Lag arb threshold:     0.1% deviation sustained 500ms
Momentum velocity:     0.1% in 5 seconds
Flash crash:           30% drop in 10 seconds
Minimum edge:          3% after fees
FOK order:             ALWAYS for arbitrage
```