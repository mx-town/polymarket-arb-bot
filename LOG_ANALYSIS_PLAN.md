# Bot Run Log Analysis Plan

Reusable plan for analyzing complete-set arb bot dry-run logs. Focus: bot efficiency and profit maximizing.

## Log Location & Format

- **Path**: `logs/dry/complete_set_YYYY-MM-DD_HHMMSS.log` or `logs/live/complete_set_YYYY-MM-DD_HHMMSS.log`
- **Format**: `YYYY-MM-DD HH:MM:SS │ logger_name │ MESSAGE`
- **Loggers**: `cs.engine`, `cs.orders`, `cs.market_data`, `cs.inventory`, `cs.binance_ws`, `cs.chainlink`, `cs.bot`

## Step 1: Session Overview (30 seconds)

Extract the session header and final state.

```bash
# Config + runtime params (first 20 lines)
head -20 <logfile>

# All SESSION lines — P&L trajectory over time
grep 'SESSION' <logfile>

# Final SUMMARY — ending state
grep 'SUMMARY\|EXPOSURE\|TICK_STATS' <logfile> | tail -6

# Total runtime
head -1 <logfile>; tail -1 <logfile>
```

**What to check:**
- Bankroll, tick interval, time window, edge settings
- P&L trajectory: is it improving, flat, or declining over time?
- Final exposure utilization: `X% used` — are we deploying capital efficiently?
- Tick performance: avg/max ms vs budget — are we timing out?

## Step 2: Fill Pipeline Health (critical path)

The profit pipeline is: **Entry → Fill → [Wait for swing] → Hedge → Fill → Merge → Profit**. The swing wait is the critical bottleneck — if BTC doesn't reverse direction, the hedge never fires and the first leg becomes an unhedged loss.

```bash
# Count each stage
grep -c 'SH_ENTRY\|MR_ENTRY' <logfile>    # entries attempted
grep -c 'DRY_FILL' <logfile>               # fills simulated (dry-run)
grep -c 'cs.engine.*│ FILL ' <logfile>     # fills recorded (live — exclude DRY_FILL)
grep -c 'HEDGE_LEG' <logfile>              # hedge orders placed
grep -c 'HEDGE_COMPLETE' <logfile>         # hedge fills confirmed
grep -c 'DRY_MERGE\|MERGE_POSITION' <logfile>  # merges executed
grep -c 'SELL_FILL' <logfile>              # reduce fills
grep -c 'BUFFER_HOLD' <logfile>            # positions stuck at resolution (spam — count unique markets instead)
grep 'BUFFER_HOLD' <logfile> | grep -oE 'btc-[^ ]+' | sort -u | wc -l  # unique markets stuck
```

**Expected healthy ratios (dry-run):**
- Entries >> 0 (signal is firing)
- DRY_FILL > 0 (simulation is working)
- HEDGE_COMPLETE / first-leg fills > 0.5 (swing is happening often enough)
- MERGE > 0 (pairs are being completed)
- BUFFER_HOLD unique markets = 0 (no unhedged positions at settlement)

**Key failure mode — unhedged positions:**
If HEDGE_COMPLETE is low relative to first-leg fills, the strategy is buying one side but BTC isn't swinging back. This is the #1 loss source. Jump to **Step 2.5** to diagnose per-market.

**If DRY_FILL = 0:** The fill simulation is broken. Check:
1. Is `check_pending_orders` running before `_evaluate_market` in `_tick_core`? (fill check must precede reprice)
2. Are orders being repriced every tick? (grep `REPRICE` count vs `DRY` place count)
3. Is the book ever crossing the order price? (grep `SIM_FILL` for debug output)

## Step 2.5: Per-Market Narrative (most important step)

Reconstruct what happened in each market window end-to-end. This is where you find the actual profit/loss drivers.

```bash
# List all market windows that were active
grep 'ENTER window\|EXIT  window\|CLEAR_INVENTORY' <logfile>

# For EACH market slug, reconstruct the full lifecycle:
SLUG="btc-updown-15m-XXXXXXXXXX"  # substitute each slug

# 1. Entry: what side, what price, how many reprices?
grep "$SLUG" <logfile> | grep 'SH_ENTRY\|MR_ENTRY\|REPRICE\|DRY_FILL\|HEDGE'

# 2. Price chase: did maker price drift upward via reprices?
grep "$SLUG" <logfile> | grep 'REPRICE' | grep -oE '[0-9.]+→[0-9.]+'

# 3. Hedge attempts: why did they fail?
grep "$SLUG" <logfile> | grep 'HEDGE_SKIP\|HEDGE_LEG\|HEDGE_COMPLETE'

# 4. Final outcome
grep "$SLUG" <logfile> | grep 'CLEAR_INVENTORY\|DRY_MERGE\|BUFFER_HOLD' | head -3
```

