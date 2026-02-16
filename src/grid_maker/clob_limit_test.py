"""CLOB order limit discovery — standalone diagnostic.

Places incrementing GTC BUY orders at $0.01 to find the max open order limit.
Safety: $0.01 × 1 share = $0.01 per order. 200 orders = $2.00 max exposure.
"""

from __future__ import annotations

import logging
import time

from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

from grid_maker.market_data import discover_markets
from shared.client import init_client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("clob_limit_test")

MAX_ORDERS = 200
PRICE = 0.01
SIZE = 1
DELAY_BETWEEN = 0.2  # seconds between placements


def _run_limit_test(client, token_id: str, label: str) -> int:
    """Place incrementing orders on one token, return max placed before rejection."""
    placed_ids: list[str] = []
    limit_hit = MAX_ORDERS

    try:
        for i in range(1, MAX_ORDERS + 1):
            try:
                order = client.create_order(
                    OrderArgs(
                        token_id=token_id,
                        price=PRICE,
                        size=SIZE,
                        side=BUY,
                    )
                )
                resp = client.post_order(order, OrderType.GTC)

                order_id = None
                if isinstance(resp, dict):
                    order_id = resp.get("orderID") or resp.get("orderId")
                elif hasattr(resp, "orderID"):
                    order_id = resp.orderID

                if order_id:
                    placed_ids.append(order_id)
                    if i % 10 == 0:
                        log.info("[%s] placed %d orders so far", label, i)
                else:
                    log.warning("[%s] order %d returned no ID: %s", label, i, resp)
                    limit_hit = i - 1
                    break

            except Exception as e:
                log.info("[%s] REJECTED at order %d: %s", label, i, e)
                limit_hit = i - 1
                break

            time.sleep(DELAY_BETWEEN)
        else:
            log.info("[%s] placed all %d orders without rejection", label, MAX_ORDERS)

    finally:
        # Cleanup: cancel all placed orders
        log.info("[%s] cleaning up %d orders...", label, len(placed_ids))
        for oid in placed_ids:
            try:
                client.cancel(oid)
            except Exception as e:
                log.warning("[%s] cancel failed for %s: %s", label, oid, e)
        log.info("[%s] cleanup complete", label)

    return limit_hit


def main() -> None:
    log.info("=" * 60)
    log.info("CLOB ORDER LIMIT DISCOVERY TEST")
    log.info("=" * 60)
    log.info("Max orders to try: %d", MAX_ORDERS)
    log.info("Price: $%.2f  Size: %d  Max exposure: $%.2f", PRICE, SIZE, PRICE * MAX_ORDERS)

    client = init_client(dry_run=False)

    # Discover one active market
    markets = discover_markets(
        assets=("bitcoin",),
        timeframes=("5m",),
        max_markets=1,
    )
    if not markets:
        log.error("No active markets found. Try again when a market is live.")
        return

    market = markets[0]
    log.info("Using market: %s", market.slug)
    log.info("UP token:   %s", market.up_token_id)
    log.info("DOWN token: %s", market.down_token_id)

    # Test 1: UP token
    log.info("")
    log.info("--- Test 1: UP token ---")
    limit_up = _run_limit_test(client, market.up_token_id, "UP")
    log.info("UP token limit: %d orders", limit_up)

    time.sleep(1)

    # Test 2: DOWN token (different token_id, checks per-token vs per-account)
    log.info("")
    log.info("--- Test 2: DOWN token ---")
    limit_down = _run_limit_test(client, market.down_token_id, "DOWN")
    log.info("DOWN token limit: %d orders", limit_down)

    # Summary
    log.info("")
    log.info("=" * 60)
    log.info("RESULTS")
    log.info("=" * 60)
    log.info("UP token limit:   %d", limit_up)
    log.info("DOWN token limit: %d", limit_down)

    min_limit = min(limit_up, limit_down)
    if limit_up >= 98 and limit_down >= 98:
        log.info("VERDICT: Full static grid ($0.01-$0.99) is feasible!")
    elif min_limit >= 30:
        log.info("VERDICT: Partial grid (%d levels), need sliding window", min_limit)
    else:
        log.info("VERDICT: Very limited (%d levels), grid needs rethink", min_limit)


if __name__ == "__main__":
    main()
