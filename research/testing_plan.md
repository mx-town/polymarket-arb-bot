# Data Layer Test Plan
## Actionable Validation Checklist

**Purpose:** Validate that our data infrastructure can extract exploitable signals before building execution layer.

**Philosophy:** 
- Test our code, not library code
- Performance comparisons: try, fix, ship (no formal tests)
- Historical analysis: heavy test coverage with verify-it-fails assertions
- Lag detection: gather everything, analyze deviations, identify opportunities

---

## 1. Historical Data Pipeline

### 1.1 Data Collection Validation

**Objective:** Confirm we can gather and store sufficient historical data for probability model construction.

| Test | Pass Criteria |
|------|---------------|
| Binance klines fetch for 6+ months | Complete dataset, no gaps >1 hour |
| Data persistence and retrieval | Round-trip integrity check |
| Timestamp alignment across sources | All timestamps normalized to UTC, <1s drift |
| Missing data detection | Gaps identified and logged |
| Rate limit handling | Graceful backoff, no data loss |

### 1.2 Data Quality Checks

| Test | Pass Criteria |
|------|---------------|
| Price sanity bounds | No prices <$1,000 or >$500,000 for BTC |
| Monotonic timestamps | No backwards time jumps |
| Duplicate detection | Identical timestamp+price pairs flagged |
| Outlier detection | >10% single-candle moves flagged for review |

---

## 2. Feature Extraction Tests

### 2.1 Price Features

**Deviation Calculation**

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Zero deviation | open=50000, current=50000 | 0.0% | ✓ |
| Positive deviation | open=50000, current=50500 | +1.0% | ✓ |
| Negative deviation | open=50000, current=49500 | -1.0% | ✓ |
| Edge: exactly at boundary | open=50000, current=50000.01 | >0% (UP) | ✓ |
| Wrong input order | Swapped params | Error or obviously wrong | ✓ |

**Velocity Calculation**

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Steady price | Flat 5s window | velocity ≈ 0 | ✓ |
| Linear increase | +$100 over 5s | velocity = $20/s | ✓ |
| Linear decrease | -$100 over 5s | velocity = -$20/s | ✓ |
| Insufficient data points | <2 prices | Graceful null/error | ✓ |
| Non-uniform timestamps | Irregular intervals | Correctly weighted | ✓ |

**Acceleration Calculation**

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Constant velocity | Linear price movement | acceleration ≈ 0 | ✓ |
| Increasing velocity | Accelerating price | acceleration > 0 | ✓ |
| Decreasing velocity | Decelerating price | acceleration < 0 | ✓ |

**Realized Volatility**

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Flat prices | No movement | volatility ≈ 0 | ✓ |
| Known volatility series | Pre-calculated dataset | Match within 1% | ✓ |
| Single price point | n=1 | Graceful null/error | ✓ |

### 2.2 Order Book Features

**Ask Book Traversal**

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Single level sufficient | 100 shares @ $0.50, want 50 | price = $0.50 | ✓ |
| Multi-level fill | 50@$0.50, 50@$0.51, want 80 | weighted avg | ✓ |
| Insufficient liquidity | 100 available, want 200 | Partial or null | ✓ |
| Empty book | No asks | Graceful null/error | ✓ |
| Unsorted input | Random order levels | Still correct result | ✓ |

**Book Imbalance**

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Equal depth | bid=1000, ask=1000 | imbalance = 0 | ✓ |
| All bids | bid=1000, ask=0 | imbalance = 1.0 | ✓ |
| All asks | bid=0, ask=1000 | imbalance = -1.0 | ✓ |
| Heavy bid | bid=800, ask=200 | imbalance = 0.6 | ✓ |

**VWAP Calculation**

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Single level | 1000 shares @ $0.50 | vwap = $0.50 | ✓ |
| Multi-level | Mixed depths | Correctly weighted | ✓ |
| Depth exceeds available | Want $10k, only $5k avail | Partial vwap or error | ✓ |

### 2.3 Time Features