**Per-market checklist:**

| Question | Where to look | Good | Bad |
|----------|--------------|------|-----|
| Did we enter? | SH_ENTRY/MR_ENTRY exists | Yes | No entries = signal too strict |
| Did we get filled? | DRY_FILL follows entry | Within 5s | Never filled or >60s |
| Did we chase price? | REPRICE count + direction | 0-2 reprices, same or lower price | 3+ reprices trending up (0.39→0.48) |
| Did we hedge? | HEDGE_COMPLETE exists | Yes, edge > 0.02 | HEDGE_SKIP spam = no swing |
| Did we merge? | DRY_MERGE exists | Yes | Stuck in BUFFER_HOLD = total loss |
| What was P&L? | CLEAR_INVENTORY net= | Positive | `unhedged=U192.30 (loss=$92.30)` |

**Expected behavior per market:**
1. Entry at bid on cheap side (price < 0.48) → filled within 1-5s as book crosses
2. BTC swings → opposite side cheapens → HEDGE_LEG placed → filled → HEDGE_COMPLETE
3. DRY_MERGE immediately → freed capital → re-enter if time remains
4. CLEAR_INVENTORY shows `was U0/D0` (fully merged) or small remainder with positive net

**Failure patterns to flag:**
- **Price chasing**: Entry at 0.39, repriced to 0.41→0.44→0.46→0.48 → filled at 0.48. Combined cost too high, hedge impossible. Fix: tighter `max_first` or cap reprice distance.
- **No swing**: HEDGE_SKIP repeated for entire window. BTC trended one direction. The entry bet on mean reversion that didn't happen.
- **Partial hedge**: HEDGE_COMPLETE for subset of shares, rest stuck as unhedged. Often happens when second fill arrives after merge depletes the hedged pair.
- **Late entry**: Entry at 780s left, swing needed but window too short. Check if entry timing left enough time for BTC to reverse.

## Step 3: Order Churn Analysis

```bash
# Order placement vs cancellation
grep -c 'DRY btc\|DRY eth' <logfile>    # total orders placed
grep -c 'DRY_CANCEL' <logfile>           # total cancels
grep -c 'REPRICE' <logfile>              # reprices (subset of cancels)
grep -c 'Removing stale' <logfile>       # orders that timed out (300s)
```

**Efficiency metrics:**
- `cancel_ratio = DRY_CANCEL / orders_placed` — above 0.95 means pathological churn
- `reprice_ratio = REPRICE / DRY_CANCEL` — should be ~1.0 (most cancels should be reprices, not stale/buffer)
- `stale_count` — orders hitting 300s timeout means the book never crossed our price

**If churn is high:** Two distinct causes:
1. **Lateral repricing** (0.48→0.47→0.48→0.47): Normal. Book oscillates 1c, maker order follows. No impact on fill quality.
2. **Upward repricing / price chasing** (0.39→0.41→0.44→0.46→0.48): Dangerous. We're raising our bid as the market moves against us, inflating entry cost and destroying hedge edge. Check how many reprices trend upward vs lateral:
```bash
# Extract reprice directions per market
grep 'REPRICE' <logfile> | grep -oE '[0-9.]+→[0-9.]+' | awk -F'→' '{if($2>$1) print "UP "$1"→"$2; else if($2<$1) print "DN "$1"→"$2; else print "FLAT"}'
```

## Step 4: Book Dynamics & Edge

```bash
# Edge distribution — are combined asks ever < 1.00?
grep 'ask_edge=' <logfile> | grep -oE 'ask_edge=[0-9.-]+' | sort | uniq -c | sort -rn

# Spread distribution — are spreads always 0.01?
grep 'BOOK ' <logfile> | grep -oE 'spread=[0-9.]+' | sort | uniq -c | sort -rn

# Book depth — number of levels available
grep 'BOOK ' <logfile> | head -20

# Price range over time — how much does the market move?
grep 'BOOK_CHANGE' <logfile> | head -30
```

