"""
Market filtering functions.

Filter markets based on liquidity, timing, and other criteria.
"""

from datetime import datetime
from typing import Optional

from src.market.state import MarketState, MarketStateManager
from src.config import FilterConfig
from src.utils.logging import get_logger

logger = get_logger("filters")


def filter_by_liquidity(
    market: MarketState,
    min_liquidity_usd: float = 1000.0,
    min_book_depth: float = 500.0,
) -> bool:
    """
    Check if market has sufficient liquidity.

    Args:
        market: MarketState to check
        min_liquidity_usd: Minimum total liquidity
        min_book_depth: Minimum size at best bid/ask

    Returns:
        True if market passes liquidity checks
    """
    # Check bid sizes
    if market.up_bid_size < min_book_depth or market.down_bid_size < min_book_depth:
        return False

    # Check ask sizes
    if market.up_ask_size < min_book_depth or market.down_ask_size < min_book_depth:
        return False

    return True


def filter_by_spread(
    market: MarketState,
    max_spread_pct: float = 0.05,
) -> bool:
    """
    Check if market has acceptable spread.

    Args:
        market: MarketState to check
        max_spread_pct: Maximum bid-ask spread percentage

    Returns:
        True if spreads are acceptable
    """
    if market.spread_up > max_spread_pct:
        return False
    if market.spread_down > max_spread_pct:
        return False
    return True


def filter_by_time_to_resolution(
    market: MarketState,
    min_seconds: int = 300,
) -> bool:
    """
    Check if market has enough time before resolution.

    Args:
        market: MarketState to check
        min_seconds: Minimum seconds until resolution

    Returns:
        True if enough time remains
    """
    time_remaining = market.time_to_resolution
    if time_remaining is None:
        return True  # No resolution time set, allow
    return time_remaining >= min_seconds


def filter_market(
    market: MarketState,
    config: FilterConfig,
    min_time_to_resolution: int = 300,
) -> bool:
    """
    Apply all filters to a market.

    Args:
        market: MarketState to check
        config: FilterConfig with thresholds
        min_time_to_resolution: Minimum seconds until resolution

    Returns:
        True if market passes all filters
    """
    if not market.is_valid:
        return False

    if not filter_by_time_to_resolution(market, min_time_to_resolution):
        logger.debug("FILTER_REJECT", f"market={market.slug} reason=time_to_resolution")
        return False

    # Only apply liquidity/spread filters if we have size data
    if market.up_bid_size > 0 and market.down_bid_size > 0:
        if not filter_by_liquidity(market, config.min_liquidity_usd, config.min_book_depth):
            logger.debug("FILTER_REJECT", f"market={market.slug} reason=liquidity")
            return False

        if not filter_by_spread(market, config.max_spread_pct):
            logger.debug("FILTER_REJECT", f"market={market.slug} reason=spread")
            return False

    return True


def get_tradeable_markets(
    manager: MarketStateManager,
    config: FilterConfig,
    min_time_to_resolution: int = 300,
) -> list[MarketState]:
    """
    Get all markets that pass filters.

    Args:
        manager: MarketStateManager with markets
        config: FilterConfig with thresholds
        min_time_to_resolution: Minimum seconds until resolution

    Returns:
        List of MarketState objects that pass all filters
    """
    tradeable = []
    for market in manager.get_valid_markets():
        if filter_market(market, config, min_time_to_resolution):
            tradeable.append(market)

    logger.info("TRADEABLE", f"count={len(tradeable)}/{len(manager.markets)}")
    return tradeable
