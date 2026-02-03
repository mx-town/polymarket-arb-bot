#!/usr/bin/env python3
"""
Polymarket Spread Analyzer

Analyzes ACTUAL CLOB order book spreads.
Shows both buy (arb) cost and market efficiency metrics.
"""

import argparse
import json
from dataclasses import dataclass

import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams

CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"


@dataclass
class MarketData:
    question: str
    yes_ask: float
    no_ask: float
    yes_bid: float
    no_bid: float
    total_ask: float  # Cost to BUY both (arb entry)
    total_bid: float  # Revenue from SELL both
    yes_spread: float  # YES bid-ask spread
    no_spread: float  # NO bid-ask spread
    midpoint_sum: float  # YES_mid + NO_mid (should be ~1.0)
    volume: float
    liquidity: float


def parse_json_field(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            return []
    return []


def fetch_markets_with_clob(limit: int = 100) -> list[MarketData]:
    """Fetch markets from Gamma, then get actual CLOB order book prices"""

    print("  Fetching markets from Gamma API...")
    markets = []
    offset = 0

    while len(markets) < limit:
        resp = requests.get(
            f"{GAMMA_HOST}/markets",
            params={"closed": "false", "archived": "false", "limit": 100, "offset": offset},
            timeout=15,
        )
        resp.raise_for_status()
        batch = resp.json()

        if not batch:
            break

        for m in batch:
            clob_tokens = parse_json_field(m.get("clobTokenIds"))
            if len(clob_tokens) == 2:
                markets.append(
                    {
                        "question": m.get("question", "")[:55],
                        "yes_token": clob_tokens[0],
                        "no_token": clob_tokens[1],
                        "volume": float(m.get("volumeNum", 0) or 0),
                        "liquidity": float(m.get("liquidityNum", 0) or 0),
                    }
                )

        offset += 100
        if len(batch) < 100:
            break

    markets = markets[:limit]
    print(f"  Found {len(markets)} binary markets")

    print("  Fetching CLOB order books...")
    client = ClobClient(CLOB_HOST)

    results = []
    batch_size = 50

    for i in range(0, len(markets), batch_size):
        batch = markets[i : i + batch_size]
        print(f"    Processing {i + 1}-{min(i + batch_size, len(markets))} of {len(markets)}...")

        token_params = []
        for m in batch:
            token_params.append(BookParams(token_id=m["yes_token"]))
            token_params.append(BookParams(token_id=m["no_token"]))

        try:
            books = client.get_order_books(token_params)

            book_map = {}
            for book in books:
                asset_id = getattr(book, "asset_id", None)
                if asset_id:
                    book_map[asset_id] = book

            for m in batch:
                yes_book = book_map.get(m["yes_token"])
                no_book = book_map.get(m["no_token"])

                if not yes_book or not no_book:
                    continue

                yes_asks = getattr(yes_book, "asks", [])
                no_asks = getattr(no_book, "asks", [])
                yes_bids = getattr(yes_book, "bids", [])
                no_bids = getattr(no_book, "bids", [])

                # Need both sides for meaningful analysis
                if not yes_asks or not no_asks or not yes_bids or not no_bids:
                    continue

                yes_ask = float(yes_asks[0].price)
                no_ask = float(no_asks[0].price)
                yes_bid = float(yes_bids[0].price)
                no_bid = float(no_bids[0].price)

                yes_mid = (yes_ask + yes_bid) / 2
                no_mid = (no_ask + no_bid) / 2

                results.append(
                    MarketData(
                        question=m["question"],
                        yes_ask=yes_ask,
                        no_ask=no_ask,
                        yes_bid=yes_bid,
                        no_bid=no_bid,
                        total_ask=yes_ask + no_ask,
                        total_bid=yes_bid + no_bid,
                        yes_spread=yes_ask - yes_bid,
                        no_spread=no_ask - no_bid,
                        midpoint_sum=yes_mid + no_mid,
                        volume=m["volume"],
                        liquidity=m["liquidity"],
                    )
                )

        except Exception as e:
            print(f"    Error: {e}")

    return results


def print_report(markets: list[MarketData], top_n: int = 20):
    """Print analysis report"""

    print(f"\n{'═' * 90}")
    print(f" POLYMARKET CLOB ANALYSIS ({len(markets)} markets with full order books)")
    print(f"{'═' * 90}")

    # Sort by midpoint sum closest to 1.0 (most efficient/balanced markets)
    balanced = sorted(markets, key=lambda x: abs(x.midpoint_sum - 1.0))

    print("\n MOST BALANCED MARKETS (midpoint sum closest to $1.00)")
    print(f"{'─' * 90}")
    print(f" {'Mid∑':>6} {'Y_bid':>6} {'Y_ask':>6} {'N_bid':>6} {'N_ask':>6} {'Liq':>7}  Question")
    print(f"{'─' * 90}")

    for m in balanced[:top_n]:
        liq_str = f"${m.liquidity / 1000:.0f}k" if m.liquidity >= 1000 else f"${m.liquidity:.0f}"
        print(
            f" {m.midpoint_sum:>6.3f} {m.yes_bid:>6.2f} {m.yes_ask:>6.2f} {m.no_bid:>6.2f} {m.no_ask:>6.2f} {liq_str:>7}  {m.question}"
        )

    # Check for actual arb (total_ask < 1.0)
    arb_opps = [m for m in markets if m.total_ask < 1.0]

    print(f"\n{'─' * 90}")
    print(" ARB OPPORTUNITIES (YES_ask + NO_ask < $1.00)")
    print(f"{'─' * 90}")

    if arb_opps:
        arb_sorted = sorted(arb_opps, key=lambda x: x.total_ask)
        for m in arb_sorted[:10]:
            profit = 1.0 - m.total_ask
            print(f" 🎯 Cost: ${m.total_ask:.4f} → Profit: {profit:.2%}  {m.question}")
    else:
        print(" None found. Market is efficient.")

    # Summary stats
    print(f"\n{'─' * 90}")
    print(" SUMMARY")
    print(f"{'─' * 90}")

    avg_midsum = sum(m.midpoint_sum for m in markets) / len(markets) if markets else 0
    avg_ask_total = sum(m.total_ask for m in markets) / len(markets) if markets else 0
    avg_yes_spread = sum(m.yes_spread for m in markets) / len(markets) if markets else 0
    avg_no_spread = sum(m.no_spread for m in markets) / len(markets) if markets else 0

    tight_markets = len([m for m in markets if abs(m.midpoint_sum - 1.0) < 0.02])

    print(f" Avg midpoint sum:      ${avg_midsum:.4f} (ideal: $1.00)")
    print(f" Avg total ask (buy):   ${avg_ask_total:.4f}")
    print(f" Avg YES bid-ask spread: {avg_yes_spread:.4f} ({avg_yes_spread * 100:.1f}%)")
    print(f" Avg NO bid-ask spread:  {avg_no_spread:.4f} ({avg_no_spread * 100:.1f}%)")
    print(" ")
    print(
        f" Markets within 2% of efficient: {tight_markets} ({tight_markets / len(markets) * 100:.1f}%)"
    )
    print(f" Markets with arb opportunity:   {len(arb_opps)}")

    print(f"\n{'─' * 90}")
    print(" INTERPRETATION")
    print(f"{'─' * 90}")
    print(" • Midpoint sum ≈ $1.00 means balanced, liquid market")
    print(" • Midpoint sum >> $1.00 means one-sided market with no real NO liquidity")
    print(" • Arb exists only when YES_ask + NO_ask < $1.00 (rare, transient)")
    print(" • To catch arb: use WebSocket for real-time price streaming")
    print(f"{'═' * 90}\n")


def main():
    parser = argparse.ArgumentParser(description="Analyze Polymarket CLOB spreads")
    parser.add_argument("-n", "--limit", type=int, default=200, help="Max markets to fetch")
    parser.add_argument("-t", "--top", type=int, default=20, help="Show top N markets")
    args = parser.parse_args()

    print("Analyzing Polymarket order books...")
    markets = fetch_markets_with_clob(args.limit)
    print_report(markets, args.top)


if __name__ == "__main__":
    main()
