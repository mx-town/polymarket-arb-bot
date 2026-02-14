"""Pure pricing functions for the complete-set strategy.

Translates QuoteCalculator.java. All functions are pure — no side effects.
"""

from __future__ import annotations

from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from typing import Optional

from complete_set.config import CompleteSetConfig
from complete_set.models import MarketInventory, TopOfBook

ZERO = Decimal("0")
ONE = Decimal("1")
TICK_001 = Decimal("0.01")
PRICE_MAX = Decimal("0.99")
WIDE_SPREAD = Decimal("0.06")
MIN_ORDER_SIZE = Decimal("5")  # Polymarket minimum


def round_to_tick(value: Decimal, tick_size: Decimal) -> Decimal:
    """Round value down to nearest tick."""
    if tick_size <= ZERO:
        return value
    ticks = (value / tick_size).to_integral_value(rounding=ROUND_DOWN)
    return ticks * tick_size


def calculate_entry_price(
    tob: TopOfBook,
    tick_size: Decimal,
    improve_ticks: int,
    skew_ticks: int,
) -> Optional[Decimal]:
    """Calculate maker entry price with inventory skew adjustment.

    Wide spread (>=0.06): mid - tick_size * max(0, improve - skew)
    Tight spread: min(best_bid + tick_size * (improve + skew), mid)
    """
    if tob.best_bid is None or tob.best_ask is None:
        return None

    mid = (tob.best_bid + tob.best_ask) / 2
    mid = mid.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
    spread = tob.best_ask - tob.best_bid

    if spread >= WIDE_SPREAD:
        effective = max(0, improve_ticks - skew_ticks)
        entry_price = mid - tick_size * Decimal(effective)
    else:
        effective = improve_ticks + skew_ticks
        improved_bid = tob.best_bid + tick_size * Decimal(effective)
        entry_price = min(improved_bid, mid)

    entry_price = round_to_tick(entry_price, tick_size)

    # Sanity checks
    if entry_price < TICK_001:
        return None
    if entry_price > PRICE_MAX:
        return None
    if entry_price >= tob.best_ask:
        entry_price = tob.best_ask - tick_size
        if entry_price < TICK_001:
            return None

    return entry_price


# ---------------------------------------------------------------------------
# Replica sizing schedule (from strategy spec / wallet analysis)
# ---------------------------------------------------------------------------

_SCHEDULE: dict[str, list[tuple[int, int]]] = {
    "btc-updown-15m": [
        (60, 11),
        (180, 13),
        (300, 17),
        (600, 19),
        (999999, 20),
    ],
    "eth-updown-15m": [
        (60, 8),
        (180, 10),
        (300, 12),
        (600, 13),
        (999999, 14),
    ],
    "bitcoin-up-or-down": [
        (60, 9),
        (180, 10),
        (300, 11),
        (600, 12),
        (900, 14),
        (1200, 15),
        (1800, 17),
        (999999, 18),
    ],
    "ethereum-up-or-down": [
        (60, 7),
        (300, 8),
        (600, 9),
        (900, 11),
        (1200, 12),
        (1800, 13),
        (999999, 14),
    ],
}


def _series_key(slug: str) -> Optional[str]:
    """Map a market slug to its sizing schedule key."""
    if slug.startswith("btc-updown-15m-"):
        return "btc-updown-15m"
    if slug.startswith("eth-updown-15m-"):
        return "eth-updown-15m"
    if slug.startswith("bitcoin-up-or-down-"):
        return "bitcoin-up-or-down"
    if slug.startswith("ethereum-up-or-down-"):
        return "ethereum-up-or-down"
    return None


def replica_shares_by_time(slug: str, seconds_to_end: int) -> Optional[Decimal]:
    """Look up base share size from the replica schedule."""
    key = _series_key(slug)
    if key is None:
        return None
    schedule = _SCHEDULE.get(key)
    if schedule is None:
        return None
    for threshold, shares in schedule:
        if seconds_to_end < threshold:
            return Decimal(shares)
    return None