**What to check:**
- `ask_edge`: If always -0.01, the market is always 1c over par. Profit comes from buying at bid (cheaper than ask) and merging at $1.
- `spread`: If always 0.01, this is a tight market. Maker orders at bid+0c are the only sensible strategy.
- Book depth: 30-100 levels is normal for Polymarket 15m markets.
- Price movement: Rapid 1-cent oscillations indicate the book is highly responsive to BTC price. This is the pattern that creates fill opportunities when the ask drops to our bid.

## Step 5: Share Sizing Validation

```bash
# Extract share sizes from order placements
grep 'DRY btc\|DRY eth' <logfile> | grep -oE 'x[0-9.]+' | sed 's/x//' | sort -n | head -5
grep 'DRY btc\|DRY eth' <logfile> | grep -oE 'x[0-9.]+' | sed 's/x//' | sort -rn | head -5

# Extract prices from placements
grep 'DRY btc\|DRY eth' <logfile> | grep -oE '@ [0-9.]+' | sed 's/@ //' | sort -n | uniq -c
```

**Expected at $500 bankroll (20% per order):**
- At price 0.47: ~212 shares ($100 / 0.47)
- At price 0.30: ~333 shares ($100 / 0.30)
- Time-adjusted: multiply by 0.55-1.0 depending on seconds_to_end
- Minimum: 5 shares (Polymarket floor)

**Watch for:**
- Wildly inconsistent sizes at similar prices → exposure cap is kicking in (check if multiple markets consuming bankroll)
- Very small sizes (< 20) → total_bankroll_cap reached, or price is very high
- Sizes capped at book depth → this is correct behavior for the fill simulation

## Step 6: Timing & Market Lifecycle

```bash
# Market enter/exit window events
grep 'ENTER window\|EXIT  window' <logfile>

# Buffer hold (pre-resolution) — only first/last per market to avoid spam
grep 'BUFFER_HOLD' <logfile> | grep -oE 'btc-[^ ]+' | sort -u  # which markets got stuck
grep 'BUFFER_HOLD' <logfile> | head -1   # first occurrence
grep 'BUFFER_HOLD' <logfile> | tail -1   # last occurrence

# Market clearing — THE money line
grep 'CLEAR_INVENTORY' <logfile>

# Discovery cycle
grep 'Discovered' <logfile> | head -5
```

**What to check:**
- Markets enter window at `max_seconds_to_end` (900s) and exit at `min_seconds_to_end` (90s)
- BUFFER_HOLD means unhedged shares sitting at resolution — check `UX/DY` for which side is exposed
- CLEAR_INVENTORY is the final verdict per market:
  - `was U0/D0` → nothing happened (no fills, or fully merged)
  - `hedged=N │ hedged_pnl=$X` → merge profit
  - `unhedged=U192.30 (loss=$92.30)` → LOSS, first leg never hedged
- Discovery runs every 30s, finding 2-3 overlapping 15m windows
- Gap between EXIT and CLEAR should be ~60-90s (waiting for resolution)

## Step 7: Signal Quality

```bash
# Entry signal breakdown
grep 'SH_ENTRY\|MR_ENTRY' <logfile> | head -20

# Skip reasons — why aren't we entering?
grep 'SH_SKIP\|MR_SKIP\|SWING_SKIP\|HEDGE_SKIP' <logfile> | head -20

# Swing filter blocks
grep 'SWING_SKIP' <logfile> | wc -l
```

**What to check:**
- SH_ENTRY logs show `range=X.XXXXX` — the candle range at entry time
- If SWING_SKIP is high, the opposite side wasn't recently cheap → market is trending, not swinging
- HEDGE_SKIP with "edge" reason means combined VWAP + hedge price doesn't leave enough edge

## Step 8: BTC Price Feed & Lag

```bash
# Binance price feed health
grep 'BTC_TICK' <logfile> | head -5
grep 'BTC_TICK' <logfile> | wc -l

# BTC price range during session (extract prices)
grep 'BTC_TICK' <logfile> | grep -oE '→ [0-9.]+' | sed 's/→ //' | sort -n | head -1  # low
grep 'BTC_TICK' <logfile> | grep -oE '→ [0-9.]+' | sed 's/→ //' | sort -rn | head -1 # high

# Candle state / deviation distribution
grep 'LAG_TRACE' <logfile> | grep -oE 'dev=[0-9.+-]+' | sort | uniq -c | sort -rn | head -10

# Polymarket book reaction to BTC moves (look for BOOK_CHANGE shortly after BTC_TICK)
# Manual: compare BTC_TICK timestamps with next BOOK_CHANGE timestamps
grep 'BTC_TICK\|BOOK_CHANGE' <logfile> | head -30
```

