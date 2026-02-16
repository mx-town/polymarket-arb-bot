#!/usr/bin/env bash
# analyze_loop.sh — recurring gabagool hypothesis generator
# Usage: bash src/observer/analyze_loop.sh [interval_seconds]
# Example: bash src/observer/analyze_loop.sh 60   # 1-min test
#          bash src/observer/analyze_loop.sh       # default 30min

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

DB="$PROJECT_ROOT/data/observer.db"
LOG_DIR="$PROJECT_ROOT/logs/observer"
LOG="$LOG_DIR/gabagool_analysis.log"
INTERVAL="${1:-1800}"
MODEL="sonnet"

mkdir -p "$LOG_DIR"

if [[ ! -f "$DB" ]]; then
  echo "ERROR: observer database not found at $DB" >&2
  exit 1
fi

# ── system prompt for Claude ──────────────────────────────────────────────────

read -r -d '' SYSTEM_PROMPT << 'SYSPROMPT' || true
You are reverse-engineering a Polymarket trading bot ("gabagool") from its on-chain activity.
You receive periodic data dumps from an observer database tracking every trade, position, merge, and market window.

Analyze ALL data and produce a structured hypothesis covering:

1. ENTRY LOGIC
   - What triggers a new market entry? (time-based? price-based? edge-based?)
   - Which side enters first? Is there a bias (Up vs Down)?
   - Entry role: MAKER (resting limit) vs TAKER (aggressive cross) — when does each apply?
   - Entry clip sizing: fixed or dynamic? What drives the size?

2. REPRICING / ORDER MANAGEMENT
   - Does gabagool post at one price or ladder across multiple levels?
   - How fast do prices update? (look at fill timestamps within a market)
   - Does repricing follow BTC price movement?
   - Price drift per market+outcome: is it chasing or anticipating?

3. HEDGE LOGIC
   - Delay between first-leg fill and hedge-leg entry
   - Does hedge use MAKER or TAKER? Under what conditions?
   - Is hedge sizing exact-match or overweight one side?
   - Does he hedge immediately or wait for price movement?

4. POSITION MANAGEMENT
   - Up/Down share imbalance per market — intentional or execution artifact?
   - Combined VWAP vs 1.00 — is he targeting positive edge?
   - Position scaling: does he add to positions or enter once?

5. MERGE BEHAVIOR
   - When does he merge? (immediately after hedge, or accumulate?)
   - Merge sizes vs position sizes

6. MARKET SELECTION
   - Which market types (5m, 15m, hourly)?
   - How many concurrent markets?
   - Does he avoid certain markets?

7. CONFIDENCE RATINGS
   For each section, rate your confidence: HIGH / MEDIUM / LOW
   based on how much data supports the conclusion.

8. GRID STRUCTURE
   - Price level distribution: how many fills at each 1-cent level?
   - Grid concentration: % of fills within 5c/10c/20c of median — flat or bell-curve?
   - Grid replenishment: how quickly does the same price level refill after a fill?

9. MARKET MICROSTRUCTURE
   - Order book depth: bid/ask depth within 10c of best price
   - Spread: typical spread for markets gabagool is active in
   - How does book depth correlate with his fill rate?

10. VOLATILITY CORRELATION
    - How does BTC 5m volatility correlate with his edge?
    - Does he adjust grid width in high-volatility vs low-volatility periods?

Format output as markdown with clear headers. Be specific with numbers.
End with a "WORKING HYPOTHESIS" section: a 3-5 sentence summary of how
the bot works end-to-end, as if writing pseudocode for replication.
SYSPROMPT

# ── SQL queries ───────────────────────────────────────────────────────────────

