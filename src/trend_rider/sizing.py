"""Position sizing for trend-rider entries."""

from __future__ import annotations

from decimal import ROUND_DOWN, Decimal

from complete_set.models import ZERO
from trend_rider.config import TrendRiderConfig

MIN_SHARES = Decimal("5")


def calculate_trend_size(
    entry_price: Decimal,
    cfg: TrendRiderConfig,
    current_exposure: Decimal,
) -> Decimal | None:
    """Calculate shares to buy for a trend entry.

    Returns None if size is below minimum threshold.
    """
    max_notional = cfg.bankroll_usd * cfg.max_position_pct
    remaining = cfg.bankroll_usd - current_exposure
    if remaining <= ZERO:
        return None
    notional = min(max_notional, remaining)
    shares = (notional / entry_price).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    if shares < MIN_SHARES:
        return None
    return shares
