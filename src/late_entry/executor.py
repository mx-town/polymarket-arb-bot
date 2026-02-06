"""Order execution via Polymarket CLOB API."""

import logging
import os

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs
from py_clob_client.order_builder.constants import BUY, SELL

log = logging.getLogger("executor")

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137  # Polygon


def init_client(dry_run: bool) -> ClobClient:
    """Initialize ClobClient. Authenticated for live, read-only for dry run."""
    if dry_run:
        log.info("INIT read-only client (DRY_RUN)")
        return ClobClient(CLOB_HOST)

    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
    funder = os.environ.get("POLYMARKET_FUNDER_ADDRESS")

    if not private_key or not funder:
        raise ValueError("POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER_ADDRESS required")

    client = ClobClient(
        CLOB_HOST,
        key=private_key,
        chain_id=CHAIN_ID,
        signature_type=1,
        funder=funder,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    log.info("INIT authenticated client ready")
    return client


def place_order(
    client: ClobClient,
    token_id: str,
    side: str,
    price: float,
    size: float,
    dry_run: bool,
) -> dict:
    """
    Place an order on the CLOB.

    Args:
        side: "buy" or "sell"

    Returns:
        {success, order_id, filled_size, filled_price, error}
    """
    if dry_run:
        log.info(
            f"DRY_ORDER token={token_id[:16]}... side={side} price={price:.4f} size={size:.2f}"
        )
        return {
            "success": True,
            "order_id": "dry-run",
            "filled_size": size,
            "filled_price": price,
            "error": None,
        }

    try:
        order_side = BUY if side == "buy" else SELL
        order = client.create_order(
            OrderArgs(
                token_id=token_id,
                price=price,
                size=size,
                side=order_side,
            )
        )
        response = client.post_order(order)

        log.info(
            f"ORDER_PLACED token={token_id[:16]}... side={side} price={price:.4f} size={size:.2f}"
        )
        return {
            "success": True,
            "order_id": getattr(response, "order_id", None),
            "filled_size": size,
            "filled_price": price,
            "error": None,
        }
    except Exception as e:
        log.error(f"ORDER_ERROR token={token_id[:16]}... error={e}")
        return {
            "success": False, "order_id": None,
            "filled_size": 0, "filled_price": 0, "error": str(e),
        }