def calculate_shares(
    slug: str,
    entry_price: Decimal,
    cfg: CompleteSetConfig,
    seconds_to_end: int,
    current_exposure: Decimal,
) -> Optional[Decimal]:
    """Calculate order size based on replica schedule and bankroll caps."""
    shares = replica_shares_by_time(slug, seconds_to_end)
    if shares is None:
        return None

    if entry_price is None or entry_price <= ZERO:
        return None

    # Apply per-order bankroll cap
    bankroll = cfg.bankroll_usd
    if bankroll > ZERO and cfg.max_order_bankroll_fraction > ZERO:
        per_order_cap = bankroll * cfg.max_order_bankroll_fraction
        cap_shares = (per_order_cap / entry_price).quantize(TICK_001, rounding=ROUND_DOWN)
        shares = min(shares, cap_shares)

    # Apply total bankroll cap
    if bankroll > ZERO and cfg.max_total_bankroll_fraction > ZERO:
        total_cap = bankroll * cfg.max_total_bankroll_fraction
        remaining = total_cap - current_exposure
        if remaining <= ZERO:
            return None
        cap_shares = (remaining / entry_price).quantize(TICK_001, rounding=ROUND_DOWN)
        shares = min(shares, cap_shares)

    shares = shares.quantize(TICK_001, rounding=ROUND_DOWN)
    if shares < MIN_ORDER_SIZE:
        return None
    return shares


def calculate_balanced_shares(
    slug: str,
    up_price: Decimal,
    down_price: Decimal,
    cfg: CompleteSetConfig,
    seconds_to_end: int,
    current_exposure: Decimal,
) -> Optional[Decimal]:
    """Calculate order size so both legs get the same number of shares.

    Uses the MORE EXPENSIVE price for bankroll caps so both legs fit
    within the budget, preventing share imbalances from asymmetric capping.
    """
    shares = replica_shares_by_time(slug, seconds_to_end)
    if shares is None:
        return None
    if up_price is None or up_price <= ZERO or down_price is None or down_price <= ZERO:
        return None

    bankroll = cfg.bankroll_usd

    # Per-order cap: use the more expensive price so both legs fit
    if bankroll > ZERO and cfg.max_order_bankroll_fraction > ZERO:
        per_order_cap = bankroll * cfg.max_order_bankroll_fraction
        expensive = max(up_price, down_price)
        cap_shares = (per_order_cap / expensive).quantize(TICK_001, rounding=ROUND_DOWN)
        shares = min(shares, cap_shares)

    # Total bankroll cap: use the more expensive price
    if bankroll > ZERO and cfg.max_total_bankroll_fraction > ZERO:
        total_cap = bankroll * cfg.max_total_bankroll_fraction
        remaining = total_cap - current_exposure
        if remaining <= ZERO:
            return None
        expensive = max(up_price, down_price)
        cap_shares = (remaining / expensive).quantize(TICK_001, rounding=ROUND_DOWN)
        shares = min(shares, cap_shares)

    shares = shares.quantize(TICK_001, rounding=ROUND_DOWN)
    if shares < MIN_ORDER_SIZE:
        return None
    return shares


def calculate_skew_ticks(
    inventory: MarketInventory,
    max_skew: int,
    imbalance_threshold: Decimal,
) -> tuple[int, int]:
    """Calculate inventory-based skew ticks.

    Returns (skew_up, skew_down) where positive means improve that leg,
    negative means penalize (widen) that leg.
    """
    if imbalance_threshold <= ZERO or max_skew <= 0:
        return (0, 0)

    imbalance = inventory.imbalance
    skew_ratio = min(1.0, abs(float(imbalance)) / float(imbalance_threshold))
    # Use math.floor(x + 0.5) to match Java's Math.round() (rounds 0.5 up)
    import math
    skew_ticks = math.floor(skew_ratio * max_skew + 0.5)

    if imbalance > ZERO:
        # More UP shares → improve DOWN quote, penalize UP quote
        return (-skew_ticks, skew_ticks)
    elif imbalance < ZERO:
        # More DOWN shares → improve UP quote, penalize DOWN quote
        return (skew_ticks, -skew_ticks)
    return (0, 0)


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
