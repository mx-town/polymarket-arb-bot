#!/usr/bin/env python3
"""
Polymarket Arbitrage Bot

Monitors binary markets for pricing inefficiencies where YES + NO < $1.00
and executes risk-free arbitrage by buying both sides.
"""

import os
import time
import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, BookParams
from py_clob_client.order_builder.constants import BUY
import requests

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)
logger = logging.getLogger(__name__)

# Configuration
CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"
CHAIN_ID = 137  # Polygon

# Thresholds
MIN_SPREAD = float(os.getenv("MIN_SPREAD", "0.02"))  # Minimum profit to act ($0.02)
MAX_POSITION_SIZE = float(os.getenv("MAX_POSITION_SIZE", "100"))  # Max USDC per trade
POLL_INTERVAL = float(os.getenv("POLL_INTERVAL", "1.0"))  # Seconds between checks

# Credentials (set via environment)
PRIVATE_KEY = os.getenv("POLYMARKET_PRIVATE_KEY")
FUNDER_ADDRESS = os.getenv("POLYMARKET_FUNDER_ADDRESS")
DRY_RUN = os.getenv("DRY_RUN", "true").lower() == "true"


@dataclass
class ArbOpportunity:
    """Represents an arbitrage opportunity"""
    market_id: str
    market_name: str
    yes_token_id: str
    no_token_id: str
    yes_ask: float
    no_ask: float
    total_cost: float
    profit_per_share: float
    timestamp: datetime


