"""Pure pricing functions for the rebate-maker strategy."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from rebate_maker.models import ONE, ZERO, MarketInventory

TICK_001 = Decimal("0.01")
WIDE_SPREAD = Decimal("0.06")
MIN_ORDER_SIZE = Decimal("5")  # Polymarket minimum

_TOTAL_FRACTION = Decimal("0.80")   # 80% max total exposure


def total_bankroll_cap(bankroll: Decimal) -> Decimal:
    """Return the maximum total exposure allowed for the given bankroll."""
    return bankroll * _TOTAL_FRACTION


def calculate_exposure(
    open_orders: dict,
    inventories: dict[str, MarketInventory],
) -> Decimal:
    """Calculate current capital exposure from open orders + inventory.

    Three components:
    1. Unfilled order notional (capital committed on the book)
    2. Unhedged imbalance x $1.00 (first-leg cost + hedge reserve)
    3. Hedged-but-unmerged cost (capital locked until merge settles)
    """
    orders_notional = ZERO
    reserved_hedge = ZERO
    for state in open_orders.values():
        if state is None or state.price is None or state.size is None:
            continue
        matched = state.matched_size if state.matched_size else ZERO
        remaining = max(ZERO, state.size - matched)
        orders_notional += state.price * remaining
        if state.reserved_hedge_notional and state.reserved_hedge_notional > ZERO:
            reserved_hedge += state.reserved_hedge_notional

    unhedged_exposure = ZERO
    hedged_locked = ZERO
    for inv in inventories.values():
        if inv is None:
            continue
        abs_imbalance = abs(inv.imbalance)
        if abs_imbalance > ZERO:
            if inv.imbalance > ZERO:
                vwap = inv.up_vwap or Decimal("0.50")
            else:
                vwap = inv.down_vwap or Decimal("0.50")
            first_leg_cost = abs_imbalance * vwap
            hedge_reserve = abs_imbalance * (ONE - vwap)
            unhedged_exposure += first_leg_cost + hedge_reserve
        hedged = min(inv.up_shares, inv.down_shares)
        if hedged > ZERO and inv.up_vwap is not None and inv.down_vwap is not None:
            hedged_locked += hedged * (inv.up_vwap + inv.down_vwap)

    return orders_notional + reserved_hedge + unhedged_exposure + hedged_locked


def calculate_exposure_breakdown(
    open_orders: dict,
    inventories: dict[str, MarketInventory],
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return (orders_notional, unhedged_exposure, hedged_locked, total_exposure)."""
    orders_notional = ZERO
    reserved_hedge = ZERO
    for state in open_orders.values():
        if state is None or state.price is None or state.size is None:
            continue
        matched = state.matched_size if state.matched_size else ZERO
        remaining = max(ZERO, state.size - matched)
        orders_notional += state.price * remaining
        if state.reserved_hedge_notional and state.reserved_hedge_notional > ZERO:
            reserved_hedge += state.reserved_hedge_notional

    unhedged_exposure = ZERO
    hedged_locked = ZERO
    for inv in inventories.values():
        if inv is None:
            continue
        abs_imbalance = abs(inv.imbalance)
        if abs_imbalance > ZERO:
            if inv.imbalance > ZERO:
                vwap = inv.up_vwap or Decimal("0.50")
            else:
                vwap = inv.down_vwap or Decimal("0.50")
            first_leg_cost = abs_imbalance * vwap
            hedge_reserve = abs_imbalance * (ONE - vwap)
            unhedged_exposure += first_leg_cost + hedge_reserve
        hedged = min(inv.up_shares, inv.down_shares)
        if hedged > ZERO and inv.up_vwap is not None and inv.down_vwap is not None:
            hedged_locked += hedged * (inv.up_vwap + inv.down_vwap)

    total = orders_notional + reserved_hedge + unhedged_exposure + hedged_locked
    return orders_notional, unhedged_exposure, hedged_locked, total


def calculate_grid_sizes(
    bankroll: Decimal,
    num_active_markets: int,
    grid_levels: int,
    prices: list[Decimal],
) -> list[tuple[Decimal, Decimal]]:
    """Calculate (price, size) tuples for a grid of orders.

    Total exposure across all levels x all markets <= bankroll.
    Even distribution: bankroll / (num_active_markets * grid_levels * 2) / avg_price per level.
    """
    if num_active_markets <= 0 or grid_levels <= 0 or bankroll <= ZERO:
        return []

    per_level_budget = bankroll / (num_active_markets * grid_levels * 2)

    result: list[tuple[Decimal, Decimal]] = []
    for price in prices:
        if price <= ZERO:
            continue
        size = (per_level_budget / price).quantize(TICK_001, rounding=ROUND_DOWN)
        if size >= ONE:
            result.append((price, size))

    return result