**What to check:**
- BTC_TICK frequency: every 2-4s is normal (Binance 1m kline stream)
- BTC range: if < $50 over the session, low volatility → fewer swing opportunities
- Deviation distribution: clustered near 0 = flat market, spread = volatile (good for swings)
- Book reaction time: BOOK_CHANGE should follow BTC_TICK within 1-2s. Longer gaps = stale books.

## Step 8.5: BTC Price Flow & Entry Validation

Reconstruct the BTC price path per market window and overlay entry/hedge decisions. This answers: "Did BTC actually create an arb opportunity, and did we act on it correctly?"

```bash
# For each market window, extract BTC price trajectory + bot decisions
SLUG="btc-updown-15m-XXXXXXXXXX"

# BTC ticks during this market's active window (between ENTER and EXIT/CLEAR)
# First get the time range:
grep "$SLUG" <logfile> | grep 'ENTER window\|EXIT  window\|CLEAR' | head -3

# Then extract BTC prices in that time range:
START="22:19:24"  # from ENTER window timestamp
END="22:28:58"    # from EXIT window timestamp
grep 'BTC_TICK' <logfile> | awk -v s="$START" -v e="$END" '$1" "$2 >= s && $1" "$2 <= e'

# Overlay: BTC ticks + all bot decisions for this market in chronological order
grep "BTC_TICK\|$SLUG" <logfile> | awk -v s="$START" -v e="$END" '$1" "$2 >= s && $1" "$2 <= e'

# Candle deviation at entry moment vs at hedge moment
grep "$SLUG" <logfile> | grep 'SH_ENTRY\|MR_ENTRY' | head -1  # entry time + range
grep "$SLUG" <logfile> | grep 'HEDGE_COMPLETE' | head -1       # hedge time (if any)
# Then check LAG_TRACE dev= at those timestamps
```

**Per-market questions to answer:**

1. **Was BTC swinging or trending during this window?**
   - Extract BTC high/low from BTC_TICK during the window
   - `swing_range = (high - low) / open` — if < 0.001 (0.1%), very flat, swings unlikely
   - If BTC moved monotonically in one direction → trending → entry was a bad bet on mean reversion

2. **Did we enter on the right side at the right time?**
   - Entry side should match the CHEAP side (the side with ask < 0.48)
   - Entry should happen AFTER a BTC move that made that side cheap, not before
   - Check `dev=` at entry time: if dev is near 0, there's no dislocation yet → premature entry
   - If dev is large (>0.001), one side should be cheap → good entry timing

3. **Did BTC swing back enough to create hedge opportunity?**
   - After first-leg fill, did BTC reverse enough that the opposite side's bid dropped?
   - Check HEDGE_SKIP reasons: `UP_vwap=X + DOWN_bid+1c=Y = Z │ edge=E < min_edge`
   - The combined cost Z must drop below `1 - min_edge` for hedge to fire
   - If Z stays at 1.00+ throughout → BTC never swung back → structural no-opportunity

4. **Were there missed swing opportunities?**
   - Look for moments where BOOK_CHANGE shows the opposite side cheapening but no HEDGE_LEG fires
   - This could indicate the hedge edge threshold is too strict, or the swing was too brief

**Expected behavior for a profitable window:**
```
T+0:    BTC at $70,000 (open). Book: UP=0.50/0.51, DOWN=0.49/0.50
T+120s: BTC drops to $69,900. Book: UP=0.40/0.41, DOWN=0.59/0.60
        → SH_ENTRY UP maker=0.40 → DRY_FILL UP +200 @ 0.40
T+300s: BTC bounces to $70,050. Book: UP=0.55/0.56, DOWN=0.44/0.45
        → HEDGE_LEG DOWN maker=0.44 → DRY_FILL DOWN +200 @ 0.44
        → HEDGE_COMPLETE edge=0.16 → DRY_MERGE 200 shares
        → Profit: 200 × ($1.00 - $0.40 - $0.44) = $32 gross
```

**Loss pattern to flag:**
```
T+0:    BTC at $70,000. Book: UP=0.50/0.51, DOWN=0.49/0.50
T+60s:  BTC rises to $70,100. Book: UP=0.55/0.56, DOWN=0.44/0.45
        → SH_ENTRY DOWN maker=0.44 → DRY_FILL DOWN +180 @ 0.44
T+120s: BTC keeps rising to $70,200. DOWN=0.35, UP=0.65
        → HEDGE_SKIP: DOWN_vwap=0.44 + UP_bid+1c=0.66 = 1.10 > threshold
T+900s: Resolution. BTC > open → UP wins → DOWN shares worth $0.00
        → CLEAR_INVENTORY unhedged=D180 (loss=$79.20)
```

