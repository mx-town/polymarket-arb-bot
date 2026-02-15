"""Pure entry signal logic — BTC momentum + market conditions."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from complete_set.binance_ws import is_btc_trending
from complete_set.models import ZERO, Direction
from trend_rider.config import TrendRiderConfig

log = logging.getLogger("tr.signal")


@dataclass(frozen=True)
class TrendSignal:
    direction: Direction
    favorite_ask: Decimal
    underdog_ask: Decimal
    btc_move_usd: Decimal
    reason: str


def evaluate_trend_entry(
    seconds_to_end: int,
    up_ask: Optional[Decimal],
    down_ask: Optional[Decimal],
    up_bid: Optional[Decimal],
    down_bid: Optional[Decimal],
    cfg: TrendRiderConfig,
) -> Optional[TrendSignal]:
    """Evaluate whether this market qualifies for a trend-rider entry.

    Returns TrendSignal if all conditions met, None with a log otherwise.
    """
    # 1. Time window check
    if seconds_to_end < cfg.min_seconds_to_end:
        return None
    if seconds_to_end > cfg.max_seconds_to_end:
        return None

    # 2. Need valid prices
    if up_ask is None or down_ask is None or up_bid is None or down_bid is None:
        return None

    # 3. Combined asks gate — only trade when complete-set has no edge
    combined_asks = up_ask + down_ask
    if combined_asks < cfg.min_combined_asks:
        log.debug("TREND_SKIP combined_asks=%.4f < %.2f", combined_asks, cfg.min_combined_asks)
        return None

    # 4. BTC momentum — must be trending
    trending, btc_move = is_btc_trending(
        lookback_sec=cfg.momentum_lookback_sec,
        threshold=cfg.momentum_threshold_usd,
    )
    if not trending:
        log.debug("TREND_SKIP btc_move=$%.1f (need $%s)", btc_move, cfg.momentum_threshold_usd)
        return None

    # 5. Direction: BTC up → buy UP side, BTC down → buy DOWN side
    if btc_move > ZERO:
        direction = Direction.UP
        favorite_ask = up_ask
        underdog_ask = down_ask
    else:
        direction = Direction.DOWN
        favorite_ask = down_ask
        underdog_ask = up_ask

    # 6. Market alignment: favorite must be in [min, max] price range
    if favorite_ask < cfg.min_favorite_price:
        log.debug(
            "TREND_SKIP %s fav_ask=%.2f < min %.2f",
            direction.value, favorite_ask, cfg.min_favorite_price,
        )
        return None
    if favorite_ask > cfg.max_favorite_price:
        log.debug(
            "TREND_SKIP %s fav_ask=%.2f > max %.2f",
            direction.value, favorite_ask, cfg.max_favorite_price,
        )
        return None

    # 7. Not already decided: underdog must have some value
    if underdog_ask < cfg.min_underdog_ask:
        log.debug(
            "TREND_SKIP %s underdog_ask=%.2f < min %.2f — market decided",
            direction.value, underdog_ask, cfg.min_underdog_ask,
        )
        return None

    return TrendSignal(
        direction=direction,
        favorite_ask=favorite_ask,
        underdog_ask=underdog_ask,
        btc_move_usd=btc_move,
        reason=(
            f"BTC {'↑' if btc_move > ZERO else '↓'}"
            f" ${abs(btc_move):.0f}/{cfg.momentum_lookback_sec}s"
            f" fav={favorite_ask} combined={combined_asks:.2f}"
        ),
    )
