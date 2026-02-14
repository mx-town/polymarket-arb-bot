"""Binance WebSocket client — streams BTC/USDT kline data for mean-reversion signals.

Module-level singleton `_candle_state` is written by the WS task and read by the engine.
Open price comes from Chainlink (same oracle Polymarket uses for settlement).
Current price comes from Binance WS (faster updates than Chainlink's 27s heartbeat).
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from decimal import Decimal

import requests

log = logging.getLogger("cs.binance_ws")

ZERO = Decimal("0")

# Last significant BTC move — read by market_data to compute real reprice lag
_last_btc_move_ts: float = 0.0   # epoch when BTC moved significantly
_last_btc_move_dir: int = 0      # +1 = up, -1 = down


def get_last_btc_move() -> tuple[float, int]:
    """Return (timestamp, direction) of the last significant BTC move."""
    return _last_btc_move_ts, _last_btc_move_dir


@dataclass
class CandleState:
    """Snapshot of the current BTC candle relative to the Polymarket window."""

    open_price: Decimal = ZERO       # BTC price at Polymarket window start
    current_price: Decimal = ZERO    # latest BTC price from WS
    high: Decimal = ZERO             # intra-window high
    low: Decimal = ZERO              # intra-window low
    last_update: float = 0.0         # epoch of last WS message
    _market_window_start: float = 0.0  # epoch of Polymarket window start

    @property
    def deviation(self) -> Decimal:
        """Signed deviation from open: positive = BTC up, negative = BTC down."""
        if self.open_price == ZERO:
            return ZERO
        return (self.current_price - self.open_price) / self.open_price

    @property
    def range_pct(self) -> Decimal:
        """Intra-window range as fraction of open price."""
        if self.open_price == ZERO:
            return ZERO
        return (self.high - self.low) / self.open_price

    @property
    def is_stale(self) -> bool:
        """True if no WS update in the last 10 seconds."""
        return time.time() - self.last_update > 10


# Module-level singleton — engine reads, WS writes
_candle_state = CandleState()
_lock = asyncio.Lock()


def get_candle_state() -> CandleState:
    """Return a snapshot of the current candle state (read-only for callers)."""
    return _candle_state


def set_market_window(start_epoch: float, rpc_url: str = "") -> None:
    """Called when a new Polymarket window starts — capture BTC open price.

    Uses Chainlink oracle (same as Polymarket) for the reference open price.
    Falls back to Binance current_price or REST if Chainlink unavailable.
    """
    global _candle_state

    now = time.time()
    # Don't re-set if we already have this window
    if _candle_state._market_window_start == start_epoch:
        return

    # Primary: Chainlink oracle (matches Polymarket's "Price to beat")
    from complete_set.chainlink import fetch_chainlink_btc_price
    open_price = fetch_chainlink_btc_price(rpc_url)
    source = "chainlink"

    # Fallback: Binance current price or REST
    if open_price == ZERO:
        open_price = _candle_state.current_price if _candle_state.current_price > ZERO else _fetch_btc_price()
        source = "binance"

    _candle_state = CandleState(
        open_price=open_price,
        current_price=_candle_state.current_price if _candle_state.current_price > ZERO else open_price,
        high=open_price,
        low=open_price,
        last_update=now,
        _market_window_start=start_epoch,
    )
    log.info("MR_WINDOW_SET │ open=%s source=%s window_start=%d", open_price, source, int(start_epoch))


def _fetch_btc_price() -> Decimal:
    """REST fallback: fetch current BTC/USDT price from Binance."""
    try:
        resp = requests.get(
            "https://api.binance.com/api/v3/ticker/price",
            params={"symbol": "BTCUSDT"},
            timeout=5,
        )
        resp.raise_for_status()
        return Decimal(resp.json()["price"])
    except Exception as e:
        log.warning("BINANCE_REST_FAIL │ %s", e)
        return ZERO


def _fetch_btc_open_at(epoch: float) -> Decimal:
    """Fetch the BTC price at a specific epoch via Binance klines REST.

    Used for mid-candle bot starts to get the open price at the Polymarket window start.
    """
    try:
        start_ms = int(epoch * 1000)
        resp = requests.get(
            "https://api.binance.com/api/v3/klines",
            params={
                "symbol": "BTCUSDT",
                "interval": "1m",
                "startTime": start_ms,
                "limit": 1,
            },
            timeout=5,
        )
        resp.raise_for_status()
        klines = resp.json()
        if klines:
            return Decimal(klines[0][1])  # open price of the 1m candle
    except Exception as e:
        log.warning("BINANCE_REST_KLINE_FAIL │ %s", e)
    return _fetch_btc_price()  # fallback to current price


async def start_binance_ws() -> None:
    """Spawn the Binance WebSocket loop with auto-reconnect. Runs forever."""
    while True:
        try:
            await _ws_loop()
        except asyncio.CancelledError:
            log.info("BINANCE_WS │ cancelled")
            return
        except Exception as e:
            log.warning("BINANCE_WS │ error: %s — reconnecting in 3s", e)
            await asyncio.sleep(3)


async def _ws_loop() -> None:
    """Single WebSocket connection loop — streams btcusdt@kline_1m."""
    import websockets

    url = "wss://stream.binance.com:9443/ws/btcusdt@kline_1m"
    log.info("BINANCE_WS │ connecting to %s", url)

    async with websockets.connect(url, ping_interval=20, ping_timeout=10) as ws:
        log.info("BINANCE_WS │ connected")
        async for msg_raw in ws:
            import json
            msg = json.loads(msg_raw)
            if msg.get("e") != "kline":
                continue
            kline = msg["k"]
            price = Decimal(kline["c"])  # close = current price
            _update_candle(price)


def _update_candle(price: Decimal) -> None:
    """Update the module-level candle state with a new price tick."""
    global _candle_state
    now = time.time()

    cs = _candle_state
    if cs.open_price == ZERO:
        # No window set yet — just track current price
        _candle_state = CandleState(
            open_price=cs.open_price,
            current_price=price,
            high=max(cs.high, price) if cs.high > ZERO else price,
            low=min(cs.low, price) if cs.low > ZERO else price,
            last_update=now,
            _market_window_start=cs._market_window_start,
        )
        return

    _candle_state = CandleState(
        open_price=cs.open_price,
        current_price=price,
        high=max(cs.high, price),
        low=min(cs.low, price) if cs.low > ZERO else price,
        last_update=now,
        _market_window_start=cs._market_window_start,
    )
    if price != cs.current_price:
        global _last_btc_move_ts, _last_btc_move_dir
        delta = price - cs.current_price
        log.debug("BTC_TICK │ %.6f │ %s → %s │ Δ=%s", now, cs.current_price, price, delta)
        if abs(delta) > 1:
            _last_btc_move_ts = now
            _last_btc_move_dir = 1 if delta > 0 else -1
