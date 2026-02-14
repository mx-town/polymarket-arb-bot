"""Pure pricing functions for the complete-set strategy."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal
from typing import Optional

from complete_set.config import CompleteSetConfig
from complete_set.models import ONE, ZERO, MarketInventory

TICK_001 = Decimal("0.01")
WIDE_SPREAD = Decimal("0.06")
MIN_ORDER_SIZE = Decimal("5")  # Polymarket minimum

# ---------------------------------------------------------------------------
# Auto-scaling bankroll sizing
# ---------------------------------------------------------------------------

_ORDER_FRACTION = Decimal("0.20")   # 20% of bankroll per order
_TOTAL_FRACTION = Decimal("0.80")   # 80% max total exposure

# Time factors derived from BTC 15m schedule ratios (11/20, 13/20, 17/20, 19/20, 20/20)
_TIME_FACTORS: list[tuple[int, Decimal]] = [
    (60,     Decimal("0.55")),
    (180,    Decimal("0.65")),
    (300,    Decimal("0.85")),
    (600,    Decimal("0.95")),
    (999999, ONE),
]


def total_bankroll_cap(bankroll: Decimal) -> Decimal:
    """Return the maximum total exposure allowed for the given bankroll."""
    return bankroll * _TOTAL_FRACTION


def calculate_balanced_shares(
    slug: str,
    up_price: Decimal,
    down_price: Decimal,
    cfg: CompleteSetConfig,
    seconds_to_end: int,
    current_exposure: Decimal,
) -> Optional[Decimal]:
    """Calculate order size from bankroll, scaling with time-to-end.

    Uses the MORE EXPENSIVE price for all caps so both legs fit
    within the budget, preventing share imbalances from asymmetric capping.
    """
    if up_price is None or up_price <= ZERO or down_price is None or down_price <= ZERO:
        return None

    bankroll = cfg.bankroll_usd
    if bankroll <= ZERO:
        return None

    expensive = max(up_price, down_price)

    # Base shares from bankroll fraction
    base = (bankroll * _ORDER_FRACTION / expensive).quantize(TICK_001, rounding=ROUND_DOWN)

    # Apply time factor
    time_factor = ONE
    for threshold, factor in _TIME_FACTORS:
        if seconds_to_end < threshold:
            time_factor = factor
            break
    shares = (base * time_factor).quantize(TICK_001, rounding=ROUND_DOWN)

    # Cap by total exposure
    total_cap = total_bankroll_cap(bankroll)
    remaining = total_cap - current_exposure
    if remaining <= ZERO:
        return None
    cap_shares = (remaining / expensive).quantize(TICK_001, rounding=ROUND_DOWN)
    shares = min(shares, cap_shares)

    if shares < MIN_ORDER_SIZE:
        return None
    return shares


def calculate_dynamic_edge(spread: Decimal, base_min_edge: Decimal) -> Decimal:
    """Scale min_edge with spread width to protect against adverse fills.

    Spread < 6%:  base_min_edge (tight market, good fills)
    Spread 6-10%: base_min_edge × 1.5 (moderate risk)
    Spread >= 10%: base_min_edge × 2.0 (wide spread, high slippage risk)
    """
    if spread >= Decimal("0.10"):
        return base_min_edge * 2
    if spread >= WIDE_SPREAD:
        return (base_min_edge * 3 / 2).quantize(Decimal("0.001"))
    return base_min_edge


def has_minimum_edge(up_price: Decimal, down_price: Decimal, min_edge: Decimal) -> bool:
    """Check if complete-set edge is sufficient: 1 - (up + down) >= min_edge."""
    cost = up_price + down_price
    edge = ONE - cost
    return edge >= min_edge


def calculate_exposure(
    open_orders: dict,
    inventories: dict[str, MarketInventory],
) -> Decimal:
    """Calculate current capital exposure from open orders + inventory.

    Three components:
    1. Unfilled order notional (capital committed on the book)
    2. Unhedged imbalance × $0.50 (directional risk)
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
            unhedged_exposure += abs_imbalance * vwap
        hedged = min(inv.up_shares, inv.down_shares)
        if hedged > ZERO and inv.up_vwap is not None and inv.down_vwap is not None:
            hedged_locked += hedged * (inv.up_vwap + inv.down_vwap)

    return orders_notional + reserved_hedge + unhedged_exposure + hedged_locked


def calculate_exposure_breakdown(
    open_orders: dict,
    inventories: dict[str, MarketInventory],
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """Return (orders_notional, unhedged_exposure, hedged_locked, total_exposure).

    - orders_notional: unfilled order notional on the book
    - unhedged_exposure: imbalance × $0.50 (directional risk)
    - hedged_locked: cost of hedged-but-unmerged pairs (capital locked until merge)
    - total_exposure: sum of all three (what counts against bankroll)
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
            unhedged_exposure += abs_imbalance * vwap
        hedged = min(inv.up_shares, inv.down_shares)
        if hedged > ZERO and inv.up_vwap is not None and inv.down_vwap is not None:
            hedged_locked += hedged * (inv.up_vwap + inv.down_vwap)

    total = orders_notional + reserved_hedge + unhedged_exposure + hedged_locked
    return orders_notional, unhedged_exposure, hedged_locked, total
