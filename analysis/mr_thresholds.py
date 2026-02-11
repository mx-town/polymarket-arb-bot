#!/usr/bin/env python3
"""
Mean-reversion threshold analysis for BTC/USDT 15-minute windows.

Fetches 14 days of 1-minute candles from Binance, groups them into
15-minute windows aligned to Polymarket's schedule (timestamps divisible
by 900 seconds), and computes reversion probabilities by deviation bucket
and time into window.
"""

import json
import math
import time
import urllib.request
from collections import defaultdict

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
SYMBOL = "BTCUSDT"
INTERVAL = "1m"
DAYS = 14
WINDOW_SEC = 900  # 15 minutes
CANDLE_SEC = 60
CANDLES_PER_WINDOW = WINDOW_SEC // CANDLE_SEC  # 15
TOLERANCE_PCT = 0.05  # 0.05% tolerance for "near-reversion"

# Deviation buckets (in %)
BUCKET_EDGES = [0.00, 0.02, 0.04, 0.06, 0.08, 0.10, 0.12, 0.14, 0.16, 0.18, 0.20]

# ---------------------------------------------------------------------------
# Binance API
# ---------------------------------------------------------------------------
BASE_URL = "https://api.binance.com/api/v3/klines"


def fetch_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list:
    """Fetch all klines between start_ms and end_ms, paginating as needed."""
    all_klines = []
    current_start = start_ms
    page = 0

    while current_start < end_ms:
        params = (
            f"symbol={symbol}&interval={interval}"
            f"&startTime={current_start}&endTime={end_ms}&limit=1000"
        )
        url = f"{BASE_URL}?{params}"
        page += 1

        for attempt in range(3):
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode())
                break
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"  retry {attempt+1} after error: {e}")
                time.sleep(2)

        if not data:
            break

        all_klines.extend(data)
        # Next page starts after the last candle's open time
        last_open = data[-1][0]
        current_start = last_open + (CANDLE_SEC * 1000)

        # Rate-limit courtesy
        time.sleep(0.25)

        if len(data) < 1000:
            break

    print(f"  fetched {len(all_klines)} candles in {page} requests")
    return all_klines


# ---------------------------------------------------------------------------
# Grouping into 15-minute windows
# ---------------------------------------------------------------------------

