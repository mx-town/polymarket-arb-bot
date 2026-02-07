"""Order execution via Polymarket CLOB API — GTC maker orders."""

import logging
import os

from py_clob_client.client import ClobClient
from py_clob_client.clob_types import OrderArgs, OrderType
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
    slug: str,
    token_id: str,
    side: str,
    price: float,
    size: float,
    dry_run: bool,
) -> dict:
    """
    Place a GTC limit (maker) order on the CLOB.

    Returns:
        {success, order_id, status, filled_size, error}
        - dry_run:  status='filled'  (simulated instant fill)
        - live:     status='pending'  (must poll with check_order)
    """
    cost = price * size
    label = f"{slug[:40]} │ {side.upper()} {size}x @ {price:.4f} = ${cost:.2f}"

    if dry_run:
        log.info(f"  DRY {label}")
        return {
            "success": True,
            "order_id": "dry-run",
            "status": "filled",
            "filled_size": size,
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
        response = client.post_order(order, OrderType.GTC)

        # Extract order_id from response
        order_id = None
        if isinstance(response, dict):
            order_id = response.get("orderID") or response.get("orderId")
        elif hasattr(response, "orderID"):
            order_id = response.orderID
        elif hasattr(response, "order_id"):
            order_id = response.order_id

        if not order_id:
            log.warning(f"  NO_ORDER_ID {label}")
            return {
                "success": False,
                "order_id": None,
                "status": "rejected",
                "filled_size": 0,
                "error": "no order_id in response",
            }

        log.info(f"  PLACED {label} (order={order_id})")
        return {
            "success": True,
            "order_id": order_id,
            "status": "pending",
            "filled_size": 0,
            "error": None,
        }
    except Exception as e:
        log.error(f"  FAILED {label} │ {e}")
        return {
            "success": False,
            "order_id": None,
            "status": "rejected",
            "filled_size": 0,
            "error": str(e),
        }


def check_order(client: ClobClient, order_id: str, dry_run: bool) -> dict:
    """
    Poll fill status of a resting order.

    Returns:
        {status, matched_size}
        status: 'filled' | 'partial' | 'pending' | 'cancelled' | 'unknown'
    """
    if dry_run:
        return {"status": "filled", "matched_size": 0}

    try:
        order = client.get_order(order_id)
        if not isinstance(order, dict):
            return {"status": "unknown", "matched_size": 0}

        status_raw = (order.get("status") or "").upper()
        matched_str = (
            order.get("size_matched")
            or order.get("matched_size")
            or order.get("matchedSize")
            or order.get("filledSize")
            or "0"
        )
        matched = float(matched_str)

        size_str = order.get("original_size") or order.get("size") or "0"
        original_size = float(size_str)

        # Fully filled
        if matched >= original_size > 0:
            return {"status": "filled", "matched_size": matched}
        if any(t in status_raw for t in ("FILLED", "MATCHED")):
            return {"status": "filled", "matched_size": matched}

        # Terminal non-fill states
        if any(t in status_raw for t in ("CANCELED", "CANCELLED", "EXPIRED", "REJECTED")):
            return {"status": "cancelled", "matched_size": matched}

        # Partial fill (some matched, order still open)
        if matched > 0:
            return {"status": "partial", "matched_size": matched}

        # Still resting on book
        return {"status": "pending", "matched_size": 0}

    except Exception as e:
        log.warning(f"  CHECK_FAIL order={order_id} │ {e}")
        return {"status": "unknown", "matched_size": 0}


def cancel_order(client: ClobClient, order_id: str, dry_run: bool) -> bool:
    """Cancel a resting order. Returns True on success."""
    if dry_run:
        log.info(f"  DRY_CANCEL order={order_id}")
        return True

    try:
        client.cancel(order_id)
        log.info(f"  CANCELLED order={order_id}")
        return True
    except Exception as e:
        log.warning(f"  CANCEL_FAIL order={order_id} │ {e}")
        return False
