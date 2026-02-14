"""Mean-reversion signal generation — pure functions, no state, no side effects.

Uses BTC deviation threshold to gate entry, then buys the cheapest side
(same logic as stop-hunt). When volume imbalance is available and conclusive,
uses it for direction instead of cheapest-ask.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum

from complete_set.binance_ws import CandleState
from complete_set.models import ZERO
from complete_set.volume_imbalance import VolumeState

log = logging.getLogger("cs.mean_reversion")


class MRDirection(Enum):
    BUY_UP = "BUY_UP"
    BUY_DOWN = "BUY_DOWN"
    SKIP = "SKIP"


def predict_direction_from_volume(
    volume: VolumeState | None,
    *,
    min_volume_btc: Decimal,
    imbalance_threshold: Decimal,
) -> MRDirection:
    """Use Binance aggTrade volume imbalance to predict BTC's next move.

    - Sell aggression (negative imbalance) → BTC dropping → UP token cheap → BUY_UP
    - Buy aggression (positive imbalance) → BTC rising → DOWN token cheap → BUY_DOWN
    - Returns SKIP if volume is stale, too low, or imbalance below threshold.
    """
    if volume is None or volume.is_stale:
        return MRDirection.SKIP

    if volume.short_volume_btc < min_volume_btc:
        return MRDirection.SKIP

    imb = volume.short_imbalance
    if abs(imb) < imbalance_threshold:
        return MRDirection.SKIP

    # Negative imbalance = sell aggression → BTC dropping → BUY UP
    if imb < ZERO:
        return MRDirection.BUY_UP
    # Positive imbalance = buy aggression → BTC rising → BUY DOWN
    return MRDirection.BUY_DOWN


@dataclass(frozen=True)
class MeanReversionSignal:
    deviation: Decimal         # signed deviation from open
    abs_deviation: Decimal     # |deviation|
    range_pct: Decimal         # intra-window range as fraction
    direction: MRDirection     # what to do
    reason: str                # human-readable reason


def evaluate_mean_reversion(
    candle: CandleState,
    seconds_to_end: int,
    up_ask: Decimal,
    down_ask: Decimal,
    *,
    deviation_threshold: Decimal,
    max_range_pct: Decimal,
    entry_window_sec: int,
    no_new_orders_sec: int,
    volume: VolumeState | None = None,
    volume_min_btc: Decimal = ZERO,
    volume_imbalance_threshold: Decimal = ZERO,
) -> MeanReversionSignal:
    """Evaluate whether to enter based on BTC mean reversion.

    Returns a signal with direction (BUY_UP, BUY_DOWN, or SKIP) and reason.
    When volume is provided and conclusive, uses it for direction;
    otherwise falls back to cheapest-ask.
    """
    dev = candle.deviation
    abs_dev = abs(dev)
    rng = candle.range_pct

    # Stale data — no recent WS update
    if candle.is_stale:
        return MeanReversionSignal(dev, abs_dev, rng, MRDirection.SKIP, "stale BTC data")

    # No open price set
    if candle.open_price == ZERO:
        return MeanReversionSignal(dev, abs_dev, rng, MRDirection.SKIP, "no open price")

    # Not in entry window
    if seconds_to_end > entry_window_sec:
        return MeanReversionSignal(dev, abs_dev, rng, MRDirection.SKIP, "outside entry window")

    # Pre-resolution buffer
    if seconds_to_end < no_new_orders_sec:
        return MeanReversionSignal(dev, abs_dev, rng, MRDirection.SKIP, "pre-resolution buffer")

    # Deviation below threshold
    if abs_dev < deviation_threshold:
        return MeanReversionSignal(dev, abs_dev, rng, MRDirection.SKIP,
                                   f"deviation {abs_dev:.5f} < {deviation_threshold}")

    # Volatility regime: skip trending candles
    if rng > max_range_pct:
        return MeanReversionSignal(dev, abs_dev, rng, MRDirection.SKIP,
                                   f"range {rng:.5f} > {max_range_pct} (trending)")

    # Direction: try volume first, fall back to cheapest-ask
    vol_dir = predict_direction_from_volume(
        volume, min_volume_btc=volume_min_btc,
        imbalance_threshold=volume_imbalance_threshold,
    )
    if vol_dir != MRDirection.SKIP:
        chosen = up_ask if vol_dir == MRDirection.BUY_UP else down_ask
        return MeanReversionSignal(
            dev, abs_dev, rng, vol_dir,
            f"deviation {dev:+.5f} → volume->{vol_dir.value} (imb={volume.short_imbalance:+.3f}, ask={chosen})",
        )

    # Fallback: buy whichever side is cheaper on the book
    direction = MRDirection.BUY_UP if up_ask <= down_ask else MRDirection.BUY_DOWN
    chosen = up_ask if direction == MRDirection.BUY_UP else down_ask

    return MeanReversionSignal(dev, abs_dev, rng, direction,
                               f"deviation {dev:+.5f} → {direction.value} (ask={chosen})")


# ── Stop-hunt signal (early entry, minutes 2-5) ──

@dataclass(frozen=True)
class StopHuntSignal:
    up_ask: Decimal
    down_ask: Decimal
    range_pct: Decimal
    direction: MRDirection     # BUY_UP / BUY_DOWN / SKIP
    reason: str


def evaluate_stop_hunt(
    candle: CandleState,
    up_ask: Decimal,
    down_ask: Decimal,
    seconds_to_end: int,
    *,
    max_first_leg: Decimal,
    max_range_pct: Decimal,
    sh_entry_start_sec: int,
    sh_entry_end_sec: int,
    no_new_orders_sec: int,
    volume: VolumeState | None = None,
    volume_min_btc: Decimal = ZERO,
    volume_imbalance_threshold: Decimal = ZERO,
) -> StopHuntSignal:
    """Evaluate whether to enter based on cheap token price in early candle window.

    No BTC deviation threshold — the Polymarket ask price IS the signal.
    Buy the cheapest side when ask < max_first_leg (~0.48).
    When volume is provided and conclusive, uses it for direction;
    otherwise falls back to cheapest-ask.
    """
    rng = candle.range_pct

    # Stale BTC data — need range filter
    if candle.is_stale:
        return StopHuntSignal(up_ask, down_ask, rng, MRDirection.SKIP, "stale BTC data")

    # No open price — can't compute range
    if candle.open_price == ZERO:
        return StopHuntSignal(up_ask, down_ask, rng, MRDirection.SKIP, "no open price")

    # Time window check: must be between sh_entry_end_sec and sh_entry_start_sec
    if seconds_to_end > sh_entry_start_sec:
        return StopHuntSignal(up_ask, down_ask, rng, MRDirection.SKIP, "before SH window")

    if seconds_to_end < sh_entry_end_sec:
        return StopHuntSignal(up_ask, down_ask, rng, MRDirection.SKIP, "past SH window")

    # Pre-resolution buffer
    if seconds_to_end < no_new_orders_sec:
        return StopHuntSignal(up_ask, down_ask, rng, MRDirection.SKIP, "pre-resolution buffer")

    # Range cap — skip trending candles
    if rng > max_range_pct:
        return StopHuntSignal(up_ask, down_ask, rng, MRDirection.SKIP,
                              f"range {rng:.5f} > {max_range_pct} (trending)")

    # Check if either side is cheap enough
    up_cheap = up_ask <= max_first_leg
    down_cheap = down_ask <= max_first_leg

    if not up_cheap and not down_cheap:
        return StopHuntSignal(up_ask, down_ask, rng, MRDirection.SKIP,
                              f"no cheap side (U={up_ask}, D={down_ask}, cap={max_first_leg:.3f})")

    # Direction: try volume first, fall back to cheapest-ask
    vol_dir = predict_direction_from_volume(
        volume, min_volume_btc=volume_min_btc,
        imbalance_threshold=volume_imbalance_threshold,
    )
    if vol_dir != MRDirection.SKIP:
        # Volume picked a direction — still require that side is cheap enough
        vol_cheap = (vol_dir == MRDirection.BUY_UP and up_cheap) or (vol_dir == MRDirection.BUY_DOWN and down_cheap)
        if vol_cheap:
            chosen = up_ask if vol_dir == MRDirection.BUY_UP else down_ask
            return StopHuntSignal(
                up_ask, down_ask, rng, vol_dir,
                f"volume->{vol_dir.value} ask={chosen} < cap={max_first_leg:.3f} (imb={volume.short_imbalance:+.3f})",
            )
        # Volume side not cheap — fall through to cheapest-ask

    # Fallback: pick the cheaper side (or the only qualifying one)
    if up_cheap and down_cheap:
        direction = MRDirection.BUY_UP if up_ask <= down_ask else MRDirection.BUY_DOWN
    elif up_cheap:
        direction = MRDirection.BUY_UP
    else:
        direction = MRDirection.BUY_DOWN

    chosen = up_ask if direction == MRDirection.BUY_UP else down_ask
    return StopHuntSignal(up_ask, down_ask, rng, direction,
                          f"{direction.value} ask={chosen} < cap={max_first_leg:.3f}")