**Time Remaining**

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Full period | t=0 of 15min window | 900 seconds | ✓ |
| Mid period | t=7.5min | 450 seconds | ✓ |
| End of period | t=15min | 0 seconds | ✓ |
| Past resolution | t > resolution_time | Negative (or error) | ✓ |

**Session Classification**

| Test | Input (UTC) | Expected | Verify Fails |
|------|-------------|----------|--------------|
| 03:00 | ASIA | ✓ |
| 10:00 | EUROPE | ✓ |
| 15:00 | US_EU_OVERLAP | ✓ |
| 19:00 | US | ✓ |
| 23:00 | LATE_US | ✓ |
| Boundary: 08:00 exactly | EUROPE (not ASIA) | ✓ |
| Boundary: 13:00 exactly | US_EU_OVERLAP | ✓ |

**Candle Phase**

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Candle open | elapsed=0s | phase = 0.0 | ✓ |
| Candle mid | elapsed=450s | phase = 0.5 | ✓ |
| Candle close | elapsed=900s | phase = 1.0 | ✓ |

### 2.4 Composite Features

**Probability Bucket Lookup**

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Known bucket with data | Valid combination | Returns (p, conf, n) | ✓ |
| Empty bucket | Rare combination | Returns null or fallback | ✓ |
| Boundary deviation | Exactly at bucket edge | Consistent bucketing | ✓ |
| Out of range deviation | deviation > 2% | Edge bucket or error | ✓ |

**Edge Calculation**

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Positive edge | fair=0.60, market=0.55 | edge = +0.05 | ✓ |
| Negative edge | fair=0.50, market=0.55 | edge = -0.05 | ✓ |
| Zero edge | fair=market | edge = 0 | ✓ |

---

## 3. Signal Detection Tests

### 3.1 Dutch Book Detector

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Clear opportunity | UP=$0.48, DOWN=$0.50 | Signal triggered | ✓ |
| No opportunity | UP=$0.52, DOWN=$0.52 | No signal | ✓ |
| Boundary: exactly $1.00 | UP=$0.50, DOWN=$0.50 | No signal (no profit) | ✓ |
| Boundary: $0.99 | UP=$0.495, DOWN=$0.495 | Signal triggered | ✓ |
| Accounts for traversal | Book prices, not midpoint | Correct execution price | ✓ |

### 3.2 Lag Arbitrage Detector

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Binance leads up | Binance +0.15%, Chainlink flat | LAG_ARB_BUY_UP | ✓ |
| Binance leads down | Binance -0.15%, Chainlink flat | LAG_ARB_BUY_DOWN | ✓ |
| No significant lag | <0.1% difference | No signal | ✓ |
| Lag not sustained | >0.1% but <500ms | No signal | ✓ |
| Sustained lag | >0.1% for >500ms | Signal triggered | ✓ |

### 3.3 Momentum Detector

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| Strong up momentum | velocity>thresh, accel>0, imbalance>0.3 | MOMENTUM_UP | ✓ |
| Velocity without confirmation | velocity>thresh, imbalance<0.3 | No signal | ✓ |
| Decelerating | velocity>thresh, accel<0 | No signal | ✓ |
| Too close to resolution | t_remaining < 60s | No signal | ✓ |

### 3.4 Flash Crash Detector

| Test | Input | Expected | Verify Fails |
|------|-------|----------|--------------|
| 30% drop in 10s | Price crashes | FLASH_CRASH signal | ✓ |
| 20% drop | Below threshold | No signal | ✓ |
| 30% drop over 30s | Too slow | No signal | ✓ |
| Gradual decline | Steady downtrend | No signal | ✓ |

---

## 4. Logging Validation

### 4.1 Timing Logs

**Objective:** Logs must capture timing with millisecond precision to verify reaction speed.

| Log Event | Required Fields |
|-----------|-----------------|
| Price update received | timestamp_ms, source, price |
| Feature extracted | timestamp_ms, feature_name, value, input_prices |
| Signal generated | timestamp_ms, signal_type, confidence, latency_from_trigger |
| Order submitted | timestamp_ms, order_id, signal_id, submission_latency |

