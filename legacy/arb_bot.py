#!/usr/bin/env python3
"""
Polymarket Arbitrage Bot

Strategy:
1. Fetch binary markets from Gamma API
2. Batch-fetch CLOB order books (actual bid/ask prices)
3. Find opportunities where YES_ask + NO_ask < $1.00
4. Execute arb if profitable after fees (~2%)

NOTE: Gamma's outcomePrices always sum to 1.0 (normalized midpoints).
Real arb opportunities are in CLOB order book spreads.
"""

import argparse
import json
import logging
import os
import time
from dataclasses import dataclass
from datetime import datetime

import requests
from py_clob_client.client import ClobClient
from py_clob_client.clob_types import BookParams, OrderArgs
from py_clob_client.order_builder.constants import BUY

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# API endpoints
CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"
CHAIN_ID = 137  # Polygon

# Polymarket fee (approximately 0.5-1% per side, ~2% round-trip worst case)
POLY_FEE_RATE = 0.02


@dataclass
class ArbOpportunity:
    """Represents an arbitrage opportunity"""

    market_id: str
    market_name: str
    yes_token_id: str
    no_token_id: str
    yes_price: float
    no_price: float
    total_cost: float
    gross_profit: float
    net_profit: float  # After fees
    timestamp: datetime


@dataclass
class BotConfig:
    """Bot configuration"""

    dry_run: bool = True
    min_spread: float = 0.02  # Minimum gross profit to consider
    min_net_profit: float = 0.005  # Minimum net profit after fees
    max_position_size: float = 100.0
    poll_interval: float = 5.0
    max_markets: int = 0
    batch_size: int = 50  # Order books to fetch per batch
    verbose: bool = False

    @classmethod
    def from_args(cls, args: argparse.Namespace) -> "BotConfig":
        return cls(
            dry_run=args.dry_run,
            min_spread=args.min_spread,
            min_net_profit=args.min_net_profit,
            max_position_size=args.max_position,
            poll_interval=args.interval,
            max_markets=args.max_markets,
            batch_size=args.batch_size,
            verbose=args.verbose,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Polymarket Arbitrage Bot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--live",
        dest="dry_run",
        action="store_false",
        help="Enable live trading (default: dry run)",
    )
    parser.add_argument(
        "--min-spread",
        type=float,
        default=float(os.getenv("MIN_SPREAD", "0.02")),
        help="Minimum gross profit per share",
    )
    parser.add_argument(
        "--min-net-profit", type=float, default=0.005, help="Minimum net profit after fees"
    )
    parser.add_argument(
        "--max-position",
        type=float,
        default=float(os.getenv("MAX_POSITION_SIZE", "100")),
        help="Maximum USDC per trade",
    )
    parser.add_argument(
        "--interval",
        type=float,
        default=float(os.getenv("POLL_INTERVAL", "5.0")),
        help="Seconds between market scans",
    )
    parser.add_argument("--max-markets", type=int, default=0, help="Max markets to scan (0 = all)")
    parser.add_argument(
        "--batch-size", type=int, default=50, help="Order books to fetch per API call"
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed progress")

    return parser.parse_args()


def parse_json_field(value):
    """Parse a JSON string field or return as-is if already parsed"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


class PolymarketArbBot:
    def __init__(self, config: BotConfig):
        self.config = config
        self.client: ClobClient | None = None

        # Stats
        self.cycles = 0
        self.markets_fetched = 0
        self.markets_scanned = 0
        self.opportunities_found = 0
        self.total_profit = 0.0

        private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
        funder_address = os.getenv("POLYMARKET_FUNDER_ADDRESS")

        if not config.dry_run:
            if not private_key or not funder_address:
                raise ValueError("POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER_ADDRESS required")

            self.client = ClobClient(
                CLOB_HOST,
                key=private_key,
                chain_id=CHAIN_ID,
                signature_type=1,
                funder=funder_address,
            )
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            logger.info("✓ Authenticated CLOB client initialized")
        else:
            self.client = ClobClient(CLOB_HOST)
            logger.info("✓ Read-only CLOB client (DRY RUN)")

    def fetch_all_markets(self) -> list:
        """Fetch all active binary markets from Gamma API"""
        all_markets = []
        offset = 0

        while True:
            try:
                resp = requests.get(
                    f"{GAMMA_HOST}/markets",
                    params={"closed": "false", "archived": "false", "limit": 100, "offset": offset},
                    timeout=15,
                )
                resp.raise_for_status()
                markets = resp.json()

                if not markets:
                    break

                # Parse and filter for binary markets
                for m in markets:
                    clob_tokens = parse_json_field(m.get("clobTokenIds"))

                    if len(clob_tokens) == 2:
                        all_markets.append(
                            {
                                "question": m.get("question", "Unknown"),
                                "condition_id": m.get("conditionId", ""),
                                "yes_token": clob_tokens[0],
                                "no_token": clob_tokens[1],
                            }
                        )

                if len(markets) < 100:
                    break
                offset += 100

                # Check max_markets limit
                if self.config.max_markets and len(all_markets) >= self.config.max_markets:
                    all_markets = all_markets[: self.config.max_markets]
                    break

            except Exception as e:
                logger.error(f"Failed to fetch markets at offset {offset}: {e}")
                break

        self.markets_fetched = len(all_markets)
        return all_markets

    def scan_markets_batch(self, markets: list) -> list[ArbOpportunity]:
        """
        Scan markets for arb opportunities using batch CLOB API calls.
        NOTE: Gamma outcomePrices always sum to 1.0 - useless for arb detection.
        We must check actual CLOB order book ask prices.
        """
        opportunities = []
        batch_size = self.config.batch_size
        total = len(markets)

        for i in range(0, total, batch_size):
            batch = markets[i : i + batch_size]
            batch_end = min(i + batch_size, total)

            if self.config.verbose:
                logger.info(f"  Scanning {i + 1}-{batch_end} of {total}...")

            # Build params for batch request (both YES and NO tokens)
            token_params = []
            for m in batch:
                token_params.append(BookParams(token_id=m["yes_token"]))
                token_params.append(BookParams(token_id=m["no_token"]))

            try:
                books = self.client.get_order_books(token_params)

                # Map token_id -> book
                book_map = {}
                for book in books:
                    asset_id = getattr(book, "asset_id", None)
                    if asset_id:
                        book_map[asset_id] = book

                # Check each market in batch
                for m in batch:
                    self.markets_scanned += 1

                    yes_book = book_map.get(m["yes_token"])
                    no_book = book_map.get(m["no_token"])

                    if not yes_book or not no_book:
                        continue

                    yes_asks = getattr(yes_book, "asks", [])
                    no_asks = getattr(no_book, "asks", [])

                    if not yes_asks or not no_asks:
                        continue

                    yes_ask = float(yes_asks[0].price)
                    no_ask = float(no_asks[0].price)
                    total_cost = yes_ask + no_ask

                    # Calculate profits
                    gross_profit = 1.0 - total_cost
                    estimated_fees = total_cost * POLY_FEE_RATE
                    net_profit = gross_profit - estimated_fees

                    # Check thresholds
                    if (
                        gross_profit >= self.config.min_spread
                        and net_profit >= self.config.min_net_profit
                    ):
                        opp = ArbOpportunity(
                            market_id=m["condition_id"],
                            market_name=m["question"],
                            yes_token_id=m["yes_token"],
                            no_token_id=m["no_token"],
                            yes_price=yes_ask,
                            no_price=no_ask,
                            total_cost=total_cost,
                            gross_profit=gross_profit,
                            net_profit=net_profit,
                            timestamp=datetime.now(),
                        )
                        opportunities.append(opp)
                        self.opportunities_found += 1

                        if self.config.verbose:
                            logger.info(f"    💰 Found: {m['question'][:50]} ({gross_profit:.2%})")

            except Exception as e:
                logger.error(f"Error scanning batch {i + 1}-{batch_end}: {e}")

        return opportunities

    def execute_arbitrage(self, opp: ArbOpportunity) -> bool:
        """Execute arbitrage trade"""
        if self.config.dry_run:
            logger.info(f"🎯 [DRY RUN] {opp.market_name[:55]}")
            logger.info(
                f"   YES @ ${opp.yes_price:.4f} + NO @ ${opp.no_price:.4f} = ${opp.total_cost:.4f}"
            )
            logger.info(f"   Gross: ${opp.gross_profit:.4f} ({opp.gross_profit * 100:.2f}%)")
            logger.info(
                f"   Net:   ${opp.net_profit:.4f} ({opp.net_profit * 100:.2f}%) after ~{POLY_FEE_RATE * 100:.1f}% fees"
            )
            return True

        try:
            shares = min(self.config.max_position_size / opp.total_cost, 1000)

            # Place both orders
            yes_order = self.client.create_order(
                OrderArgs(price=opp.yes_price, size=shares, side=BUY, token_id=opp.yes_token_id)
            )
            self.client.post_order(yes_order)

            no_order = self.client.create_order(
                OrderArgs(price=opp.no_price, size=shares, side=BUY, token_id=opp.no_token_id)
            )
            self.client.post_order(no_order)

            profit = shares * opp.net_profit
            self.total_profit += profit

            logger.info(f"✅ Executed: {opp.market_name[:50]}")
            logger.info(f"   {shares:.2f} shares, est. profit: ${profit:.4f}")
            return True

        except Exception as e:
            logger.error(f"Execution failed: {e}")
            return False

    def run_cycle(self):
        """Run one scan cycle"""
        self.cycles += 1
        cycle_start = time.time()

        logger.info(f"\n{'=' * 60}")
        logger.info(f"Cycle {self.cycles}")
        logger.info(f"{'=' * 60}")

        # Step 1: Fetch all markets from Gamma
        logger.info("→ Fetching markets from Gamma API...")
        markets = self.fetch_all_markets()
        logger.info(f"  Found {len(markets)} binary markets")

        # Step 2: Scan CLOB order books in batches
        logger.info(f"→ Scanning CLOB order books (batch size: {self.config.batch_size})...")
        opportunities = self.scan_markets_batch(markets)

        # Step 3: Execute any opportunities found
        if opportunities:
            logger.info(f"\n🎉 Found {len(opportunities)} profitable opportunities!")
            for opp in opportunities:
                self.execute_arbitrage(opp)
        else:
            logger.info(
                f"  No opportunities (need >{self.config.min_spread * 100:.1f}% gross, >{self.config.min_net_profit * 100:.2f}% net)"
            )

        # Stats
        cycle_time = time.time() - cycle_start
        logger.info(f"\n⏱  Cycle completed in {cycle_time:.1f}s")
        logger.info(f"📊 Total: {self.markets_scanned} scanned, {self.opportunities_found} opps")

        if self.total_profit > 0:
            logger.info(f"💰 Est. profit: ${self.total_profit:.4f}")

    def run(self):
        """Main bot loop"""
        cfg = self.config

        logger.info("=" * 60)
        logger.info("Polymarket Arbitrage Bot")
        logger.info("=" * 60)
        logger.info(f"  Mode:            {'DRY RUN' if cfg.dry_run else '🔴 LIVE'}")
        logger.info(f"  Min gross:       ${cfg.min_spread} ({cfg.min_spread * 100:.1f}%)")
        logger.info(f"  Min net profit:  ${cfg.min_net_profit} ({cfg.min_net_profit * 100:.2f}%)")
        logger.info(f"  Max position:    ${cfg.max_position_size}")
        logger.info(f"  Poll interval:   {cfg.poll_interval}s")
        logger.info(f"  Batch size:      {cfg.batch_size} order books/call")
        logger.info(f"  Est. fee rate:   {POLY_FEE_RATE * 100:.1f}%")
        logger.info("=" * 60)

        while True:
            try:
                self.run_cycle()
                logger.info(f"\n⏳ Next scan in {cfg.poll_interval}s...")
                time.sleep(cfg.poll_interval)

            except KeyboardInterrupt:
                logger.info("\n👋 Shutting down...")
                break
            except Exception as e:
                logger.error(f"Error: {e}")
                time.sleep(5)


def main():
    args = parse_args()
    config = BotConfig.from_args(args)
    bot = PolymarketArbBot(config)
    bot.run()


if __name__ == "__main__":
    main()
