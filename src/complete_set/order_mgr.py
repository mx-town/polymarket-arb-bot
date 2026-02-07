"""Order lifecycle management: placement, replacement, cancellation, fill detection.

Translates OrderManager.java. Tracks at most 1 order per token_id.
"""

from __future__ import annotations

import logging
import math
import time
from decimal import Decimal, ROUND_DOWN
from typing import Callable, Optional

from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from complete_set.models import (
    Direction,
    GabagoolMarket,
    OrderState,
)

log = logging.getLogger("cs.orders")

# ANSI colors for log highlights
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_RESET = "\033[0m"

ORDER_STALE_TIMEOUT_S = 300.0
ORDER_STATUS_POLL_INTERVAL_S = 1.0
DRY_FILL_DELAY_S = 1.0  # simulate fill delay in dry-run mode
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
        order_type: Optional[OrderType] = None,
        side: str = "BUY",
    ) -> bool:
        """Place a BUY or SELL order. Returns True on success."""
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
                side=side,
                matched_size=ZERO,  # starts unfilled — exposure accumulates
                seconds_to_end_at_entry=seconds_to_end,
            )
            self._orders[token_id] = state
            # Don't fire on_fill here; check_pending_orders will simulate
            # the fill after DRY_FILL_DELAY_S so exposure is realistic.
            return True

        try:
            ot = order_type or OrderType.GTC

            # FOK (taker) orders require price*size ≤ 2 decimals (maker amount)
            # and size ≤ 4 decimals (taker amount).
            # py_clob_client internally rounds size to 2 decimals, so we must
            # ensure cents * (size*100) % 100 == 0.
            # step = 100 / gcd(cents, 100) / 100.
            if ot == OrderType.FOK:
                cents = int(price * 100)
                g = math.gcd(cents, 100)
                step = Decimal(100 // g) / Decimal(100)
                size = (size / step).to_integral_value(rounding=ROUND_DOWN) * step
                if size <= ZERO:
                    log.warning("FOK size rounded to zero, skipping %s", token_id[:16])
                    return False

                # Polymarket requires min $1 notional for marketable FOK BUY orders
                min_notional = Decimal("1")
                notional = price * size
                if notional < min_notional:
                    min_size = math.ceil(float(min_notional / price / step)) * step
                    log.debug(
                        "FOK_MIN_NOTIONAL %s │ %s x %s = $%s < $1 │ bumping to %s",
                        token_id[:16], price, size, notional, min_size,
                    )
                    size = min_size

                label = (
                    f"{market.slug[:40]} │ {direction.value} "
                    f"@ {price} x{size} ({reason}, {seconds_to_end}s left)"
                )

            clob_side = SELL if side == "SELL" else BUY
            log.info("PLACE %s", label)
            order = client.create_order(
                OrderArgs(
                    token_id=token_id,
                    price=float(price),
                    size=float(size),
                    side=clob_side,
                )
            )
            resp = client.post_order(order, ot)

            # Extract order ID from response
            order_id = None
            if isinstance(resp, dict):
                order_id = resp.get("orderID") or resp.get("orderId")
            elif hasattr(resp, "orderID"):
                order_id = resp.orderID
            elif hasattr(resp, "order_id"):
                order_id = resp.order_id

            if not order_id:
                log.warning("%sOrder submission returned null orderId for %s%s", C_YELLOW, market.slug, C_RESET)
                # Insert sentinel to prevent duplicate submissions
                self._orders[token_id] = OrderState(
                    order_id="",
                    market=market,
                    token_id=token_id,
                    direction=direction,
                    price=price,
                    size=size,
                    placed_at=time.time(),
                    side=side,
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
                side=side,
                matched_size=ZERO,
                seconds_to_end_at_entry=seconds_to_end,
            )
            log.info("%sPLACED %s (order=%s, type=%s)%s", C_GREEN, label, order_id, ot.value if hasattr(ot, 'value') else ot, C_RESET)
            return True

        except Exception as e:
            error_str = str(e).lower()
            is_balance_error = "balance" in error_str or "allowance" in error_str
            log.error("%sFAILED %s │ %s (balance_error=%s)%s", C_RED, label, e, is_balance_error, C_RESET)
            # Sentinel prevents duplicate submissions for GTC orders that
            # might be on the book despite the error.  Skip for:
            # - Balance errors: no order exists to track
            # - FOK orders: terminal by nature, nothing on the book
            is_fok = (order_type == OrderType.FOK)
            if not is_balance_error and not is_fok:
                self._orders[token_id] = OrderState(
                    order_id="",
                    market=market,
                    token_id=token_id,
                    direction=direction,
                    price=price,
                    size=size,
                    placed_at=time.time(),
                    side=side,
                    matched_size=ZERO,
                    seconds_to_end_at_entry=seconds_to_end,
                )
            return False

    # -----------------------------------------------------------------
    # Cancel
    # -----------------------------------------------------------------

    def cancel_order(
        self,
        client,
        token_id: str,
        reason: str = "",
        on_fill: Optional[Callable[[OrderState, Decimal], None]] = None,
    ) -> None:
        """Cancel an order by token_id, reconciling any fills first."""
        state = self._orders.get(token_id)
        if state is None:
            return

        if not state.order_id:
            self._orders.pop(token_id, None)
            log.debug("REMOVE_SENTINEL %s reason=%s", token_id[:16], reason)
            return  # sentinel, nothing to cancel on CLOB

        if self._dry_run:
            self._orders.pop(token_id, None)
            log.info("DRY_CANCEL %s reason=%s", token_id[:16], reason)
            return

        # Reconcile fills before cancelling: query CLOB for actual matched_size
        matched = ZERO
        try:
            order = client.get_order(state.order_id)
            if isinstance(order, dict):
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
                    log.info(
                        "%sRECONCILE_FILL %s %s +%s shares before cancel (reason=%s)%s",
                        C_YELLOW,
                        state.order_id,
                        token_id[:16],
                        delta,
                        reason,
                        C_RESET,
                    )
                    on_fill(state, delta)
        except Exception as e:
            log.warning(
                "%sPre-cancel fill check failed %s: %s (fills may be lost)%s",
                C_YELLOW, state.order_id, e, C_RESET,
            )

        # If fully filled, skip the cancel call — order is already terminal
        if matched >= state.size:
            log.info(
                "%sSKIP_CANCEL %s fully filled (%s/%s), reason=%s%s",
                C_GREEN, state.order_id, matched, state.size, reason, C_RESET,
            )
            self._orders.pop(token_id, None)
            return

        # Now remove from tracking and cancel on CLOB
        self._orders.pop(token_id, None)
        try:
            client.cancel(state.order_id)
            log.info("CANCELLED %s reason=%s", state.order_id, reason)
        except Exception as e:
            log.warning("%sCancel failed %s: %s%s", C_RED, state.order_id, e, C_RESET)

    def cancel_market_orders(
        self,
        client,
        market: GabagoolMarket,
        reason: str = "",
        on_fill: Optional[Callable[[OrderState, Decimal], None]] = None,
    ) -> None:
        """Cancel all orders for a market."""
        self.cancel_order(client, market.up_token_id, reason, on_fill)
        self.cancel_order(client, market.down_token_id, reason, on_fill)

    def cancel_all(
        self,
        client,
        reason: str = "SHUTDOWN",
        on_fill: Optional[Callable[[OrderState, Decimal], None]] = None,
    ) -> None:
        """Cancel all tracked orders."""
        for token_id in list(self._orders.keys()):
            self.cancel_order(client, token_id, reason, on_fill)

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
                # Simulate fill after DRY_FILL_DELAY_S
                if state.matched_size < state.size:
                    if now - state.placed_at >= DRY_FILL_DELAY_S:
                        delta = state.size - state.matched_size
                        self._orders[token_id] = OrderState(
                            order_id=state.order_id,
                            market=state.market,
                            token_id=state.token_id,
                            direction=state.direction,
                            price=state.price,
                            size=state.size,
                            placed_at=state.placed_at,
                            side=state.side,
                            matched_size=state.size,
                            last_status_check_at=now,
                            seconds_to_end_at_entry=state.seconds_to_end_at_entry,
                        )
                        if on_fill:
                            on_fill(state, delta)
                        log.info(
                            "%sDRY_FILL %s %s +%s shares @ %s (after %.1fs)%s",
                            C_GREEN,
                            state.market.slug if state.market else "?",
                            state.direction.value if state.direction else "?",
                            delta, state.price,
                            now - state.placed_at,
                            C_RESET,
                        )

                # Remove stale orders
                if now - state.placed_at > ORDER_STALE_TIMEOUT_S:
                    log.info(
                        "%sRemoving stale dry-run order %s token=%s after %ds%s",
                        C_YELLOW,
                        state.order_id,
                        token_id[:16],
                        int(now - state.placed_at),
                        C_RESET,
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
                    "%sCancelling stale order %s token=%s after %ds%s",
                    C_YELLOW,
                    state.order_id,
                    token_id[:16],
                    int(now - state.placed_at),
                    C_RESET,
                )
                self.cancel_order(client, token_id, "STALE_TIMEOUT", on_fill)

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
                side=state.side,
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
            side=state.side,
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