**Validation Tests:**

| Test | Pass Criteria |
|------|---------------|
| Timestamp precision | All logs include millisecond precision |
| Latency calculation | signal_time - price_update_time < 50ms for Dutch Book |
| Ordered events | No timestamp inversions in log sequence |
| Correlation IDs | Can trace price → feature → signal → order |

### 4.2 Feature Extraction Logs

| Test | Pass Criteria |
|------|---------------|
| All inputs captured | Can reconstruct feature calculation from logs |
| Intermediate values | Velocity, acceleration logged before signal |
| Threshold comparisons | Log shows value vs threshold for each check |

### 4.3 Log Replay Capability

| Test | Pass Criteria |
|------|---------------|
| Deterministic replay | Same logs → same signals when replayed |
| Audit trail complete | Can explain every signal from logs alone |

---

## 5. Lag Analysis (Exploratory)

**Objective:** Gather all price streams simultaneously, identify where deviations exist, find exploitable patterns.

### 5.1 Data Collection Setup

**Streams to capture simultaneously:**
1. Binance WebSocket (btcusdt@trade)
2. Polymarket RTDS (crypto_prices - Binance source)
3. Polymarket RTDS (crypto_prices_chainlink)
4. Chainlink on-chain (RPC polling every 2s)
5. Polymarket CLOB WebSocket (order book updates)

**Duration:** Minimum 1 hour continuous capture, ideally 24 hours across all sessions.

**Output:** Single synchronized dataset with all feeds aligned by timestamp.

### 5.2 Lag Measurements

| Comparison | Measurement | What We Learn |
|------------|-------------|---------------|
| Binance → RTDS Binance | Propagation delay | RTDS overhead |
| Binance → RTDS Chainlink | Oracle lag | Primary arb window |
| Binance → Chainlink RPC | On-chain update delay | Backup signal timing |
| RTDS Chainlink → CLOB repricing | Market reaction time | Execution window |
| Binance → CLOB repricing | End-to-end opportunity | Total arb window |

### 5.3 Analysis Questions

| Question | How to Answer |
|----------|---------------|
| What is typical lag window? | Median, p95, p99 of Binance→Chainlink lag |
| Does lag vary by session? | Group by trading session, compare distributions |
| Does lag vary by volatility? | Correlate lag with realized vol |
| When does CLOB reprice? | Detect price_change events, measure from Binance move |
| Are there predictable patterns? | Autocorrelation analysis on lag series |

### 5.4 Deviation Analysis

| Check | What We're Looking For |
|-------|------------------------|
| Price discrepancies | Binance vs Chainlink divergence >0.1% |
| Stale Chainlink | No update for >60s during volatile period |
| CLOB mispricing | UP + DOWN significantly != $1.00 |
| Order book staleness | Book not updating despite price moves |

### 5.5 Exploitable Patterns to Identify

| Pattern | Signature | Opportunity |
|---------|-----------|-------------|
| Consistent lag | Chainlink always trails Binance by X seconds | Lag arb timing |
| Update clustering | Chainlink updates in bursts | Predict next update |
| CLOB reaction delay | Book updates Y seconds after Chainlink | Execution window |
| Session-dependent lag | Longer lag during low-volume sessions | Session selection |

---

## 6. Market Discovery Testing

**Objective:** Verify automatic discovery of current 15-minute BTC market works reliably.

### 6.1 Functional Tests

| Test | Pass Criteria |
|------|---------------|
| Finds active market | Returns valid condition ID for current window |
| Market transition | Correctly switches at 15-minute boundaries |
| Handles no active market | Graceful handling if market not yet created |
| Returns both UP and DOWN | Both token IDs available |
| Correct resolution time | Matches expected 15-minute boundary |

### 6.2 Reliability Tests

| Test | Pass Criteria |
|------|---------------|
| API failure handling | Retry logic, doesn't crash |
| Stale cache detection | Refreshes when market expires |
| Multiple rapid calls | Caches result, doesn't spam API |

### 6.3 Integration Validation