run_queries() {
  local db="$1"

  echo "=== 1. TRADE SUMMARY BY SIDE/OUTCOME/ROLE ==="
  sqlite3 -header -column "$db" "
    SELECT side, outcome, role,
           COUNT(*) as trades,
           ROUND(AVG(price), 4) as avg_price,
           ROUND(MIN(price), 4) as min_price,
           ROUND(MAX(price), 4) as max_price,
           ROUND(SUM(usdc_size), 2) as total_usdc,
           ROUND(AVG(size), 2) as avg_clip
    FROM obs_trades
    GROUP BY side, outcome, role
    ORDER BY side, outcome, role;
  "

  echo ""
  echo "=== 2. PER-MARKET CHRONOLOGY ==="
  sqlite3 -header -column "$db" "
    SELECT slug,
           COUNT(*) as trades,
           datetime(MIN(ts), 'unixepoch') as first_trade,
           datetime(MAX(ts), 'unixepoch') as last_trade,
           ROUND(MAX(ts) - MIN(ts), 1) as span_sec,
           GROUP_CONCAT(DISTINCT outcome) as outcomes,
           GROUP_CONCAT(DISTINCT role) as roles
    FROM obs_trades
    GROUP BY slug
    ORDER BY MIN(ts);
  "

  echo ""
  echo "=== 3. HEDGE DELAY (first Up buy → first Down buy per slug) ==="
  sqlite3 -header -column "$db" "
    WITH first_up AS (
      SELECT slug, MIN(ts) as first_up_ts
      FROM obs_trades WHERE outcome = 'Up' AND side = 'BUY'
      GROUP BY slug
    ),
    first_down AS (
      SELECT slug, MIN(ts) as first_down_ts
      FROM obs_trades WHERE outcome = 'Down' AND side = 'BUY'
      GROUP BY slug
    )
    SELECT u.slug,
           datetime(u.first_up_ts, 'unixepoch') as first_up,
           datetime(d.first_down_ts, 'unixepoch') as first_down,
           ROUND(d.first_down_ts - u.first_up_ts, 1) as delay_sec
    FROM first_up u
    JOIN first_down d ON u.slug = d.slug
    ORDER BY u.first_up_ts;
  "

  echo ""
  echo "=== 4. PRICE DRIFT PER SLUG+OUTCOME ==="
  sqlite3 -header -column "$db" "
    SELECT slug, outcome,
           COUNT(*) as fills,
           ROUND(MIN(price), 4) as min_px,
           ROUND(MAX(price), 4) as max_px,
           ROUND(AVG(price), 4) as avg_px,
           ROUND(MAX(price) - MIN(price), 4) as drift
    FROM obs_trades
    WHERE side = 'BUY'
    GROUP BY slug, outcome
    ORDER BY slug, outcome;
  "

  echo ""
  echo "=== 5. REPRICING CADENCE (trades per 2-second window) ==="
  sqlite3 -header -column "$db" "
    SELECT slug, outcome,
           CAST(ts / 2 AS INTEGER) * 2 as window_ts,
           datetime(CAST(ts / 2 AS INTEGER) * 2, 'unixepoch') as window_time,
           COUNT(*) as fills_in_window,
           ROUND(MIN(price), 4) as lo,
           ROUND(MAX(price), 4) as hi
    FROM obs_trades
    WHERE side = 'BUY'
    GROUP BY slug, outcome, CAST(ts / 2 AS INTEGER)
    HAVING COUNT(*) > 1
    ORDER BY window_ts;
  "

  echo ""
  echo "=== 6. MARKET WINDOWS (aggregated view) ==="
  sqlite3 -header -column "$db" "
    SELECT slug, status,
           ROUND(up_vwap, 4) as up_vwap,
           ROUND(down_vwap, 4) as down_vwap,
           ROUND(up_shares, 2) as up_shares,
           ROUND(down_shares, 2) as down_shares,
           ROUND(combined_cost, 4) as combined_cost,
           ROUND(estimated_edge, 4) as edge,
           ROUND(hedge_delay_sec, 1) as hedge_delay,
           ROUND(merged_shares, 2) as merged,
           first_trade_at,
           last_trade_at
    FROM obs_market_windows
    ORDER BY first_trade_at;
  "

  echo ""
  echo "=== 7. LATEST POSITIONS ==="
  sqlite3 -header -column "$db" "
    SELECT p.slug, p.outcome,
           ROUND(p.size, 4) as shares,
           ROUND(p.avg_price, 4) as avg_px,
           ROUND(p.cur_price, 4) as cur_px,
           ROUND(p.cash_pnl, 4) as pnl,
           datetime(p.ts, 'unixepoch') as snapshot_at
    FROM obs_positions p
    INNER JOIN (
      SELECT slug, outcome, MAX(ts) as max_ts
      FROM obs_positions
      GROUP BY slug, outcome
    ) latest ON p.slug = latest.slug
            AND p.outcome = latest.outcome
            AND p.ts = latest.max_ts
    ORDER BY p.slug, p.outcome;
  "

  echo ""
  echo "=== 8. MERGES ==="
  sqlite3 -header -column "$db" "
    SELECT tx_hash,
           ROUND(shares, 2) as shares,
           block_number,
           datetime(ts, 'unixepoch') as merge_time
    FROM obs_merges
    ORDER BY ts;
  "

  # Query 8b: only run if obs_redemptions table exists
  if sqlite3 "$db" "SELECT name FROM sqlite_master WHERE type='table' AND name='obs_redemptions';" | grep -q obs_redemptions; then
    echo ""
    echo "=== 8b. REDEMPTIONS (single-sided position decreases from resolved markets) ==="
    sqlite3 -header -column "$db" "
      SELECT slug, outcome,
             ROUND(shares, 2) as shares,
             ROUND(from_size, 2) as from_size,
             ROUND(to_size, 2) as to_size,
             datetime(ts, 'unixepoch') as redeemed_at
      FROM obs_redemptions
      ORDER BY ts;
    "
  fi

  echo ""
  echo "=== 9. CLIP SIZE DISTRIBUTION ==="
  sqlite3 -header -column "$db" "
    SELECT
      CASE
        WHEN size < 5 THEN '0-5'
        WHEN size < 10 THEN '5-10'
        WHEN size < 20 THEN '10-20'
        WHEN size < 50 THEN '20-50'
        WHEN size < 100 THEN '50-100'
        ELSE '100+'
      END as size_bucket,
      COUNT(*) as count,
      ROUND(AVG(price), 4) as avg_price,
      ROUND(AVG(usdc_size), 2) as avg_usdc
    FROM obs_trades
    WHERE side = 'BUY'
    GROUP BY size_bucket
    ORDER BY MIN(size);
  "

  echo ""
  echo "=== 10. ROLE BY MARKET (MAKER/TAKER % per slug) ==="
  sqlite3 -header -column "$db" "
    SELECT slug,
           COUNT(*) as total,
           SUM(CASE WHEN role = 'MAKER' THEN 1 ELSE 0 END) as maker_ct,
           SUM(CASE WHEN role = 'TAKER' THEN 1 ELSE 0 END) as taker_ct,
           ROUND(100.0 * SUM(CASE WHEN role = 'MAKER' THEN 1 ELSE 0 END) / COUNT(*), 1) as maker_pct,
           ROUND(100.0 * SUM(CASE WHEN role = 'TAKER' THEN 1 ELSE 0 END) / COUNT(*), 1) as taker_pct
    FROM obs_trades
    GROUP BY slug
    ORDER BY total DESC;
  "

  echo ""
  echo "=== 11. ENTRY SIDE ANALYSIS (which outcome bought first per market) ==="
  sqlite3 -header -column "$db" "
    WITH first_buy AS (
      SELECT slug, outcome, MIN(ts) as first_ts
      FROM obs_trades WHERE side = 'BUY'
      GROUP BY slug, outcome
    ),
    ranked AS (
      SELECT slug, outcome, first_ts,
             ROW_NUMBER() OVER (PARTITION BY slug ORDER BY first_ts) as rn
      FROM first_buy
    )
    SELECT slug, outcome as first_entry_side,
           datetime(first_ts, 'unixepoch') as entry_time
    FROM ranked
    WHERE rn = 1
    ORDER BY first_ts;
  "

  echo ""
  echo "=== 12. TRADE TIMELINE (last 200 trades, chronological) ==="
  sqlite3 -header -column "$db" "
    SELECT datetime(ts, 'unixepoch') as time,
           slug, side, outcome, role,
           ROUND(price, 4) as price,
           ROUND(size, 2) as size,
           ROUND(usdc_size, 2) as usdc
    FROM obs_trades
    ORDER BY ts DESC
    LIMIT 200;
  "

  echo ""
  echo "=== 13. PRICE LEVEL DISTRIBUTION (fills bucketed into 1-cent increments) ==="
  sqlite3 -header -column "$db" "
    SELECT slug, outcome,
           ROUND(price, 2) as price_level,
           COUNT(*) as fills,
           ROUND(SUM(size), 2) as total_size,
           ROUND(SUM(usdc_size), 2) as total_usdc
    FROM obs_trades
    WHERE side = 'BUY'
    GROUP BY slug, outcome, ROUND(price, 2)
    ORDER BY slug, outcome, price_level;
  "

  echo ""
  echo "=== 14. GRID CONCENTRATION (% of fills within 5c/10c/20c of median) ==="
  sqlite3 -header -column "$db" "
    WITH medians AS (
      SELECT slug, outcome,
             AVG(price) as median_price
      FROM (
        SELECT slug, outcome, price,
               ROW_NUMBER() OVER (PARTITION BY slug, outcome ORDER BY price) as rn,
               COUNT(*) OVER (PARTITION BY slug, outcome) as cnt
        FROM obs_trades WHERE side = 'BUY'
      )
      WHERE rn IN (cnt/2, cnt/2+1)
      GROUP BY slug, outcome
    )
    SELECT t.slug, t.outcome,
           ROUND(m.median_price, 4) as median_px,
           COUNT(*) as total_fills,
           SUM(CASE WHEN ABS(t.price - m.median_price) <= 0.05 THEN 1 ELSE 0 END) as within_5c,
           ROUND(100.0 * SUM(CASE WHEN ABS(t.price - m.median_price) <= 0.05 THEN 1 ELSE 0 END) / COUNT(*), 1) as pct_5c,
           SUM(CASE WHEN ABS(t.price - m.median_price) <= 0.10 THEN 1 ELSE 0 END) as within_10c,
           ROUND(100.0 * SUM(CASE WHEN ABS(t.price - m.median_price) <= 0.10 THEN 1 ELSE 0 END) / COUNT(*), 1) as pct_10c,
           SUM(CASE WHEN ABS(t.price - m.median_price) <= 0.20 THEN 1 ELSE 0 END) as within_20c,
           ROUND(100.0 * SUM(CASE WHEN ABS(t.price - m.median_price) <= 0.20 THEN 1 ELSE 0 END) / COUNT(*), 1) as pct_20c
    FROM obs_trades t
    JOIN medians m ON t.slug = m.slug AND t.outcome = m.outcome
    WHERE t.side = 'BUY'
    GROUP BY t.slug, t.outcome
    ORDER BY t.slug, t.outcome;
  "

  echo ""
  echo "=== 15. INTER-FILL TIMING AT SAME PRICE LEVELS (grid replenishment) ==="
  sqlite3 -header -column "$db" "
    WITH price_fills AS (
      SELECT slug, outcome,
             ROUND(price, 2) as price_level,
             ts,
             LAG(ts) OVER (PARTITION BY slug, outcome, ROUND(price, 2) ORDER BY ts) as prev_ts
      FROM obs_trades
      WHERE side = 'BUY'
    )
    SELECT slug, outcome, price_level,
           COUNT(*) as fills_at_level,
           ROUND(AVG(ts - prev_ts), 1) as avg_refill_sec,
           ROUND(MIN(ts - prev_ts), 1) as min_refill_sec,
           ROUND(MAX(ts - prev_ts), 1) as max_refill_sec
    FROM price_fills
    WHERE prev_ts IS NOT NULL
    GROUP BY slug, outcome, price_level
    HAVING COUNT(*) >= 3
    ORDER BY slug, outcome, price_level;
  "

  echo ""
  echo "=== 16. CROSS-SESSION COMPARISON ==="
  sqlite3 -header -column "$db" "
    SELECT s.id as session_id,
           datetime(s.started_at, 'unixepoch') as started,
           datetime(s.ended_at, 'unixepoch') as ended,
           ROUND((COALESCE(s.ended_at, strftime('%s','now')) - s.started_at) / 60.0, 1) as duration_min,
           COUNT(DISTINCT t.slug) as markets,
           COUNT(t.id) as trades,
           ROUND(SUM(t.usdc_size), 2) as total_usdc,
           ROUND(AVG(t.size), 2) as avg_clip,
           ROUND(100.0 * SUM(CASE WHEN t.role = 'MAKER' THEN 1 ELSE 0 END) / NULLIF(COUNT(t.id), 0), 1) as maker_pct
    FROM obs_sessions s
    LEFT JOIN obs_trades t ON t.session_id = s.id
    GROUP BY s.id
    ORDER BY s.started_at;
  "

  echo ""
  echo "=== 17. POSITION SIZE OVER TIME (growth rate per market) ==="
  sqlite3 -header -column "$db" "
    SELECT slug, outcome,
           datetime(ts, 'unixepoch') as snapshot_time,
           ROUND(size, 2) as shares,
           ROUND(size - LAG(size) OVER (PARTITION BY slug, outcome ORDER BY ts), 2) as delta
    FROM obs_positions
    WHERE size > 0
    ORDER BY slug, outcome, ts;
  "

  # Query 18: only run if obs_book_snapshots table exists
  if sqlite3 "$db" "SELECT name FROM sqlite_master WHERE type='table' AND name='obs_book_snapshots';" | grep -q obs_book_snapshots; then
    echo ""
    echo "=== 18. BOOK SNAPSHOT SUMMARY ==="
    sqlite3 -header -column "$db" "
      SELECT token_id,
             COUNT(*) as snapshots,
             ROUND(AVG(spread), 4) as avg_spread,
             ROUND(AVG(mid_price), 4) as avg_mid,
             ROUND(AVG(bid_depth_10c), 2) as avg_bid_depth,
             ROUND(AVG(ask_depth_10c), 2) as avg_ask_depth,
             ROUND(AVG(bid_levels), 1) as avg_bid_levels,
             ROUND(AVG(ask_levels), 1) as avg_ask_levels
      FROM obs_book_snapshots
      GROUP BY token_id
      ORDER BY COUNT(*) DESC;
    "
  fi

  # Query 19: only run if obs_prices table exists
  if sqlite3 "$db" "SELECT name FROM sqlite_master WHERE type='table' AND name='obs_prices';" | grep -q obs_prices; then
    echo ""
    echo "=== 19. BTC PRICE & VOLATILITY ==="
    sqlite3 -header -column "$db" "
      SELECT datetime(ts, 'unixepoch') as time,
             ROUND(btc_price, 2) as btc,
             ROUND(eth_price, 2) as eth,
             ROUND(btc_pct_change_1m * 100, 3) as btc_1m_pct,
             ROUND(btc_pct_change_5m * 100, 3) as btc_5m_pct,
             ROUND(btc_rolling_vol_5m * 100, 4) as btc_vol_5m,
             ROUND(btc_range_pct_5m * 100, 3) as btc_range_5m
      FROM obs_prices
      ORDER BY ts DESC
      LIMIT 30;
    "
  fi
}