def group_into_windows(klines: list) -> dict:
    """
    Group 1m candles into 15m windows aligned to 900s boundaries.
    Returns {window_start_ms: [candle, ...]} with candles sorted by time.
    Each candle is (open_time_ms, open, high, low, close).
    """
    windows = defaultdict(list)

    for k in klines:
        open_time_ms = k[0]
        open_time_s = open_time_ms // 1000
        # Align to 900s boundary
        window_start_s = (open_time_s // WINDOW_SEC) * WINDOW_SEC
        window_start_ms = window_start_s * 1000

        candle = (
            open_time_ms,
            float(k[1]),  # open
            float(k[2]),  # high
            float(k[3]),  # low
            float(k[4]),  # close
        )
        windows[window_start_ms].append(candle)

    # Sort candles within each window and filter incomplete windows
    complete = {}
    for ws, candles in sorted(windows.items()):
        candles.sort(key=lambda c: c[0])
        if len(candles) >= CANDLES_PER_WINDOW:
            complete[ws] = candles[:CANDLES_PER_WINDOW]

    return complete


# ---------------------------------------------------------------------------
# Analysis
# ---------------------------------------------------------------------------

def bucket_index(dev_pct: float) -> int:
    """Return bucket index for a deviation percentage (absolute value)."""
    abs_dev = abs(dev_pct)
    for i in range(len(BUCKET_EDGES) - 1):
        if abs_dev < BUCKET_EDGES[i + 1]:
            return i
    return len(BUCKET_EDGES) - 1  # overflow bucket (0.20%+)


def bucket_label(idx: int) -> str:
    if idx >= len(BUCKET_EDGES) - 1:
        return f"{BUCKET_EDGES[-1]:.2f}%+"
    return f"{BUCKET_EDGES[idx]:.2f}-{BUCKET_EDGES[idx+1]:.2f}%"


def analyze_windows(windows: dict):
    """
    For each window, at each minute mark T (1..14):
    - deviation = (close_at_T - window_open) / window_open
    - does price cross back through open after T? (exact reversion)
    - does price come within TOLERANCE_PCT of open after T? (near reversion)
    """

    # Storage: reversion_data[minute_offset][bucket_idx] = {n, reverted, near_reverted}
    reversion_data = defaultdict(lambda: defaultdict(lambda: {"n": 0, "reverted": 0, "near_reverted": 0}))

    # Per-minute deviation tracking
    minute_deviations = defaultdict(list)  # minute_offset -> [abs_dev_pct, ...]

    # Overall window stats
    max_deviations = []  # max abs deviation per window

    for ws, candles in windows.items():
        window_open = candles[0][1]  # open price of first candle
        if window_open == 0:
            continue

        # Precompute closes at each minute
        closes = [c[4] for c in candles]  # close price of each 1m candle
        # Also track highs and lows for intra-candle reversion detection
        highs = [c[2] for c in candles]
        lows = [c[3] for c in candles]

        window_max_dev = 0.0

        for t in range(1, CANDLES_PER_WINDOW):
            # Deviation at minute T (using close of candle T, which is T minutes in)
            close_t = closes[t]
            dev = (close_t - window_open) / window_open
            dev_pct = dev * 100.0
            abs_dev_pct = abs(dev_pct)

            minute_deviations[t].append(abs_dev_pct)
            window_max_dev = max(window_max_dev, abs_dev_pct)

            # Check reversion: does price cross through open after minute T?
            reverted = False
            near_reverted = False

            if abs_dev_pct < 0.001:
                # Already at open, trivially reverted
                reverted = True
                near_reverted = True
            else:
                for j in range(t + 1, CANDLES_PER_WINDOW):
                    # Check if candle j's range crosses the open price
                    if lows[j] <= window_open <= highs[j]:
                        reverted = True
                        near_reverted = True
                        break

                    # Check near-reversion (within tolerance)
                    if not near_reverted:
                        candle_close = closes[j]
                        near_dev = abs(candle_close - window_open) / window_open * 100.0
                        if near_dev <= TOLERANCE_PCT:
                            near_reverted = True

                        # Also check high/low proximity
                        for price in (highs[j], lows[j]):
                            near_dev = abs(price - window_open) / window_open * 100.0
                            if near_dev <= TOLERANCE_PCT:
                                near_reverted = True

            bidx = bucket_index(dev_pct)
            entry = reversion_data[t][bidx]
            entry["n"] += 1
            if reverted:
                entry["reverted"] += 1
            if near_reverted:
                entry["near_reverted"] += 1

        max_deviations.append(window_max_dev)

    return reversion_data, minute_deviations, max_deviations


# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

def print_results(reversion_data, minute_deviations, max_deviations, n_windows):
    sep = "=" * 100

    print(f"\n{sep}")
    print(f"  BTC/USDT 15-Minute Window Mean-Reversion Analysis")
    print(f"  {DAYS} days | {n_windows} complete windows | tolerance = {TOLERANCE_PCT}%")
    print(sep)

    # --- Overall stats ---
    print(f"\n--- Overall Window Statistics ---\n")

    if max_deviations:
        max_deviations_sorted = sorted(max_deviations)
        n = len(max_deviations_sorted)
        mean_max = sum(max_deviations_sorted) / n
        median_max = max_deviations_sorted[n // 2]

        above_004 = sum(1 for d in max_deviations_sorted if d > 0.04) / n * 100
        above_010 = sum(1 for d in max_deviations_sorted if d > 0.10) / n * 100
        above_020 = sum(1 for d in max_deviations_sorted if d > 0.20) / n * 100

        print(f"  Max deviation per window:")
        print(f"    Mean:   {mean_max:.4f}%")
        print(f"    Median: {median_max:.4f}%")
        print(f"    P75:    {max_deviations_sorted[int(n*0.75)]:.4f}%")
        print(f"    P90:    {max_deviations_sorted[int(n*0.90)]:.4f}%")
        print(f"    P95:    {max_deviations_sorted[int(n*0.95)]:.4f}%")
        print(f"    P99:    {max_deviations_sorted[int(n*0.99)]:.4f}%")
        print(f"    Max:    {max_deviations_sorted[-1]:.4f}%")
        print()
        print(f"  Windows with max deviation > 0.04%: {above_004:.1f}%")
        print(f"  Windows with max deviation > 0.10%: {above_010:.1f}%")
        print(f"  Windows with max deviation > 0.20%: {above_020:.1f}%")

    # --- Per-minute deviation stats ---
    print(f"\n--- Deviation by Minute into Window ---\n")
    print(f"  {'Minute':>6}  {'Mean':>8}  {'Median':>8}  {'P75':>8}  {'P90':>8}  {'P95':>8}  {'Samples':>8}")
    print(f"  {'-'*6}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}  {'-'*8}")

    for t in range(1, CANDLES_PER_WINDOW):
        devs = sorted(minute_deviations.get(t, []))
        if not devs:
            continue
        n = len(devs)
        mean_d = sum(devs) / n
        median_d = devs[n // 2]
        p75 = devs[int(n * 0.75)]
        p90 = devs[int(n * 0.90)]
        p95 = devs[int(n * 0.95)]
        print(f"  {t:>4}m   {mean_d:>7.4f}%  {median_d:>7.4f}%  {p75:>7.4f}%  {p90:>7.4f}%  {p95:>7.4f}%  {n:>8}")

    # --- Reversion probability table ---
    print(f"\n--- Reversion Probability by Deviation Bucket and Time ---\n")
    print(f"  (Exact reversion = price crosses back through open after minute T)")
    print(f"  (Near reversion  = price comes within {TOLERANCE_PCT}% of open after minute T)\n")

    # Collect all buckets that have data
    all_buckets = set()
    for t in reversion_data:
        for b in reversion_data[t]:
            all_buckets.add(b)
    all_buckets = sorted(all_buckets)

    for bidx in all_buckets:
        label = bucket_label(bidx)
        print(f"\n  Deviation bucket: {label}")
        print(f"  {'Minute':>6}  {'Samples':>8}  {'Exact Rev%':>10}  {'Near Rev%':>10}")
        print(f"  {'-'*6}  {'-'*8}  {'-'*10}  {'-'*10}")

        for t in range(1, CANDLES_PER_WINDOW):
            entry = reversion_data.get(t, {}).get(bidx)
            if not entry or entry["n"] == 0:
                continue
            n = entry["n"]
            exact_pct = entry["reverted"] / n * 100
            near_pct = entry["near_reverted"] / n * 100
            print(f"  {t:>4}m   {n:>8}  {exact_pct:>9.1f}%  {near_pct:>9.1f}%")

    # --- Compact summary: reversion at key time points ---
    print(f"\n--- Compact Summary: Reversion Probability at Key Points ---\n")
    key_minutes = [3, 5, 7, 10, 12, 14]
    key_buckets = [2, 3, 4, 5, 6, 7, 8, 9, 10]  # 0.04%+ buckets

    header = f"  {'Bucket':<12}"
    for t in key_minutes:
        header += f"  {'T='+str(t)+'m':>10}"
    print(header)
    print(f"  {'-'*12}" + f"  {'-'*10}" * len(key_minutes))

    for bidx in key_buckets:
        if bidx not in all_buckets:
            continue
        label = bucket_label(bidx)
        row = f"  {label:<12}"
        for t in key_minutes:
            entry = reversion_data.get(t, {}).get(bidx)
            if entry and entry["n"] >= 3:
                pct = entry["reverted"] / entry["n"] * 100
                n = entry["n"]
                row += f"  {pct:>5.0f}%/{n:<3}"
            else:
                row += f"  {'---':>10}"
        print(row)

    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    now_ms = int(time.time() * 1000)
    start_ms = now_ms - (DAYS * 24 * 60 * 60 * 1000)

    print(f"Fetching {DAYS} days of {SYMBOL} 1m candles from Binance...")
    klines = fetch_klines(SYMBOL, INTERVAL, start_ms, now_ms)

    if not klines:
        print("ERROR: No data fetched")
        return

    print(f"Grouping into 15-minute windows (aligned to {WINDOW_SEC}s boundaries)...")
    windows = group_into_windows(klines)
    print(f"  {len(windows)} complete 15-minute windows")

    print("Analyzing reversion patterns...")
    reversion_data, minute_deviations, max_deviations = analyze_windows(windows)

    print_results(reversion_data, minute_deviations, max_deviations, len(windows))


if __name__ == "__main__":
    main()