## Step 9: Profit Attribution (when fills exist)

```bash
# Fill details
grep 'DRY_FILL\|FILL ' <logfile>

# Position tracking
grep 'POSITION' <logfile>

# Unrealized P&L on hedged positions
grep 'UNREALIZED' <logfile>

# Merge events and profit
grep 'DRY_MERGE\|MERGE_POSITION' <logfile>

# Per-market P&L at clearing
grep 'CLEAR_INVENTORY' <logfile>
```

**Profit formula per market:**
- `hedged_shares × ($1.00 - up_vwap - down_vwap) - gas_cost`
- Healthy: up_vwap + down_vwap < $0.98 → $0.02+ edge per share
- At 100 shares: $2.00 gross - $0.003 gas = ~$2.00 net per cycle

## Step 10: Red Flags Checklist

### Infrastructure flags (is the bot working?)

| Flag | How to check | Meaning |
|------|-------------|---------|
| Zero fills | `grep -c DRY_FILL` = 0 | Fill simulation broken |
| 99%+ cancel ratio | cancel/place > 0.99 | Pathological repricing (check tick order) |
| Exposure always 0% | SUMMARY shows 0% used | No capital being deployed (no entries) |
| Stale orders | `grep 'Removing stale'` | Orders never cross — sim too strict |
| TICK_SLOW > 50% of lines | Many tick budget warnings | HTTP latency issues, increase tick interval |
| Zero BOOK_CHANGE events | Static book | CLOB feed may be down |
| Zero BTC_TICK events | No price feed | Binance WS disconnected |

### Strategy flags (is the bot profitable?)

| Flag | How to check | Meaning |
|------|-------------|---------|
| Unhedged BUFFER_HOLD | Any BUFFER_HOLD with `U>0/D0` or `U0/D>0` | First leg filled but no swing → total loss at settlement |
| Price chasing | REPRICE trending up (0.39→0.48) | Entry cost inflated, hedge edge destroyed |
| Hedge rate < 50% | HEDGE_COMPLETE / first-leg fills | BTC not swinging enough, or edge threshold too strict |
| Negative CLEAR_INVENTORY | `net=$-X` in CLEAR lines | Unhedged positions resolved at loss |
| P&L declining over time | SESSION realized going down | Unhedged losses outpacing merge profits |
| ask_edge always -0.01 | All MARKET lines show -0.01 | Normal — profit from maker spread, not ask-side edge |
| Large unhedged exposure | SUMMARY shows high exposure% but low merge count | Capital tied up in first legs waiting for swings |

## Step 11: Efficiency Recommendations Template

After analysis, score each dimension 1-5 and provide recommendations:

**Strategy metrics (profit drivers):**
1. **Hedge Completion Rate** (HEDGE_COMPLETE / first-leg fills): Target > 0.7. THE most important metric — unhedged positions are pure losses.
2. **Unhedged Loss Ratio** ($ lost to unhedged positions / total $ deployed): Target < 0.1. From CLEAR_INVENTORY `unhedged=` lines.
3. **Net P&L per market** (realized / markets cleared): Target > $0.50
4. **Price Chase Score** (markets with 3+ upward reprices / total entries): Target 0. Each upward reprice destroys hedge edge.
5. **Swing Opportunity Hit Rate** (hedges completed / windows where BTC swung > 0.1%): Target > 0.5. Are we capitalizing on swings when they happen?

**Execution metrics (efficiency):**
6. **Fill Rate** (fills / market-windows): Target > 0.5 fills per 15m window
7. **Capital Utilization** (avg exposure / bankroll cap): Target > 40%
8. **Merge Rate** (merges / hedge completions): Target > 0.9
9. **Order Churn** (cancels / fills): Lower is better, < 10:1 target
10. **Signal Quality** (entries that led to fills / total entries): Target > 0.3

**Infrastructure metrics (health):**
11. **Tick Efficiency** (avg_tick_ms / budget_ms): Target < 0.5
12. **BTC Feed Uptime** (gaps > 10s in BTC_TICK / session length): Target 0
13. **Book Freshness** (BOOK_CHANGE events per minute): Target > 10
