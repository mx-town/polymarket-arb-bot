"""Order lifecycle management: placement, replacement, cancellation, fill detection.

Translates OrderManager.java. Tracks at most 1 order per token_id.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal
from typing import Callable, Optional

from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY

from complete_set.models import (
    Direction,
    GabagoolMarket,
    OrderState,
    ReplaceDecision,
)

log = logging.getLogger("cs.orders")

ORDER_STALE_TIMEOUT_S = 300.0
ORDER_STATUS_POLL_INTERVAL_S = 1.0
ZERO = Decimal("0")


class OrderManager:
    def __init__(self, dry_run: bool = True):
        self._orders: dict[str, OrderState] = {}  # token_id -> OrderState
        self._dry_run = dry_run

    def get_open_orders(self) -> dict[str, OrderState]:
        return dict(self._orders)

    def get_order(self, token_id: str) -> Optional[OrderState]:
        return self._orders.get(token_id)

    def has_order(self, token_id: str) -> bool:
        return token_id in self._orders

    # -----------------------------------------------------------------
    # Place
    # -----------------------------------------------------------------

    def place_order(
        self,
        client,
        market: GabagoolMarket,
        token_id: str,
        direction: Direction,
        price: Decimal,
        size: Decimal,
        seconds_to_end: int,
        reason: str = "QUOTE",
        on_fill: Optional[Callable] = None,
    ) -> bool:
        """Place a BUY GTC limit order. Returns True on success."""
        label = (
            f"{market.slug[:40]} │ {direction.value} "
            f"@ {price} x{size} ({reason}, {seconds_to_end}s left)"
        )

        if self._dry_run:
            log.info("DRY %s", label)
            state = OrderState(
                order_id=f"dry-{int(time.time()*1000)}",
                market=market,
                token_id=token_id,
                direction=direction,
                price=price,
                size=size,
                placed_at=time.time(),
                matched_size=size,  # mark fully matched immediately
                seconds_to_end_at_entry=seconds_to_end,
            )
            self._orders[token_id] = state
            # Fire fill callback now so inventory updates, but keep order
            # in _orders so maybe_replace sees it and respects cooldown.
            if on_fill:
                on_fill(state, size)
            return True

        try:
            log.info("PLACE %s", label)
            order = client.create_order(
                OrderArgs(
                    token_id=token_id,
                    price=float(price),
                    size=float(size),
                    side=BUY,
                )
            )
            resp = client.post_order(order, OrderType.GTC)

            # Extract order ID from response
            order_id = None
            if isinstance(resp, dict):
                order_id = resp.get("orderID") or resp.get("orderId")
            elif hasattr(resp, "orderID"):
                order_id = resp.orderID
            elif hasattr(resp, "order_id"):
                order_id = resp.order_id

            if not order_id:
                log.warning("Order submission returned null orderId for %s", market.slug)
                # Insert sentinel so maybe_replace returns SKIP for min_replace_millis
                self._orders[token_id] = OrderState(
                    order_id="",
                    market=market,
                    token_id=token_id,
                    direction=direction,
                    price=price,
                    size=size,
                    placed_at=time.time(),
                    matched_size=ZERO,
                    seconds_to_end_at_entry=seconds_to_end,
                )
                return False

            self._orders[token_id] = OrderState(
                order_id=order_id,
                market=market,
                token_id=token_id,
                direction=direction,
                price=price,
                size=size,
                placed_at=time.time(),
                matched_size=ZERO,
                seconds_to_end_at_entry=seconds_to_end,
            )
            log.info("PLACED %s (order=%s)", label, order_id)
            return True

        except Exception as e:
            log.error("FAILED %s │ %s", label, e)
            # Insert sentinel so maybe_replace returns SKIP for min_replace_millis
            self._orders[token_id] = OrderState(
                order_id="",
                market=market,
                token_id=token_id,
                direction=direction,
                price=price,
                size=size,
                placed_at=time.time(),
                matched_size=ZERO,
                seconds_to_end_at_entry=seconds_to_end,
            )
            return False

    # -----------------------------------------------------------------
    # Replace decision
    # -----------------------------------------------------------------

    def maybe_replace(
        self,
        token_id: str,
        new_price: Decimal,
        new_size: Decimal,
        min_replace_millis: int,
        min_price_change: Decimal = ZERO,
    ) -> ReplaceDecision:
        """Decide whether to skip, place new, or replace existing order."""
        existing = self._orders.get(token_id)
        if existing is None:
            return ReplaceDecision.PLACE

        age_ms = (time.time() - existing.placed_at) * 1000
        if age_ms < min_replace_millis:
            return ReplaceDecision.SKIP

        price_delta = abs(existing.price - new_price)
        same_size = existing.size == new_size

        # Skip if price moved less than the minimum threshold
        if price_delta < min_price_change and same_size:
            return ReplaceDecision.SKIP

        return ReplaceDecision.REPLACE

    # -----------------------------------------------------------------
    # Cancel
    # -----------------------------------------------------------------

    def cancel_order(self, client, token_id: str, reason: str = "") -> None:
        """Cancel an order by token_id."""
        state = self._orders.pop(token_id, None)
        if state is None:
            return

        if self._dry_run:
            log.info("DRY_CANCEL %s reason=%s", token_id[:16], reason)
            return

        try:
            client.cancel(state.order_id)
            log.info("CANCELLED %s reason=%s", state.order_id, reason)
        except Exception as e:
            log.warning("Cancel failed %s: %s", state.order_id, e)

    def cancel_market_orders(
        self, client, market: GabagoolMarket, reason: str = ""
    ) -> None:
        """Cancel all orders for a market."""
        self.cancel_order(client, market.up_token_id, reason)
        self.cancel_order(client, market.down_token_id, reason)

    def cancel_all(self, client, reason: str = "SHUTDOWN") -> None:
        """Cancel all tracked orders."""
        for token_id in list(self._orders.keys()):
            self.cancel_order(client, token_id, reason)

    # -----------------------------------------------------------------
    # Fill detection
    # -----------------------------------------------------------------

    def check_pending_orders(
        self,
        client,
        on_fill: Optional[Callable[[OrderState, Decimal], None]] = None,
    ) -> None:
        """Poll order status, detect fills, remove terminal orders."""
        now = time.time()

        for token_id in list(self._orders.keys()):
            state = self._orders.get(token_id)
            if state is None:
                continue

            if self._dry_run:
                # Dry-run orders persist; fills happen at placement time.
                # Only remove once stale so min_replace_millis throttles.
                if now - state.placed_at > ORDER_STALE_TIMEOUT_S:
                    log.info(
                        "Removing stale dry-run order %s token=%s after %ds",
                        state.order_id,
                        token_id[:16],
                        int(now - state.placed_at),
                    )
                    self._orders.pop(token_id, None)
                continue

            # Check if due for status poll
            if (
                state.last_status_check_at is not None
                and now - state.last_status_check_at < ORDER_STATUS_POLL_INTERVAL_S
            ):
                continue

            self._refresh_order_status(client, token_id, state, now, on_fill)

            # Check for stale orders
            state = self._orders.get(token_id)
            if state is None:
                continue
            if now - state.placed_at > ORDER_STALE_TIMEOUT_S:
                log.info(
                    "Cancelling stale order %s token=%s after %ds",
                    state.order_id,
                    token_id[:16],
                    int(now - state.placed_at),
                )
                self.cancel_order(client, token_id, "STALE_TIMEOUT")

    def _refresh_order_status(
        self,
        client,
        token_id: str,
        state: OrderState,
        now: float,
        on_fill: Optional[Callable],
    ) -> None:
        """Poll order status from CLOB."""
        if not state.order_id:
            return

        try:
            order = client.get_order(state.order_id)
        except Exception:
            # Update last check time, keep order
            self._orders[token_id] = OrderState(
                order_id=state.order_id,
                market=state.market,
                token_id=state.token_id,
                direction=state.direction,
                price=state.price,
                size=state.size,
                placed_at=state.placed_at,
                matched_size=state.matched_size,
                last_status_check_at=now,
                seconds_to_end_at_entry=state.seconds_to_end_at_entry,
            )
            return

        if not isinstance(order, dict):
            return

        status = order.get("status", "")
        matched_str = (
            order.get("matched_size")
            or order.get("matchedSize")
            or order.get("size_matched")
            or order.get("filledSize")
        )
        matched = Decimal(str(matched_str)) if matched_str else ZERO

        prev_matched = state.matched_size or ZERO
        if matched > prev_matched and on_fill:
            delta = matched - prev_matched
            on_fill(state, delta)

        # Check terminal
        if self._is_terminal(status, matched, state.size):
            self._orders.pop(token_id, None)
            return

        # Update state
        self._orders[token_id] = OrderState(
            order_id=state.order_id,
            market=state.market,
            token_id=state.token_id,
            direction=state.direction,
            price=state.price,
            size=state.size,
            placed_at=state.placed_at,
            matched_size=matched if matched > prev_matched else prev_matched,
            last_status_check_at=now,
            seconds_to_end_at_entry=state.seconds_to_end_at_entry,
        )

    @staticmethod
    def _is_terminal(status: str, matched: Decimal, requested: Decimal) -> bool:
        if matched >= requested:
            return True
        if not status:
            return False
        s = status.upper()
        return any(
            term in s
            for term in ("FILLED", "CANCELED", "CANCELLED", "EXPIRED", "REJECTED", "DONE")
        )