| Test | Pass Criteria |
|------|---------------|
| Discovered market is tradeable | Can fetch order book for returned IDs |
| Token IDs match CLOB | Order submission accepts discovered IDs |

---

## 7. Performance Testing

**Approach:** No formal tests. Try configurations, measure, keep what works.

### 7.1 Polling Interval Experiment

**Current:** 1-second polling
**Test:** Remove polling, rely on WebSocket push only

| Metric | Measure |
|--------|---------|
| Signal detection latency | Time from price move to signal generation |
| CPU usage | With vs without polling loop |
| Memory stability | Any leaks over 1 hour |

**Decision:** If WebSocket-only latency is <100ms worse, remove polling.

### 7.2 Feature Calculation Timing

| Operation | Target | If Exceeded |
|-----------|--------|-------------|
| Deviation calculation | <1ms | Optimize |
| Book traversal | <5ms | Cache partial results |
| Full feature vector | <10ms | Parallelize |
| Signal evaluation | <5ms | Simplify logic |

### 7.3 Memory Profiling

| Check | Concern |
|-------|---------|
| Ring buffer growth | Should stay bounded |
| Order book caching | Clear old snapshots |
| Log accumulation | Rotate or flush |

---

## 8. Test Execution Order

### Phase 1: Historical Data (Offline)

1. Fetch 6 months Binance data
2. Run all feature extraction tests against known data
3. Verify probability bucket generation
4. Validate statistical properties (mean reversion, session patterns)

### Phase 2: Live Data Collection (Observation Only)

1. Connect all 5 price streams
2. Run lag analysis for 24 hours
3. Generate deviation report
4. Identify exploitable patterns

### Phase 3: Signal Detection (Paper Mode)

1. Run signal detectors on live data
2. Log all would-be signals
3. Verify signal timing via logs
4. Calculate theoretical P&L

### Phase 4: Market Discovery Integration

1. Test discovery across market transitions
2. Verify continuous operation over multiple 15-min windows
3. Confirm token ID validity

### Phase 5: Performance Tuning

1. Remove 1s polling, measure impact
2. Profile feature extraction
3. Optimize bottlenecks
4. Establish baseline latency metrics

---

## 9. Success Criteria

### Data Layer Ready When:

- [ ] All feature extraction tests pass with verify-fails
- [ ] Lag analysis shows exploitable window >1 second
- [ ] Signal detectors generate expected signals on test data
- [ ] Logs capture complete audit trail with ms precision
- [ ] Market discovery works across multiple transitions
- [ ] End-to-end latency (price → signal) <50ms for Dutch Book
- [ ] 24-hour stability test passes without crashes or memory leaks

### Go/No-Go Metrics:

| Metric | Go | No-Go |
|--------|----|----|
| Chainlink lag window | >2 seconds median | <1 second |
| Dutch Book opportunities/day | >10 detected | 0 detected |
| Feature extraction latency | <10ms | >100ms |
| WebSocket stability | >99% uptime | <95% uptime |
| Log completeness | 100% events traced | Missing events |

---

## 10. Tools Needed

| Purpose | Tool |
|---------|------|
| Historical data | Binance API + local storage |
| Live data capture | Python asyncio + websockets |
| Lag analysis | Pandas + matplotlib |
| Test runner | pytest with verify-fails plugin |
| Performance profiling | cProfile / py-spy |
| Log analysis | Structured JSON logs + jq |

---

## Appendix: Test Data Fixtures

### Required Fixtures

| Fixture | Contents |
|---------|----------|
| flat_prices.json | 15 minutes of zero movement |
| trending_up.json | Steady 1% increase over 15 min |
| trending_down.json | Steady 1% decrease over 15 min |
| volatile_session.json | High volatility period from real data |
| flash_crash.json | Known flash crash event |
| dutch_book_opportunity.json | Snapshot where UP+DOWN < $1.00 |
| lag_event.json | Binance moved, Chainlink delayed |

### Fixture Requirements

- All fixtures include millisecond timestamps
- Order book fixtures include full depth (not just top of book)
- Real data preferred over synthetic where possible
- Each fixture documents expected signal output