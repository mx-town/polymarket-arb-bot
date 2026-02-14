"""Price history tracking for complete-set markets.

Records UP/DOWN ask prices over time for volatility analysis.
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

_MAX_HISTORY = 1800  # ring buffer cap per market


@dataclass(frozen=True)
class ProbSnapshot:
    timestamp: float
    up_ask: Decimal
    down_ask: Decimal


# Module-level state -- per-market ring buffer
_prob_history: dict[str, deque[ProbSnapshot]] = {}


def record_prices(slug: str, up_ask: Decimal, down_ask: Decimal) -> None:
    """Append a price snapshot for the given market."""
    buf = _prob_history.get(slug)
    if buf is None:
        buf = deque(maxlen=_MAX_HISTORY)
        _prob_history[slug] = buf
    buf.append(ProbSnapshot(timestamp=time.time(), up_ask=up_ask, down_ask=down_ask))


def opposite_was_cheap(
    slug: str,
    buying_up: bool,
    lookback_sec: float,
    threshold: Decimal,
) -> bool:
    """Check if the opposite side was recently below threshold.

    If buying UP, check if DOWN was recently cheap.
    If buying DOWN, check if UP was recently cheap.
    Returns True (permissive) when insufficient history.
    """
    buf = _prob_history.get(slug)
    if not buf:
        return True

    now = time.time()
    cutoff = now - lookback_sec

    # Not enough history to judge — be permissive
    if buf[0].timestamp > cutoff:
        return True

    for snap in buf:
        if snap.timestamp < cutoff:
            continue
        if buying_up and snap.down_ask <= threshold:
            return True
        if not buying_up and snap.up_ask <= threshold:
            return True

    return False


def clear_market_history(slug: str) -> None:
    """Remove price history for a market that rotated out."""
    _prob_history.pop(slug, None)
