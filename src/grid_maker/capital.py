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


def calculate_grid_allocation(
    budget: Decimal,
    grid_levels: int,
    base_size: Decimal,
    grid_step: Decimal,
    best_bid: Decimal,
    size_curve: str = "flat",
) -> list[tuple[Decimal, Decimal]]:
    """Calculate (price, size) pairs for one side of a grid.

    Posts grid_levels GTC BUY orders from best_bid + step*1 up to
    best_bid + step*grid_levels.

    size_curve:
        "flat" — uniform size across all levels
        "bell" — larger sizes near the mid, tapering at edges

    Returns list of (price, size) tuples. Total notional ≤ budget.
    """
    if grid_levels <= 0 or budget <= ZERO or best_bid is None:
        return []

    # Generate price levels
    prices: list[Decimal] = []
    for i in range(1, grid_levels + 1):
        p = best_bid + grid_step * i
        if ZERO < p < ONE:
            prices.append(p)

    if not prices:
        return []

    # Calculate sizes based on curve
    if size_curve == "bell":
        # Bell curve: peak at middle level, taper at edges
        mid = len(prices) / 2.0
        raw_weights = [
            Decimal(str(math.exp(-((i - mid) ** 2) / (2 * (len(prices) / 4) ** 2))))
            for i in range(len(prices))
        ]
        total_weight = sum(raw_weights)
        if total_weight <= ZERO:
            return []
        sizes = [
            (base_size * w / total_weight * len(prices)).quantize(TICK, rounding=ROUND_DOWN)
            for w in raw_weights
        ]
    else:
        # Flat: uniform size
        sizes = [base_size] * len(prices)

    # Cap total notional to budget
    result: list[tuple[Decimal, Decimal]] = []
    total_notional = ZERO
    for price, size in zip(prices, sizes):
        if size <= ZERO:
            continue
        notional = price * size
        if total_notional + notional > budget:
            # Reduce this level to fit within budget
            remaining_budget = budget - total_notional
            if remaining_budget <= ZERO:
                break
            capped_size = (remaining_budget / price).quantize(TICK, rounding=ROUND_DOWN)
            if capped_size >= ONE:
                result.append((price, capped_size))
            break
        result.append((price, size))
        total_notional += notional

    return result


def calculate_static_grid(
    min_price: Decimal,
    max_price: Decimal,
    grid_step: Decimal,
    fixed_size: Decimal,
    budget: Decimal,
) -> list[tuple[Decimal, Decimal]]:
    """Calculate (price, size) pairs for a static full-range grid.

    Generates prices from min_price to max_price at grid_step increments.
    Every level gets fixed_size shares. Budget cap is applied from the
    cheapest end (most levels for the money).

    Does NOT depend on best_bid — prices are absolute.
    """
    if min_price <= ZERO or max_price < min_price or grid_step <= ZERO:
        return []
    if fixed_size <= ZERO or budget <= ZERO:
        return []

    # Generate all price levels
    prices: list[Decimal] = []
    p = min_price
    while p <= max_price:
        prices.append(p)
        p += grid_step

    if not prices:
        return []

    # Assign fixed_size to every level, cap at budget (cheapest first)
    result: list[tuple[Decimal, Decimal]] = []
    total_notional = ZERO
    for price in prices:
        notional = price * fixed_size
        if total_notional + notional > budget:
            remaining = budget - total_notional
            if remaining <= ZERO:
                break
            capped_size = (remaining / price).quantize(TICK, rounding=ROUND_DOWN)
            if capped_size >= ONE:
                result.append((price, capped_size))
            break
        result.append((price, fixed_size))
        total_notional += notional

    return result


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


def scale_grid_params(
    bankroll: Decimal,
    base_levels: int,
    base_size: Decimal,
) -> tuple[int, Decimal]:
    """Scale grid levels and size as bankroll grows.

    At 2x bankroll: +50% levels, same size (wider coverage)
    At 4x bankroll: +50% levels, +50% size (both dimensions)

    Returns (scaled_levels, scaled_size).
    """
    base_bankroll = Decimal("500")  # reference point
    if bankroll <= base_bankroll:
        return base_levels, base_size

    ratio = bankroll / base_bankroll

    # Scale levels: sqrt growth (more coverage, not linear)
    level_factor = Decimal(str(math.sqrt(float(ratio))))
    scaled_levels = max(base_levels, int(base_levels * level_factor))

    # Scale size: only after 4x bankroll
    if ratio >= 4:
        size_factor = Decimal(str(math.sqrt(float(ratio / 4))))
        scaled_size = (base_size * size_factor).quantize(TICK, rounding=ROUND_DOWN)
    else:
        scaled_size = base_size

    log.info(
        "SCALE │ bankroll=$%s ratio=%.1fx │ levels=%d→%d size=%s→%s",
        bankroll, float(ratio), base_levels, scaled_levels, base_size, scaled_size,
    )
    return scaled_levels, scaled_size