# ── main loop ─────────────────────────────────────────────────────────────────

echo "gabagool analysis loop started — interval=${INTERVAL}s, log=$LOG"
echo "Press Ctrl+C to stop"

while true; do
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Running analysis cycle..."

  # 1. Gather data
  DATA=$(run_queries "$DB" 2>&1)

  TRADE_COUNT=$(sqlite3 "$DB" "SELECT COUNT(*) FROM obs_trades;")
  if [[ "$TRADE_COUNT" -eq 0 ]]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] No trades in DB yet, skipping cycle"
    sleep "$INTERVAL"
    continue
  fi

  # 2. Build prompt
  PROMPT="${SYSTEM_PROMPT}

--- RAW OBSERVER DATA (${TRADE_COUNT} trades) ---

${DATA}"

  # 3. Pipe to claude (unset CLAUDE_CODE_ENTRYPOINT to avoid nested session issues)
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Sending ${TRADE_COUNT} trades to Claude ${MODEL}..."
  RESPONSE=$(echo "$PROMPT" | CLAUDECODE="" claude -p --model "$MODEL" 2>&1) || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: claude command failed" >&2
    echo "======== $(date '+%Y-%m-%d %H:%M:%S') — ERROR ========" >> "$LOG"
    echo "Claude command failed. Check that 'claude' CLI is available." >> "$LOG"
    echo "" >> "$LOG"
    sleep "$INTERVAL"
    continue
  }

  # 4. Append timestamped analysis to log
  {
    echo "======== $(date '+%Y-%m-%d %H:%M:%S') — ${TRADE_COUNT} trades analyzed ========"
    echo ""
    echo "$RESPONSE"
    echo ""
    echo ""
  } >> "$LOG"

  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Analysis written to $LOG"

  # 5. Sleep
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] Next cycle in ${INTERVAL}s"
  sleep "$INTERVAL"
done
