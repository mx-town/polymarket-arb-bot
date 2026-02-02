"""
Order Book Feature Extraction

Provides functions to extract trading-relevant features from order book data:
- Ask book traversal for execution price estimation
- Book imbalance for directional pressure
- VWAP calculation for average execution cost
- Spread analysis

These features are critical for:
1. Dutch Book detection (combined ask prices)
2. Execution cost estimation
3. Market microstructure signals
"""

from dataclasses import dataclass
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class OrderBookLevel:
    """Single level in an order book."""
    price: float
    size: float


@dataclass
class OrderBookSnapshot:
    """Complete order book snapshot."""
    bids: list[OrderBookLevel]  # Sorted best (highest) first
    asks: list[OrderBookLevel]  # Sorted best (lowest) first
    timestamp_ms: int


@dataclass
class OrderBookFeatures:
    """Extracted features from order book."""
    # Spread metrics
    best_bid: float
    best_ask: float
    spread: float
    spread_bps: float  # Spread in basis points
    midpoint: float

    # Depth metrics
    bid_depth_5: float  # Total size in top 5 bid levels
    ask_depth_5: float  # Total size in top 5 ask levels
    imbalance: float    # [-1, 1] range

    # Execution estimates
    vwap_ask_100: Optional[float]  # VWAP to buy $100 worth
    vwap_bid_100: Optional[float]  # VWAP to sell $100 worth

    timestamp_ms: int


def get_executable_price(
    book_asks: list[tuple[float, float]],
    target_size: float
) -> Optional[float]:
    """
    Walk the ask book to find actual execution price for a given size.

    DO NOT use last_trade_price or best_ask alone - this accounts for
    depth and slippage.

    Args:
        book_asks: List of (price, size) tuples, sorted by price ascending
        target_size: Number of shares/contracts to buy

    Returns:
        Weighted average execution price, or None if insufficient liquidity

    Example:
        >>> asks = [(0.50, 100), (0.51, 100), (0.52, 50)]
        >>> get_executable_price(asks, 150)
        0.5033...  # (100*0.50 + 50*0.51) / 150
    """
    if not book_asks or target_size <= 0:
        return None

    filled = 0.0
    total_cost = 0.0

    for price, size in sorted(book_asks, key=lambda x: x[0]):
        take = min(size, target_size - filled)
        total_cost += take * price
        filled += take

        if filled >= target_size:
            break

    if filled <= 0:
        return None

    return total_cost / filled


def get_executable_price_bid(
    book_bids: list[tuple[float, float]],
    target_size: float
) -> Optional[float]:
    """
    Walk the bid book to find actual execution price for selling.

    Args:
        book_bids: List of (price, size) tuples, sorted by price descending
        target_size: Number of shares/contracts to sell

    Returns:
        Weighted average execution price, or None if insufficient liquidity
    """
    if not book_bids or target_size <= 0:
        return None

    filled = 0.0
    total_value = 0.0

    # Bids should be sorted highest first
    for price, size in sorted(book_bids, key=lambda x: -x[0]):
        take = min(size, target_size - filled)
        total_value += take * price
        filled += take

        if filled >= target_size:
            break

    if filled <= 0:
        return None

    return total_value / filled


def calculate_book_imbalance(
    bids: list[tuple[float, float]],
    asks: list[tuple[float, float]],
    levels: int = 5
) -> float:
    """
    Calculate order book imbalance from top N levels.

    Imbalance = (bid_depth - ask_depth) / (bid_depth + ask_depth)

    Args:
        bids: List of (price, size) tuples
        asks: List of (price, size) tuples
        levels: Number of levels to consider

    Returns:
        Imbalance in range [-1, 1]
        - Positive: More bid pressure (bullish)
        - Negative: More ask pressure (bearish)
        - Zero: Balanced

    Example:
        >>> bids = [(99, 100), (98, 100)]
        >>> asks = [(101, 50), (102, 50)]
        >>> calculate_book_imbalance(bids, asks, levels=2)
        0.5  # (200 - 100) / (200 + 100)
    """
    # Sort bids descending, asks ascending
    sorted_bids = sorted(bids, key=lambda x: -x[0])[:levels]
    sorted_asks = sorted(asks, key=lambda x: x[0])[:levels]

    bid_depth = sum(size for _, size in sorted_bids)
    ask_depth = sum(size for _, size in sorted_asks)

    total_depth = bid_depth + ask_depth
    if total_depth <= 0:
        return 0.0

    return (bid_depth - ask_depth) / total_depth


def calculate_vwap_ask(
    book_asks: list[tuple[float, float]],
    depth_usd: float
) -> Optional[float]:
    """
    Calculate volume-weighted average price for buying depth_usd worth.

    Args:
        book_asks: List of (price, size) tuples
        depth_usd: Dollar amount to buy

    Returns:
        VWAP for the purchase, or None if insufficient liquidity

    Example:
        >>> asks = [(0.50, 1000), (0.51, 1000)]
        >>> calculate_vwap_ask(asks, 600)
        0.5033...  # Buy 1000@0.50=$500, then 196@0.51=$100
    """
    if not book_asks or depth_usd <= 0:
        return None

    filled_value = 0.0
    filled_size = 0.0

    for price, size in sorted(book_asks, key=lambda x: x[0]):
        if price <= 0:
            continue

        value_at_level = size * price
        if filled_value + value_at_level >= depth_usd:
            # Partial fill at this level
            remaining_value = depth_usd - filled_value
            remaining_size = remaining_value / price
            filled_size += remaining_size
            filled_value = depth_usd
            break

        filled_value += value_at_level
        filled_size += size

    if filled_size <= 0:
        return None

    return filled_value / filled_size


