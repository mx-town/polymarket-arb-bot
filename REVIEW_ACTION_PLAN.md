# Complete-Set Arb Bot — Review Action Plan

> Living document. Updated: 2026-02-14
> Source: Full codebase review (4,295 lines, 15 modules, 0 tests)

---

## Status Legend

- [ ] Not started
- [~] In progress
- [x] Done
- [!] Blocked / needs investigation

---

## TIER 1 — Money Losers (est. -$3 to -$5/day)

### T1-1: CLEANUP_SELL sells at loss (est. -$3-4/day)
- **File:** `engine.py:670-699`
- **Root cause:** Pre-resolution buffer sells unhedged legs at current bid with no floor price check. Confirmed by MEMORY.md: reduces lost ~$11.30 over 3 sessions while merges earned ~$3.50.
- **Fix options:**
  - (A) Remove CLEANUP_SELL entirely — let unhedged positions resolve at settlement, redeem via `_pending_redemptions` (already exists)
  - (B) Gate with `bid >= vwap * 0.80` floor — accept max 20% loss, skip if worse
- **Recommendation:** Option A. Settlement redemption already works. No reason to panic-sell at bad prices.
- **Status:** [ ]

### T1-2: No gas price cap — unlimited cost exposure
- **File:** `redeem.py:275`
- **Root cause:** `gas_price = ceil(gas_price_raw * 1.50)` with no upper bound. Polygon congestion can spike gas 50-100x.
- **Fix:**
  - Add `max_gas_price_gwei` to `CompleteSetConfig` (default: 200 gwei)
  - In `_send_safe_tx`: abort if `gas_price_gwei > max_gas_price_gwei`
  - Log warning when gas exceeds 50% of cap
- **Status:** [ ]

### T1-3: No pre-merge profitability check
- **File:** `engine.py:326-346`
- **Root cause:** Merges whenever `hedged >= min_merge_shares` without checking `gross_profit > gas_cost`. 5 shares at 0.01 edge = $0.05 gross; gas can eat 40%+.
- **Fix:**
  - Before merge launch in `_check_settlements`: compute `gross = hedged * (1 - up_vwap - down_vwap)`
  - Estimate gas cost in USD (use cached gas price + MATIC/USD estimate)
  - Skip merge if `gross < gas_estimate_usd * 1.5`
  - Add `min_merge_profit_usd` to config (default: 0.02)
- **Status:** [ ]

### T1-4: Missing CTF approval — first merge always reverts
- **File:** `redeem.py:372-399`
- **Root cause:** `merge_positions` never calls `isApprovedForAll` or `setApprovalForAll`. ERC1155 ABI has both (lines 73-90) but neither invoked. First merge on fresh Safe reverts, wastes gas, increments failure counter (5 = permanent block).
- **Fix:**
  - In `merge_positions`, before encoding merge data:
    - Call `ctf.functions.isApprovedForAll(safe_address, target_operator).call()`
    - If not approved: send approval tx via Safe first, wait for receipt
  - Cache approval status per (safe, operator) pair to avoid repeated checks
- **Status:** [ ]

### T1-5: Balance exhaustion leaves one-sided positions
- **File:** `engine.py:982-984`
- **Root cause:** Hedge silently skipped with `DEBUG` log when bankroll exhausted. No recovery path — stuck with directional risk.
- **Fix options:**
  - (A) Reserve hedge notional when placing first leg (pre-allocate from bankroll)
  - (B) Cancel first leg when hedge is impossible
  - (C) Log at WARNING level + track unhedged exposure separately
- **Recommendation:** Option A — reserve `max_order_bankroll_fraction` for hedge when first leg is placed.
- **Status:** [ ]

---

## TIER 2 — Edge Erosion (est. -$0.50 to -$1/day combined)

### T2-1: VWAP quantization inflates edge by 0.02%
- **File:** `models.py:65,71`
- **Root cause:** `.quantize(Decimal("0.0001"))` on VWAP properties. Both VWAPs rounded down = edge inflated by 0.0002. ~$0.24/day at $24 deployed over 50 cycles.
- **Fix:** Remove `.quantize()` from `up_vwap` and `down_vwap` properties. Only quantize in log formatting.
- **Status:** [ ]

### T2-2: Dynamic edge doesn't track first leg's spread
- **File:** `quote_calc.py:248-259`, `engine.py:767-771`
- **Root cause:** First leg has no edge check (only price cap). Spread can change between legs — hedge may lock in combined cost >0.99. After gas, these merges lose $0.05-0.10 each.
- **Fix:**
  - Add `entry_dynamic_edge` field to `MarketInventory`
  - Set when first leg fills
  - Hedge must satisfy `up_vwap + down_maker < 1 - entry_dynamic_edge`
