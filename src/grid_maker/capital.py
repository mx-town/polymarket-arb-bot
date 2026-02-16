"""Capital management — budget allocation, grid sizing, and compounding."""

from __future__ import annotations

import logging
import math
from decimal import ROUND_DOWN, Decimal

log = logging.getLogger("gm.capital")

ZERO = Decimal("0")
ONE = Decimal("1")
TICK = Decimal("0.01")


def calculate_per_market_budget(
    bankroll: Decimal,
    n_active_markets: int,
) -> Decimal:
    """Calculate USDC budget per market, evenly distributed."""
    if n_active_markets <= 0 or bankroll <= ZERO:
        return ZERO
    return (bankroll / n_active_markets).quantize(TICK, rounding=ROUND_DOWN)


def calculate_static_grid(
    min_price: Decimal,
    max_price: Decimal,
    grid_step: Decimal,
    target_size: Decimal,
    budget: Decimal,
) -> list[tuple[Decimal, Decimal]]:
    """Calculate (price, size) pairs for a static full-range grid.

    Always returns ALL levels from min_price to max_price at grid_step
    increments.  If the budget can afford target_size at every level, use
    target_size.  Otherwise scale down proportionally so every level gets
    the same (smaller) size — never truncate coverage.

    Minimum size per level is 1 share.
    """
    if min_price <= ZERO or max_price < min_price or grid_step <= ZERO:
        return []
    if target_size <= ZERO or budget <= ZERO:
        return []

    # Generate all price levels
    prices: list[Decimal] = []
    p = min_price
    while p <= max_price:
        prices.append(p)
        p += grid_step

    if not prices:
        return []

    # Compute ideal cost at full target_size
    ideal_cost = sum(price * target_size for price in prices)

    if budget >= ideal_cost:
        # Full size at every level
        return [(price, target_size) for price in prices]

    # Scale down: every level gets floor(target_size * scale_factor), min 1
    scale_factor = budget / ideal_cost
    scaled_raw = target_size * scale_factor
    # Use math.floor on float conversion for clean integer-like sizing
    scaled_int = max(1, math.floor(float(scaled_raw)))
    scaled_size = Decimal(str(scaled_int))

    # Verify we can actually afford this — if even 1 share/level exceeds budget, cap
    total_at_scaled = sum(price * scaled_size for price in prices)
    if total_at_scaled > budget:
        scaled_size = ONE

    return [(price, scaled_size) for price in prices]


def compound_bankroll(
    current_bankroll: Decimal,
    session_pnl: Decimal,
    rebate_income: Decimal = ZERO,
) -> Decimal:
    """Recalculate bankroll by adding session P&L and rebate income.

    Only compounds upward — never reduces bankroll below current level
    (drawdowns are absorbed, not compounded downward).
    """
    new_bankroll = current_bankroll + session_pnl + rebate_income
    return max(current_bankroll, new_bankroll)