class PolymarketArbBot:
    def __init__(self):
        self.client: Optional[ClobClient] = None
        self.opportunities_found = 0
        self.total_profit = 0.0
        
        if not DRY_RUN:
            if not PRIVATE_KEY or not FUNDER_ADDRESS:
                raise ValueError("POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER_ADDRESS required for live trading")
            
            self.client = ClobClient(
                CLOB_HOST,
                key=PRIVATE_KEY,
                chain_id=CHAIN_ID,
                signature_type=1,  # Email/Magic wallet
                funder=FUNDER_ADDRESS
            )
            self.client.set_api_creds(self.client.create_or_derive_api_creds())
            logger.info("Initialized authenticated CLOB client")
        else:
            self.client = ClobClient(CLOB_HOST)  # Read-only
            logger.info("Running in DRY RUN mode (read-only)")

    def get_active_markets(self, limit: int = 100, offset: int = 0) -> list:
        """Fetch active binary markets from Gamma API"""
        params = {
            "closed": "false",
            "archived": "false",
            "limit": limit,
            "offset": offset,
        }
            
        try:
            resp = requests.get(f"{GAMMA_HOST}/markets", params=params, timeout=10)
            resp.raise_for_status()
            markets = resp.json()
            
            # Filter for binary markets only (exactly 2 outcomes)
            binary_markets = [m for m in markets if len(m.get("clobTokenIds", [])) == 2 or len(m.get("tokens", [])) == 2]
            logger.info(f"Fetched {len(markets)} markets, {len(binary_markets)} are binary")
            return binary_markets
            
        except Exception as e:
            logger.error(f"Failed to fetch markets: {e}")
            return []

    def check_arbitrage(self, market: dict) -> Optional[ArbOpportunity]:
        """Check if a market has an arbitrage opportunity"""
        # Get token IDs - try both field names
        token_ids = market.get("clobTokenIds", [])
        if not token_ids:
            tokens = market.get("tokens", [])
            token_ids = [t.get("token_id") for t in tokens if t.get("token_id")]
        
        if len(token_ids) != 2:
            return None
            
        try:
            yes_token_id = token_ids[0]
            no_token_id = token_ids[1]
            
            yes_book = self.client.get_order_book(yes_token_id)
            no_book = self.client.get_order_book(no_token_id)
            
            # Get best ask (lowest sell price) for each side
            yes_asks = yes_book.asks if hasattr(yes_book, 'asks') else []
            no_asks = no_book.asks if hasattr(no_book, 'asks') else []
            
            if not yes_asks or not no_asks:
                return None
                
            yes_ask = float(yes_asks[0].price)
            no_ask = float(no_asks[0].price)
            total_cost = yes_ask + no_ask
            
            # Check for arbitrage opportunity
            if total_cost < (1.0 - MIN_SPREAD):
                profit = 1.0 - total_cost
                return ArbOpportunity(
                    market_id=market.get("conditionId", market.get("condition_id", "")),
                    market_name=market.get("question", "Unknown"),
                    yes_token_id=yes_token_id,
                    no_token_id=no_token_id,
                    yes_ask=yes_ask,
                    no_ask=no_ask,
                    total_cost=total_cost,
                    profit_per_share=profit,
                    timestamp=datetime.now()
                )
                
        except Exception as e:
            logger.debug(f"Error checking market {market.get('question', 'Unknown')[:50]}: {e}")
            
        return None

    def execute_arbitrage(self, opp: ArbOpportunity) -> bool:
        """Execute arbitrage by buying both YES and NO shares"""
        if DRY_RUN:
            logger.info(f"[DRY RUN] Would execute arb on: {opp.market_name[:60]}")
            logger.info(f"  YES @ ${opp.yes_ask:.4f} + NO @ ${opp.no_ask:.4f} = ${opp.total_cost:.4f}")
            logger.info(f"  Profit per share: ${opp.profit_per_share:.4f}")
            return True
            
        try:
            # Calculate position size (limited by MAX_POSITION_SIZE)
            shares = min(MAX_POSITION_SIZE / opp.total_cost, 1000)
            
            # Create and place YES order
            yes_order = self.client.create_order(OrderArgs(
                price=opp.yes_ask,
                size=shares,
                side=BUY,
                token_id=opp.yes_token_id
            ))
            yes_resp = self.client.post_order(yes_order)
            
            # Create and place NO order
            no_order = self.client.create_order(OrderArgs(
                price=opp.no_ask,
                size=shares,
                side=BUY,
                token_id=opp.no_token_id
            ))
            no_resp = self.client.post_order(no_order)
            
            profit = shares * opp.profit_per_share
            self.total_profit += profit
            
            logger.info(f"✅ Executed arb: {opp.market_name[:50]}")
            logger.info(f"   Bought {shares:.2f} shares each side")
            logger.info(f"   Profit: ${profit:.4f}")
            
            return True
            
        except Exception as e:
            logger.error(f"Failed to execute arb: {e}")
            return False

    def scan_markets(self, markets: list) -> list[ArbOpportunity]:
        """Scan all markets for arbitrage opportunities"""
        opportunities = []
        
        for market in markets:
            opp = self.check_arbitrage(market)
            if opp:
                opportunities.append(opp)
                self.opportunities_found += 1
                
        return opportunities

    def run(self):
        """Main bot loop"""
        logger.info("=" * 60)
        logger.info("Polymarket Arbitrage Bot Starting")
        logger.info(f"  Min spread: ${MIN_SPREAD}")
        logger.info(f"  Max position: ${MAX_POSITION_SIZE}")
        logger.info(f"  Poll interval: {POLL_INTERVAL}s")
        logger.info(f"  Dry run: {DRY_RUN}")
        logger.info("=" * 60)
        
        while True:
            try:
                # Fetch all active markets (paginate if needed)
                all_markets = []
                offset = 0
                while True:
                    markets = self.get_active_markets(limit=100, offset=offset)
                    if not markets:
                        break
                    all_markets.extend(markets)
                    if len(markets) < 100:
                        break
                    offset += 100
                
                logger.info(f"Scanning {len(all_markets)} total binary markets...")
                
                # Scan for opportunities
                opportunities = self.scan_markets(all_markets)
                
                if opportunities:
                    logger.info(f"Found {len(opportunities)} arbitrage opportunities!")
                    for opp in opportunities:
                        self.execute_arbitrage(opp)
                else:
                    logger.debug("No opportunities found this cycle")
                
                # Stats
                if self.opportunities_found > 0:
                    logger.info(f"Stats: {self.opportunities_found} opps found, ${self.total_profit:.2f} profit")
                
                time.sleep(POLL_INTERVAL)
                
            except KeyboardInterrupt:
                logger.info("Shutting down...")
                break
            except Exception as e:
                logger.error(f"Error in main loop: {e}")
                time.sleep(5)


def main():
    bot = PolymarketArbBot()
    bot.run()


if __name__ == "__main__":
    main()