#!/usr/bin/env python3
"""Calculate realized PnL from a Polymarket CSV export.

Usage:
    python scripts/calc_pnl.py <csv_path> [--start-at UNIX_TIMESTAMP]

Actions in the CSV:
    Buy   — spent usdcAmount, received tokenAmount of tokenName (Up/Down)
    Sell  — received usdcAmount, sold tokenAmount of tokenName
    Merge — received usdcAmount (= tokenAmount, since 1 pair = $1), burned pairs
"""

import argparse
import csv
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path


def parse_csv(path: str, start_at: int = 0) -> list[dict]:
    rows = []
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            ts = int(row["timestamp"])
            if ts >= start_at:
                rows.append(row)
    rows.sort(key=lambda r: int(r["timestamp"]))
    return rows


def calc_pnl(rows: list[dict]) -> None:
    markets: dict[str, dict] = defaultdict(lambda: {
        "usdc_out": 0.0,    # total USDC spent buying
        "usdc_in": 0.0,     # total USDC received (merges + sells)
        "up_bought": 0.0,   # total Up shares bought
        "down_bought": 0.0, # total Down shares bought
        "up_cost": 0.0,
        "down_cost": 0.0,
        "merged": 0.0,      # total pairs merged
        "up_sold": 0.0,
        "down_sold": 0.0,
        "sell_revenue": 0.0,
        "buys": 0,
        "merges": 0,
        "sells": 0,
    })

    for row in rows:
        mkt = row["marketName"]
        action = row["action"]
        usdc = float(row["usdcAmount"])
        tokens = float(row["tokenAmount"])
        side = row["tokenName"]
        m = markets[mkt]

        if action == "Buy":
            m["usdc_out"] += usdc
            m["buys"] += 1
            if side == "Up":
                m["up_bought"] += tokens
                m["up_cost"] += usdc
            elif side == "Down":
                m["down_bought"] += tokens
                m["down_cost"] += usdc

        elif action == "Sell":
            m["usdc_in"] += usdc
            m["sell_revenue"] += usdc
            m["sells"] += 1
            if side == "Up":
                m["up_sold"] += tokens
            elif side == "Down":
                m["down_sold"] += tokens

        elif action == "Merge":
            m["usdc_in"] += usdc
            m["merged"] += tokens
            m["merges"] += 1

    # Print per-market breakdown
    total_spent = 0.0
    total_received = 0.0
    total_hedged_remaining = 0.0
    total_unhedged_cost = 0.0

    for mkt_name in sorted(markets.keys()):
        m = markets[mkt_name]
        up_remaining = m["up_bought"] - m["merged"] - m["up_sold"]
        down_remaining = m["down_bought"] - m["merged"] - m["down_sold"]
        up_remaining = max(0, up_remaining)
        down_remaining = max(0, down_remaining)
        hedged_remaining = min(up_remaining, down_remaining)
        unhedged_up = up_remaining - hedged_remaining
        unhedged_down = down_remaining - hedged_remaining

        # VWAPs
        up_vwap = m["up_cost"] / m["up_bought"] if m["up_bought"] > 0 else 0
        down_vwap = m["down_cost"] / m["down_bought"] if m["down_bought"] > 0 else 0

        # Hedged remaining value: pairs worth $1.00 each, cost = hedged * (up_vwap + down_vwap)
        hedged_value = hedged_remaining * 1.0
        hedged_cost = hedged_remaining * (up_vwap + down_vwap)
        hedged_pnl = hedged_value - hedged_cost

        # Unhedged: at-risk capital (may expire worthless)
        unhedged_cost = unhedged_up * up_vwap + unhedged_down * down_vwap

        # Realized from merges: merge_usdc - cost_of_merged_pairs
        merge_cost = m["merged"] * (up_vwap + down_vwap)
        merge_pnl = m["usdc_in"] - m["sell_revenue"] - merge_cost  # merge revenue - merge cost

        total_spent += m["usdc_out"]
        total_received += m["usdc_in"]
        total_hedged_remaining += hedged_pnl
        total_unhedged_cost += unhedged_cost

        short_name = mkt_name[:65]
        c_g, c_r, c_y, rst = "\033[32m", "\033[31m", "\033[33m", "\033[0m"

        print(f"  {short_name}")
        print(f"    Buys: {m['buys']}  Merges: {m['merges']}  Sells: {m['sells']}")
        print(f"    Up  VWAP: ${up_vwap:.4f}  bought={m['up_bought']:.1f}  remaining={up_remaining:.1f}")
        print(f"    Down VWAP: ${down_vwap:.4f}  bought={m['down_bought']:.1f}  remaining={down_remaining:.1f}")
        c = c_g if merge_pnl >= 0 else c_r
        print(f"    Merged: {m['merged']:.1f} pairs → ${m['usdc_in'] - m['sell_revenue']:.2f} received, cost=${merge_cost:.2f}, {c}pnl=${merge_pnl:.2f}{rst}")
        if hedged_remaining > 0:
            c = c_g if hedged_pnl >= 0 else c_r
            print(f"    Hedged remaining: {hedged_remaining:.1f} pairs, value=${hedged_value:.2f}, cost=${hedged_cost:.2f}, {c}pnl=${hedged_pnl:.2f}{rst}")
        if unhedged_up > 0 or unhedged_down > 0:
            side_str = f"U{unhedged_up:.1f}" if unhedged_up > 0 else f"D{unhedged_down:.1f}"
            print(f"    {c_y}Unhedged: {side_str}, cost=${unhedged_cost:.2f} (at risk){rst}")

    # Totals
    print()
    print("─" * 80)
    net_cash = total_received - total_spent
    c_g, c_r, rst = "\033[32m", "\033[31m", "\033[0m"

    c = c_g if net_cash >= 0 else c_r
    print(f"  Cash flow:  spent=${total_spent:.2f}  received=${total_received:.2f}  {c}net=${net_cash:.2f}{rst}")

    c = c_g if total_hedged_remaining >= 0 else c_r
    print(f"  Hedged remaining (will merge for $1/pair): {c}${total_hedged_remaining:.2f} unrealized{rst}")

    print(f"  {c_y}Unhedged at risk: ${total_unhedged_cost:.2f}{rst}")

    # Remaining hedged pairs will return $1/pair when merged
    total_hedged_value = sum(
        min(max(0, m["up_bought"] - m["merged"] - m["up_sold"]),
            max(0, m["down_bought"] - m["merged"] - m["down_sold"]))
        for m in markets.values()
    )

    print()
    # Best case: merge remaining hedged pairs, recover unhedged cost
    best_case = net_cash + total_hedged_value + total_unhedged_cost
    # Worst case: merge remaining hedged, unhedged expires worthless
    worst_case = net_cash + total_hedged_value
    c = c_g if best_case >= 0 else c_r
    print(f"  Best case  (hedged merges, unhedged recovers): {c}${best_case:.2f}{rst}")
    c = c_g if worst_case >= 0 else c_r
    print(f"  Worst case (hedged merges, unhedged expires):  {c}${worst_case:.2f}{rst}")
    c = c_g if total_hedged_remaining >= 0 else c_r
    print(f"  Edge on merged+hedged pairs:                   {c}${total_hedged_remaining + (total_received - total_spent + total_unhedged_cost + total_hedged_value - best_case):.2f}{rst}")
    # Simpler: just compute merge edge
    merge_edge = total_received - total_spent + total_hedged_value + total_unhedged_cost
    c = c_g if merge_edge >= 0 else c_r
    print(f"  Net edge (profit if all positions close flat):  {c}${merge_edge:.2f}{rst}")


def main():
    parser = argparse.ArgumentParser(description="Calculate PnL from Polymarket CSV export")
    parser.add_argument("csv_path", help="Path to the CSV file")
    parser.add_argument("--start-at", type=int, default=0, help="Unix timestamp to start from")
    args = parser.parse_args()

    if not Path(args.csv_path).exists():
        print(f"File not found: {args.csv_path}", file=sys.stderr)
        sys.exit(1)

    rows = parse_csv(args.csv_path, args.start_at)
    if not rows:
        print("No transactions found after the given timestamp.")
        sys.exit(0)

    ts_min = min(int(r["timestamp"]) for r in rows)
    ts_max = max(int(r["timestamp"]) for r in rows)
    print(f"\nPnL Report: {len(rows)} transactions")
    print(f"  From: {datetime.fromtimestamp(ts_min, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print(f"  To:   {datetime.fromtimestamp(ts_max, tz=timezone.utc).strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print()

    calc_pnl(rows)


if __name__ == "__main__":
    main()
