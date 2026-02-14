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


def clear_market_history(slug: str) -> None:
    """Remove price history for a market that rotated out."""
    _prob_history.pop(slug, None)