def calculate_vwap_bid(
    book_bids: list[tuple[float, float]],
    depth_usd: float
) -> Optional[float]:
    """
    Calculate volume-weighted average price for selling depth_usd worth.

    Args:
        book_bids: List of (price, size) tuples
        depth_usd: Dollar amount to sell

    Returns:
        VWAP for the sale, or None if insufficient liquidity
    """
    if not book_bids or depth_usd <= 0:
        return None

    filled_value = 0.0
    filled_size = 0.0

    for price, size in sorted(book_bids, key=lambda x: -x[0]):
        if price <= 0:
            continue

        value_at_level = size * price
        if filled_value + value_at_level >= depth_usd:
            remaining_value = depth_usd - filled_value
            remaining_size = remaining_value / price
            filled_size += remaining_size
            filled_value = depth_usd
            break

        filled_value += value_at_level
        filled_size += size

    if filled_size <= 0:
        return None

    return filled_value / filled_size


def calculate_spread(
    best_bid: float,
    best_ask: float
) -> tuple[float, float]:
    """
    Calculate spread in absolute and basis point terms.

    Args:
        best_bid: Best (highest) bid price
        best_ask: Best (lowest) ask price

    Returns:
        Tuple of (spread, spread_bps)

    Example:
        >>> calculate_spread(0.49, 0.51)
        (0.02, 400.0)  # 2 cents, 400 bps
    """
    spread = best_ask - best_bid
    midpoint = (best_ask + best_bid) / 2

    if midpoint <= 0:
        return (spread, 0.0)

    spread_bps = (spread / midpoint) * 10000
    return (spread, spread_bps)


def extract_orderbook_features(
    snapshot: OrderBookSnapshot,
    vwap_depth: float = 100.0
) -> OrderBookFeatures:
    """
    Extract all order book features from a snapshot.

    Args:
        snapshot: Order book snapshot
        vwap_depth: Dollar depth for VWAP calculation

    Returns:
        OrderBookFeatures dataclass with all metrics
    """
    if not snapshot.bids or not snapshot.asks:
        # Return empty features for empty book
        return OrderBookFeatures(
            best_bid=0.0,
            best_ask=0.0,
            spread=0.0,
            spread_bps=0.0,
            midpoint=0.0,
            bid_depth_5=0.0,
            ask_depth_5=0.0,
            imbalance=0.0,
            vwap_ask_100=None,
            vwap_bid_100=None,
            timestamp_ms=snapshot.timestamp_ms
        )

    # Convert to tuples
    bids = [(l.price, l.size) for l in snapshot.bids]
    asks = [(l.price, l.size) for l in snapshot.asks]

    # Best prices
    best_bid = max(b[0] for b in bids) if bids else 0.0
    best_ask = min(a[0] for a in asks) if asks else 0.0

    # Spread
    spread, spread_bps = calculate_spread(best_bid, best_ask)
    midpoint = (best_bid + best_ask) / 2 if best_bid > 0 and best_ask > 0 else 0.0

    # Depth
    sorted_bids = sorted(bids, key=lambda x: -x[0])[:5]
    sorted_asks = sorted(asks, key=lambda x: x[0])[:5]
    bid_depth_5 = sum(s for _, s in sorted_bids)
    ask_depth_5 = sum(s for _, s in sorted_asks)

    # Imbalance
    imbalance = calculate_book_imbalance(bids, asks, levels=5)

    # VWAP
    vwap_ask = calculate_vwap_ask(asks, vwap_depth)
    vwap_bid = calculate_vwap_bid(bids, vwap_depth)

    return OrderBookFeatures(
        best_bid=best_bid,
        best_ask=best_ask,
        spread=spread,
        spread_bps=spread_bps,
        midpoint=midpoint,
        bid_depth_5=bid_depth_5,
        ask_depth_5=ask_depth_5,
        imbalance=imbalance,
        vwap_ask_100=vwap_ask,
        vwap_bid_100=vwap_bid,
        timestamp_ms=snapshot.timestamp_ms
    )


def check_dutch_book_opportunity(
    up_asks: list[tuple[float, float]],
    down_asks: list[tuple[float, float]],
    target_size: float,
    threshold: float = 0.99
) -> tuple[bool, float, float, float]:
    """
    Check for Dutch Book arbitrage opportunity.

    In a binary market, UP + DOWN should equal $1.00. If we can buy both
    for less than $1.00, we have guaranteed profit.

    Args:
        up_asks: Ask book for UP token
        down_asks: Ask book for DOWN token
        target_size: Size to check
        threshold: Maximum combined cost to trigger (default 0.99)

    Returns:
        Tuple of (is_opportunity, up_price, down_price, combined_cost)

    Example:
        >>> up_asks = [(0.48, 100)]
        >>> down_asks = [(0.50, 100)]
        >>> check_dutch_book_opportunity(up_asks, down_asks, 50)
        (True, 0.48, 0.50, 0.98)
    """
    up_price = get_executable_price(up_asks, target_size)
    down_price = get_executable_price(down_asks, target_size)

    if up_price is None or down_price is None:
        return (False, 0.0, 0.0, 1.0)

    combined_cost = up_price + down_price
    is_opportunity = combined_cost < threshold

    return (is_opportunity, up_price, down_price, combined_cost)
