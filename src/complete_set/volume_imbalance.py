"""Binance aggTrade WebSocket — rolling buy/sell volume imbalance for direction prediction.

Stream: wss://stream.binance.com:9443/ws/btcusdt@aggTrade
Accumulation: 1-second buckets in a deque(maxlen=120)
Trade parsing: aggTrade `m: true` = buyer is maker = sell aggression (taker sold)

Public API:
    start_volume_ws()  — async background task with auto-reconnect
    get_volume_state() — engine reads this each tick
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque
from dataclasses import dataclass
from decimal import Decimal

log = logging.getLogger("cs.volume_imbalance")

ZERO = Decimal("0")


@dataclass
class _Bucket:
    """One-second aggregation bucket."""
    timestamp: float = 0.0
    buy_vol: float = 0.0
    sell_vol: float = 0.0


@dataclass
class VolumeState:
    """Snapshot of rolling volume imbalance — read by engine each tick."""
    short_imbalance: Decimal = ZERO     # 30s window, range [-1, +1]
    medium_imbalance: Decimal = ZERO    # 120s window, range [-1, +1]
    short_volume_btc: Decimal = ZERO    # total taker volume in short window
    medium_volume_btc: Decimal = ZERO   # total taker volume in medium window
    last_update: float = 0.0           # epoch of last aggTrade

    @property
    def is_stale(self) -> bool:
        """True if no aggTrade in the last 5 seconds."""
        return time.time() - self.last_update > 5


# ── Module-level singleton ──
_buckets: deque[_Bucket] = deque(maxlen=120)
_current_bucket: _Bucket = _Bucket()
_volume_state: VolumeState = VolumeState()

# Configurable windows (set by engine before starting WS)
_short_window_sec: int = 30
_medium_window_sec: int = 120


def configure_windows(short_sec: int = 30, medium_sec: int = 120) -> None:
    """Set the rolling window durations. Call before start_volume_ws()."""
    global _short_window_sec, _medium_window_sec
    _short_window_sec = short_sec
    _medium_window_sec = medium_sec


def get_volume_state() -> VolumeState:
    """Return the current volume imbalance snapshot (read-only for callers)."""
    return _volume_state


def _flush_bucket() -> None:
    """Push current bucket to deque and start a new one."""
    global _current_bucket, _volume_state
    if _current_bucket.timestamp > 0:
        _buckets.append(_current_bucket)
    _current_bucket = _Bucket(timestamp=time.time())

    # Recompute imbalances from buckets
    now = time.time()
    short_buy = 0.0
    short_sell = 0.0
    med_buy = 0.0
    med_sell = 0.0

    for b in _buckets:
        age = now - b.timestamp
        if age <= _medium_window_sec:
            med_buy += b.buy_vol
            med_sell += b.sell_vol
            if age <= _short_window_sec:
                short_buy += b.buy_vol
                short_sell += b.sell_vol

    short_total = short_buy + short_sell
    med_total = med_buy + med_sell

    short_imb = Decimal(str((short_buy - short_sell) / short_total)) if short_total > 0 else ZERO
    med_imb = Decimal(str((med_buy - med_sell) / med_total)) if med_total > 0 else ZERO

    _volume_state = VolumeState(
        short_imbalance=short_imb,
        medium_imbalance=med_imb,
        short_volume_btc=Decimal(str(short_total)),
        medium_volume_btc=Decimal(str(med_total)),
        last_update=now,
    )


def _on_agg_trade(qty: float, is_buyer_maker: bool) -> None:
    """Process a single aggTrade — aggregate into current 1s bucket."""
    global _current_bucket
    now = time.time()

    # Roll to new bucket every second
    if now - _current_bucket.timestamp >= 1.0:
        _flush_bucket()

    # m: true = buyer is maker = taker SOLD (sell aggression)
    if is_buyer_maker:
        _current_bucket.sell_vol += qty
    else:
        _current_bucket.buy_vol += qty


async def start_volume_ws() -> None:
    """Spawn the aggTrade WebSocket loop with auto-reconnect. Runs forever."""
    while True:
        try:
            await _ws_loop()
        except asyncio.CancelledError:
            log.info("VOLUME_WS | cancelled")
            return
        except Exception as e:
            log.warning("VOLUME_WS | error: %s — reconnecting in 3s", e)
            await asyncio.sleep(3)


async def _ws_loop() -> None:
    """Single WebSocket connection loop — streams btcusdt@aggTrade."""
    import websockets

    url = "wss://stream.binance.com:9443/ws/btcusdt@aggTrade"
    log.info("VOLUME_WS | connecting to %s", url)

    async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
        log.info("VOLUME_WS | connected")
        async for msg_raw in ws:
            msg = json.loads(msg_raw)
            if msg.get("e") != "aggTrade":
                continue
            qty = float(msg["q"])
            is_buyer_maker = msg["m"]  # true = buyer is maker = sell aggression
            _on_agg_trade(qty, is_buyer_maker)
