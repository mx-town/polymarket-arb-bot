"""Order lifecycle management: placement, replacement, cancellation, fill detection.

Tracks multiple orders per token_id.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import replace
from decimal import ROUND_DOWN, Decimal
from typing import Callable, Optional

from py_clob_client.clob_types import OrderArgs, OrderType
from py_clob_client.order_builder.constants import BUY, SELL

from shared.market_data import get_simulated_fill_size
from shared.models import (
    C_GREEN,
    C_RED,
    C_RESET,
    C_YELLOW,
    ZERO,
    Direction,
    GabagoolMarket,
    OrderState,
)

log = logging.getLogger("shared.orders")

ORDER_STALE_TIMEOUT_S = 7200.0
ORDER_STATUS_POLL_INTERVAL_S = 1.0


class OrderManager:
    def __init__(self, dry_run: bool = True):
        self._orders: dict[str, list[OrderState]] = {}  # token_id -> list[OrderState]
        self._dry_run = dry_run

    def get_open_orders(self) -> dict[str, OrderState]:
        """Backward-compatible: returns first order per token."""
        return {tid: orders[0] for tid, orders in self._orders.items() if orders}

    def get_all_open_orders(self) -> dict[str, list[OrderState]]:
        """Returns all orders per token."""
        return dict(self._orders)

    def get_order(self, token_id: str) -> Optional[OrderState]:
        """Backward-compatible: returns first order for token."""
        orders = self._orders.get(token_id, [])
        return orders[0] if orders else None

    def get_all_orders_for_token(self, token_id: str) -> list[OrderState]:
        """Returns all orders for a token."""
        return list(self._orders.get(token_id, []))

    def has_order(self, token_id: str) -> bool:
        """Returns True if any orders exist for token."""
        return bool(self._orders.get(token_id))

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
        reserved_hedge_notional: Decimal = ZERO,
        entry_dynamic_edge: Decimal = ZERO,
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
                reserved_hedge_notional=reserved_hedge_notional,
                entry_dynamic_edge=entry_dynamic_edge,
            )
            if token_id not in self._orders:
                self._orders[token_id] = []
            self._orders[token_id].append(state)
            # Don't fire on_fill here; check_pending_orders will simulate
            # the fill using book-depth-aware logic.
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
                    if side == "SELL":
                        # Can't sell more than we hold — skip if position too small
                        log.warning(
                            "FOK_MIN_NOTIONAL %s │ SELL %s x %s = $%s < $1 │ need %s shares, skipping",
                            token_id[:16], price, size, notional, min_size,
                        )
                        return False
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
                # Insert sentinel to prevent duplicate submissions.
                # Skip for FOK orders — they are terminal by nature,
                # nothing on the book to track.
                is_fok = (order_type == OrderType.FOK)
                if not is_fok:
                    sentinel = OrderState(
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
                        reserved_hedge_notional=reserved_hedge_notional,
                        entry_dynamic_edge=entry_dynamic_edge,
                    )
                    if token_id not in self._orders:
                        self._orders[token_id] = []
                    self._orders[token_id].append(sentinel)
                return False

            state = OrderState(
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
                reserved_hedge_notional=reserved_hedge_notional,
                entry_dynamic_edge=entry_dynamic_edge,
            )
            if token_id not in self._orders:
                self._orders[token_id] = []
            self._orders[token_id].append(state)
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
                sentinel = OrderState(
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
                    reserved_hedge_notional=reserved_hedge_notional,
                    entry_dynamic_edge=entry_dynamic_edge,
                )
                if token_id not in self._orders:
                    self._orders[token_id] = []
                self._orders[token_id].append(sentinel)
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
        """Cancel first order by token_id, reconciling any fills first."""
        orders = self._orders.get(token_id, [])
        if not orders:
            return

        state = orders[0]

        if not state.order_id:
            orders.pop(0)
            if not orders:
                self._orders.pop(token_id, None)
            log.debug("REMOVE_SENTINEL %s reason=%s", token_id[:16], reason)
            return  # sentinel, nothing to cancel on CLOB

        if self._dry_run:
            orders.pop(0)
            if not orders:
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
            orders.pop(0)
            if not orders:
                self._orders.pop(token_id, None)
            return

        # Now remove from tracking and cancel on CLOB
        orders.pop(0)
        if not orders:
            self._orders.pop(token_id, None)
        try:
            client.cancel(state.order_id)
            log.info("CANCELLED %s reason=%s", state.order_id, reason)
        except Exception as e:
            log.warning("%sCancel failed %s: %s%s", C_RED, state.order_id, e, C_RESET)

    def cancel_all_for_token(
        self,
        client,
        token_id: str,
        reason: str = "",
        on_fill: Optional[Callable[[OrderState, Decimal], None]] = None,
    ) -> None:
        """Cancel all orders for a token."""
        orders = self._orders.get(token_id, [])
        for state in list(orders):
            if not state.order_id:
                log.debug("REMOVE_SENTINEL %s reason=%s", token_id[:16], reason)
                continue

            if self._dry_run:
                log.info("DRY_CANCEL %s reason=%s", token_id[:16], reason)
                continue

            # Reconcile fills before cancelling
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

            # If fully filled, skip the cancel call
            if matched >= state.size:
                log.info(
                    "%sSKIP_CANCEL %s fully filled (%s/%s), reason=%s%s",
                    C_GREEN, state.order_id, matched, state.size, reason, C_RESET,
                )
                continue

            # Cancel on CLOB
            try:
                client.cancel(state.order_id)
                log.info("CANCELLED %s reason=%s", state.order_id, reason)
            except Exception as e:
                log.warning("%sCancel failed %s: %s%s", C_RED, state.order_id, e, C_RESET)

        # Remove all orders for this token
        self._orders.pop(token_id, None)

    def cancel_market_orders(
        self,
        client,
        market: GabagoolMarket,
        reason: str = "",
        on_fill: Optional[Callable[[OrderState, Decimal], None]] = None,
    ) -> None:
        """Cancel all orders for a market (both sides, all orders per side)."""
        self.cancel_all_for_token(client, market.up_token_id, reason, on_fill)
        self.cancel_all_for_token(client, market.down_token_id, reason, on_fill)

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
            orders = self._orders.get(token_id, [])
            if not orders:
                continue

            # Iterate in reverse to safely remove orders while iterating
            for idx in range(len(orders) - 1, -1, -1):
                state = orders[idx]

                if self._dry_run:
                    # Depth-validated fill simulation:
                    # Uses full order book depth to determine whether our price
                    # would be crossed. No delay gate needed — zero crossing
                    # volume is the natural guard against instant fills (order
                    # placed at bid+1c, ask above that → crossing=0 → no fill
                    # until ask drops).
                    if state.matched_size < state.size:
                        remaining = state.size - state.matched_size
                        delta, new_consumed = get_simulated_fill_size(
                            state.token_id, state.price, state.side, remaining,
                            consumed=state.consumed_crossing,
                        )
                        if delta > ZERO:
                            new_matched = state.matched_size + delta
                            orders[idx] = replace(
                                state,
                                matched_size=new_matched,
                                consumed_crossing=new_consumed,
                                last_status_check_at=now,
                            )
                            if on_fill:
                                on_fill(state, delta)
                            log.info(
                                "%sDRY_FILL %s %s %s +%s shares @ %s (after %.1fs)%s",
                                C_GREEN,
                                state.market.slug if state.market else "?",
                                state.side,
                                state.direction.value if state.direction else "?",
                                delta, state.price,
                                now - state.placed_at,
                                C_RESET,
                            )
                        elif new_consumed != state.consumed_crossing:
                            # Book turnover detected — update consumed even
                            # when no fill so the reset sticks.
                            orders[idx] = replace(
                                state,
                                consumed_crossing=new_consumed,
                                last_status_check_at=now,
                            )

                    # Skip stale timeout purge for dry-run orders — let the
                    # engine's _cleanup_market handle removal when the market
                    # ends.  The 300s timeout kills grid orders too early in
                    # 5m markets (grid lives ~360s, last 60s has no orders).
                    continue

                # Check if due for status poll
                if (
                    state.last_status_check_at is not None
                    and now - state.last_status_check_at < ORDER_STATUS_POLL_INTERVAL_S
                ):
                    continue

                self._refresh_order_status(client, token_id, idx, state, now, on_fill)

                # Check for stale orders (after refresh, check if still exists)
                if idx < len(orders):
                    current_state = orders[idx]
                    if now - current_state.placed_at > ORDER_STALE_TIMEOUT_S:
                        log.info(
                            "%sCancelling stale order %s token=%s after %ds%s",
                            C_YELLOW,
                            current_state.order_id,
                            token_id[:16],
                            int(now - current_state.placed_at),
                            C_RESET,
                        )
                        # Cancel this specific order by removing it from the list
                        stale_state = orders.pop(idx)
                        if stale_state.order_id and not self._dry_run:
                            try:
                                client.cancel(stale_state.order_id)
                                log.info("CANCELLED %s reason=STALE_TIMEOUT", stale_state.order_id)
                            except Exception as e:
                                log.warning(
                                    "%sCancel failed %s: %s%s",
                                    C_RED, stale_state.order_id, e, C_RESET,
                                )

            # Clean up empty lists
            if not orders:
                self._orders.pop(token_id, None)

    def check_pending_orders_bulk(
        self,
        client,
        on_fill: Optional[Callable[[OrderState, Decimal], None]] = None,
    ) -> None:
        """Bulk fill detection — fetches all open orders in one API call.

        More efficient than check_pending_orders for large order counts
        (e.g., static grid with 196 orders/market × 5 markets).
        Falls back to individual polling if bulk fetch fails.
        """
        now = time.time()

        # Dry-run mode: delegate to per-order simulation (needs book depth)
        if self._dry_run:
            self.check_pending_orders(client, on_fill=on_fill)
            return

        # Fetch all open orders in one call
        try:
            open_orders = client.get_orders()
        except Exception as e:
            log.warning("BULK_FETCH_FAILED: %s — falling back to individual polling", e)
            self.check_pending_orders(client, on_fill=on_fill)
            return

        if not isinstance(open_orders, list):
            self._sweep_stale_orders(now, on_fill)
            return

        # Build lookup: order_id -> CLOB order dict
        clob_lookup: dict[str, dict] = {}
        for order in open_orders:
            if not isinstance(order, dict):
                continue
            oid = (
                order.get("id")
                or order.get("orderID")
                or order.get("orderId", "")
            )
            if oid:
                clob_lookup[oid] = order

        # Iterate local orders, match against bulk lookup
        for token_id in list(self._orders.keys()):
            orders = self._orders.get(token_id, [])
            if not orders:
                continue

            for idx in range(len(orders) - 1, -1, -1):
                state = orders[idx]

                if not state.order_id:
                    # Sentinel — skip (reconcile_orders handles these)
                    continue

                clob_order = clob_lookup.get(state.order_id)
                if clob_order is not None:
                    # Order still on book — check for partial fill
                    matched_str = (
                        clob_order.get("matched_size")
                        or clob_order.get("matchedSize")
                        or clob_order.get("size_matched")
                        or clob_order.get("filledSize")
                    )
                    matched = Decimal(str(matched_str)) if matched_str else ZERO
                    prev_matched = state.matched_size or ZERO

                    if matched > prev_matched and on_fill:
                        delta = matched - prev_matched
                        on_fill(state, delta)

                    # Update state
                    orders[idx] = replace(
                        state,
                        matched_size=matched if matched > prev_matched else prev_matched,
                        last_status_check_at=now,
                    )
                else:
                    # Order not in CLOB response — either fully filled or cancelled
                    # Do one individual check to reconcile final fill
                    self._refresh_order_status(client, token_id, idx, state, now, on_fill)

                # Check stale timeout
                if idx < len(orders):
                    current_state = orders[idx]
                    if now - current_state.placed_at > ORDER_STALE_TIMEOUT_S:
                        log.info(
                            "%sCancelling stale order %s token=%s after %ds%s",
                            C_YELLOW,
                            current_state.order_id,
                            token_id[:16],
                            int(now - current_state.placed_at),
                            C_RESET,
                        )
                        stale_state = orders.pop(idx)
                        if stale_state.order_id:
                            try:
                                client.cancel(stale_state.order_id)
                                log.info("CANCELLED %s reason=STALE_TIMEOUT", stale_state.order_id)
                            except Exception as e:
                                log.warning(
                                    "%sCancel failed %s: %s%s",
                                    C_RED, stale_state.order_id, e, C_RESET,
                                )

            if not orders:
                self._orders.pop(token_id, None)

    def _sweep_stale_orders(
        self,
        now: float,
        on_fill: Optional[Callable] = None,
    ) -> None:
        """Remove orders that have exceeded the stale timeout."""
        for token_id in list(self._orders.keys()):
            orders = self._orders.get(token_id, [])
            for idx in range(len(orders) - 1, -1, -1):
                state = orders[idx]
                if now - state.placed_at > ORDER_STALE_TIMEOUT_S:
                    orders.pop(idx)
            if not orders:
                self._orders.pop(token_id, None)

    def _refresh_order_status(
        self,
        client,
        token_id: str,
        idx: int,
        state: OrderState,
        now: float,
        on_fill: Optional[Callable],
    ) -> None:
        """Poll order status from CLOB."""
        if not state.order_id:
            return

        orders = self._orders.get(token_id, [])
        if idx >= len(orders):
            return

        try:
            order = client.get_order(state.order_id)
        except Exception:
            # Update last check time, keep order
            orders[idx] = replace(state, last_status_check_at=now)
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
            orders.pop(idx)
            if not orders:
                self._orders.pop(token_id, None)
            return

        # Update state
        orders[idx] = replace(
            state,
            matched_size=matched if matched > prev_matched else prev_matched,
            last_status_check_at=now,
        )

    # -----------------------------------------------------------------
    # Reconciliation
    # -----------------------------------------------------------------

    def reconcile_orders(self, client) -> None:
        """Reconcile local sentinel orders with actual CLOB state.

        - Sentinels (order_id="") that match a real CLOB order get upgraded.
        - CLOB orders not tracked locally are logged as orphans.
        Skipped in dry-run mode.
        """
        if self._dry_run:
            return

        try:
            open_orders = client.get_orders()
        except Exception as e:
            log.warning("RECONCILE_FETCH_FAILED: %s", e)
            return

        if not open_orders or not isinstance(open_orders, list):
            return

        # Build token_id -> list[CLOB order] lookup
        clob_by_token: dict[str, list[dict]] = {}
        for order in open_orders:
            if not isinstance(order, dict):
                continue
            tid = order.get("asset_id") or order.get("token_id", "")
            if tid:
                if tid not in clob_by_token:
                    clob_by_token[tid] = []
                clob_by_token[tid].append(order)

        # Upgrade sentinels that have a matching CLOB order
        for token_id, orders in list(self._orders.items()):
            clob_orders = clob_by_token.get(token_id, [])

            for idx, state in enumerate(orders):
                if state.order_id:
                    continue  # not a sentinel

                if not clob_orders:
                    break

                # Match first available CLOB order to this sentinel
                clob_order = clob_orders.pop(0)
                real_id = (
                    clob_order.get("id")
                    or clob_order.get("orderID")
                    or clob_order.get("orderId", "")
                )
                if not real_id:
                    continue

                log.info(
                    "%sRECONCILE_UPGRADE %s │ sentinel → order=%s%s",
                    C_GREEN, token_id[:16], real_id, C_RESET,
                )
                orders[idx] = replace(
                    state,
                    order_id=real_id,
                    last_status_check_at=None,
                )

        # Log orphans — CLOB orders we don't track
        tracked_order_ids = {
            state.order_id
            for orders in self._orders.values()
            for state in orders
            if state.order_id
        }
        for tid, orders_list in clob_by_token.items():
            for order in orders_list:
                oid = order.get("id") or order.get("orderID") or order.get("orderId", "")
                if oid and oid not in tracked_order_ids:
                    log.warning(
                        "%sRECONCILE_ORPHAN %s │ order=%s not tracked locally%s",
                        C_YELLOW, tid[:16], oid, C_RESET,
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
