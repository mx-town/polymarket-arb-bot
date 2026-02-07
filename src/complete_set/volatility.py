"""Probability swing tracking for complete-set entry filtering.

Tracks UP/DOWN ask prices over time and computes swing amplitude +
efficiency ratio to distinguish oscillating markets (good for arb)
from trending or calm markets (bad — one side stays expensive).
"""

from __future__ import annotations

import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

_MAX_HISTORY = 1800  # ring buffer cap per market


@dataclass(frozen=True)
class ProbSnapshot:
    timestamp: float
    up_ask: Decimal
    down_ask: Decimal


@dataclass(frozen=True)
class SwingSignal:
    sample_count: int
    window_seconds: float
    up_swing: Decimal
    down_swing: Decimal
    net_move: Decimal
    efficiency: Decimal
    direction_changes: int
    is_oscillating: bool


# Module-level state — per-market ring buffer
_prob_history: dict[str, deque[ProbSnapshot]] = {}


def record_prices(slug: str, up_ask: Decimal, down_ask: Decimal) -> None:
    """Append a price snapshot for the given market."""
    buf = _prob_history.get(slug)
    if buf is None:
        buf = deque(maxlen=_MAX_HISTORY)
        _prob_history[slug] = buf
    buf.append(ProbSnapshot(timestamp=time.time(), up_ask=up_ask, down_ask=down_ask))


def analyze_swings(
    slug: str,
    min_samples: int = 20,
    lookback_seconds: float = 120.0,
    min_swing: Decimal = Decimal("0.05"),
    max_efficiency: Decimal = Decimal("0.60"),
    min_reversals: int = 2,
) -> Optional[SwingSignal]:
    """Analyze price history to determine if market is oscillating.

    Returns None if insufficient data (caller should bypass filter).
    """
    buf = _prob_history.get(slug)
    if not buf or len(buf) < min_samples:
        return None

    now = time.time()

    # Full history for net_move / efficiency (total drift since tracking started)
    first = buf[0]
    last = buf[-1]
    net_move = abs(last.up_ask - first.up_ask)

    # Lookback window for swing amplitude + direction changes
    cutoff = now - lookback_seconds
    window = [s for s in buf if s.timestamp >= cutoff]
    if len(window) < min_samples:
        return None

    up_prices = [s.up_ask for s in window]
    down_prices = [s.down_ask for s in window]

    up_swing = max(up_prices) - min(up_prices)
    down_swing = max(down_prices) - min(down_prices)
    swing = max(up_swing, down_swing)

    # Efficiency: net drift / total swing (0 = oscillating, 1 = trending)
    efficiency = (net_move / swing) if swing > 0 else Decimal("1")

    # Direction changes: count reversals in UP ask with smoothing threshold
    direction_changes = _count_direction_changes(up_prices, threshold=Decimal("0.005"))

    is_oscillating = (
        swing >= min_swing
        and efficiency <= max_efficiency
        and direction_changes >= min_reversals
    )

    return SwingSignal(
        sample_count=len(window),
        window_seconds=lookback_seconds,
        up_swing=up_swing,
        down_swing=down_swing,
        net_move=net_move,
        efficiency=efficiency,
        direction_changes=direction_changes,
        is_oscillating=is_oscillating,
    )


def check_entry_momentum(
    slug: str,
    side: str,
    lookback_samples: int = 6,
    bounce_threshold: Decimal = Decimal("0.01"),
) -> Optional[bool]:
    """Check if the target side has bounced off its recent low.

    Returns True if bounced (enter), False if still falling (skip),
    None if insufficient data (caller bypasses check).
    """
    buf = _prob_history.get(slug)
    if not buf or len(buf) < lookback_samples:
        return None

    # Take the last N snapshots
    window = list(buf)[-lookback_samples:]

    # Extract the target side's ask prices
    if side == "up":
        prices = [s.up_ask for s in window]
    elif side == "down":
        prices = [s.down_ask for s in window]
    else:
        return None

    trough = min(prices)
    latest = prices[-1]
    bounce = latest - trough

    if bounce >= bounce_threshold:
        return True
    return False


def clear_market_history(slug: str) -> None:
    """Remove price history for a market that rotated out."""
    _prob_history.pop(slug, None)


def _count_direction_changes(prices: list[Decimal], threshold: Decimal) -> int:
    """Count direction reversals with smoothing.

    Only counts a reversal when cumulative move in the new direction
    exceeds `threshold`, filtering out noise.
    """
    if len(prices) < 3:
        return 0

    changes = 0
    last_anchor = prices[0]
    direction = 0  # 0 = undecided, 1 = up, -1 = down

    for price in prices[1:]:
        move = price - last_anchor
        if abs(move) < threshold:
            continue

        new_dir = 1 if move > 0 else -1
        if direction != 0 and new_dir != direction:
            changes += 1
            last_anchor = price
        elif direction == 0:
            pass  # first significant move — set direction
        direction = new_dir

    return changes