- **Status:** [ ]

### T2-3: Unhedged exposure valued at $0.50, not VWAP
- **File:** `quote_calc.py:294-295`
- **Root cause:** `unhedged_exposure += abs_imbalance * Decimal("0.50")`. Overestimates exposure when VWAP < 0.50, blocks $0.50-1.00 buying power per 10-share imbalance.
- **Fix:** Use actual VWAP: `unhedged_exposure += abs_imbalance * (up_vwap or down_vwap or 0.50)`
- **Status:** [ ]

### T2-4: min_merge_shares=5 is gas-inefficient
- **File:** `config.yaml:30`
- **Root cause:** 5 shares at 1% edge = $0.05. Gas eats 12-46%. Raising to 10 halves merge frequency, saves ~$0.15/day gas.
- **Fix:** Change `min_merge_shares: 10` in config.yaml.
- **Status:** [ ]

---

## TIER 3 — Reliability & Edge Cases

### T3-1: Empty order book crashes bot
- **File:** `engine.py:767-771`
- **Root cause:** Ternary evaluates `best_ask - best_bid` before None check. `TypeError` during illiquid moments.
- **Fix:** Check both `best_bid` and `best_ask` for None before arithmetic.
- **Status:** [ ]

### T3-2: FOK sentinel leak on null orderId
- **File:** `order_mgr.py:156-170`
- **Root cause:** Sentinel inserted for FOK orders on null orderId. Blocks token_id for 300s > 90s cleanup window.
- **Fix:** Skip sentinel for FOK orders (`if not is_fok: self._orders[token_id] = ...`).
- **Status:** [ ]

### T3-3: Double PnL accounting on market expiry during merge
- **File:** `engine.py:228-241`, `inventory.py:262-265,301-304`
- **Root cause:** Market rotates out + merge completes → both `clear_market` and `reduce_merged` add PnL.
- **Fix:** Skip `clear_market` for markets with pending merge tasks.
- **Status:** [ ]

### T3-4: No config validation at startup
- **File:** `config.py:51-86`
- **Root cause:** Zero validation. Negative `min_edge`, zero `bankroll_usd`, inverted time windows all silently break logic.
- **Fix:** Add validation in `load_complete_set_config` with clear error messages.
- **Status:** [ ]

### T3-5: Bootstrap VWAP uses mid-price (wrong by 10-30%)
- **File:** `inventory.py:140-156`
- **Root cause:** On restart with existing positions, cost estimated from mid-price or 0.50 fallback. If actual was 0.68, hedge enters thinking 2% edge but actually losing.
- **Fix:** Mark bootstrapped positions. Refuse hedge entries or add manual VWAP override.
- **Status:** [ ]

### T3-6: Network timeout sentinel blocks fill detection
- **File:** `order_mgr.py:187-209`
- **Root cause:** If `post_order` times out but order landed on CLOB, sentinel blocks fill detection. Double exposure risk.
- **Fix:** Periodic reconciliation of `_orders` against CLOB `get_orders()`.
- **Status:** [ ]

---

## TIER 4 — Performance

### T4-1: Order status polling is serialized (primary bottleneck)
- **File:** `order_mgr.py:310-373`
- **Root cause:** N orders × ~100ms each, inside `_tick_core`. 2 orders = 200ms = 40% of 500ms tick budget. 4+ orders = drift.
- **Fix:** Parallelize with `asyncio.gather`.
- **Status:** [ ]

### T4-2: No tick duration measurement
- **File:** `engine.py`
- **Root cause:** No instrumentation for tick timing. Drift goes unnoticed.
- **Fix:** Log warning when tick takes >90% of budget.
- **Status:** [ ]

---

## Test Coverage Gaps (Priority)

| Area | Why it matters | Status |
|------|---------------|--------|
| VWAP calculation | Rounding errors → wrong edge → bad trades | [ ] |
| Edge calculation | Core profitability math | [ ] |
| Exposure calculation | Over/under counting → wrong position sizes | [ ] |
| Cost scaling in sync | Proportional errors → VWAP corruption | [ ] |
| Gas profitability check | Merge at a loss | [ ] |
| FOK sizing math | Decimal precision → rejected orders | [ ] |
| Config validation | Bad config → silent failures | [ ] |
| Inventory reduce/merge | State corruption → phantom inventory | [ ] |

---

## Changelog

| Date | Changes |
|------|---------|
| 2026-02-14 | Initial review — 17 issues identified across 4 tiers |
