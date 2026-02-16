"""BTC and ETH price tracker via Binance public API.

Polls spot prices at each tick, stores a rolling window of prices,
and computes volatility metrics (pct change, rolling vol, range).
"""

from __future__ import annotations

import logging
import time
from collections import deque
from statistics import stdev

import requests

from observer.models import BtcPriceSnapshot

log = logging.getLogger("obs.btc_price")

BINANCE_TICKER_URL = "https://api.binance.com/api/v3/ticker/price"
REQUEST_TIMEOUT = 5

# Default 360 ticks = 1 hour at 10s intervals
DEFAULT_MAX_LEN = 360

# Tick counts for metric windows
TICKS_1M = 6    # 6 ticks * 10s = 60s
TICKS_5M = 30   # 30 ticks * 10s = 300s


class BtcPriceTracker:
    """Polls Binance for BTC/ETH spot prices and computes volatility metrics."""

    def __init__(self, max_len: int = DEFAULT_MAX_LEN):
        self._btc_prices: deque[float] = deque(maxlen=max_len)
        self._eth_prices: deque[float] = deque(maxlen=max_len)

    def _fetch_price(self, symbol: str) -> float:
        """Fetch current spot price from Binance."""
        resp = requests.get(
            BINANCE_TICKER_URL,
            params={"symbol": symbol},
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return float(resp.json()["price"])

    def _pct_change(self, prices: deque[float], ticks: int) -> float:
        """Percent change over the last N ticks. Returns 0.0 if insufficient data."""
        if len(prices) < ticks + 1:
            return 0.0
        old = prices[-(ticks + 1)]
        cur = prices[-1]
        if old == 0:
            return 0.0
        return (cur - old) / old * 100.0

    def _rolling_vol(self, prices: deque[float], ticks: int) -> float:
        """Standard deviation of 1-tick percent returns over the last N ticks."""
        if len(prices) < ticks + 1:
            return 0.0
        window = list(prices)[-ticks - 1:]
        returns = []
        for i in range(1, len(window)):
            if window[i - 1] != 0:
                returns.append((window[i] - window[i - 1]) / window[i - 1] * 100.0)
        if len(returns) < 2:
            return 0.0
        return stdev(returns)

    def _range_pct(self, prices: deque[float], ticks: int) -> float:
        """(max - min) / mean over the last N ticks."""
        if len(prices) < ticks:
            return 0.0
        window = list(prices)[-ticks:]
        mn = min(window)
        mx = max(window)
        mean = sum(window) / len(window)
        if mean == 0:
            return 0.0
        return (mx - mn) / mean * 100.0

    def _build_snapshot(self, btc: float, eth: float) -> BtcPriceSnapshot:
        """Append prices and compute all metrics."""
        self._btc_prices.append(btc)
        self._eth_prices.append(eth)

        return BtcPriceSnapshot(
            timestamp=time.time(),
            btc_price=btc,
            eth_price=eth,
            btc_pct_change_1m=self._pct_change(self._btc_prices, TICKS_1M),
            btc_pct_change_5m=self._pct_change(self._btc_prices, TICKS_5M),
            btc_rolling_vol_5m=self._rolling_vol(self._btc_prices, TICKS_5M),
            btc_range_pct_5m=self._range_pct(self._btc_prices, TICKS_5M),
            eth_pct_change_1m=self._pct_change(self._eth_prices, TICKS_1M),
            eth_pct_change_5m=self._pct_change(self._eth_prices, TICKS_5M),
        )

    def snapshot(self) -> BtcPriceSnapshot:
        """Initial fetch — logs startup info."""
        btc = self._fetch_price("BTCUSDT")
        eth = self._fetch_price("ETHUSDT")
        snap = self._build_snapshot(btc, eth)
        log.info(
            "INIT │ btc=$%.2f eth=$%.2f │ window=%d/%d",
            btc, eth, len(self._btc_prices), self._btc_prices.maxlen,
        )
        return snap

    def poll(self) -> BtcPriceSnapshot:
        """Tick fetch — logs price and volatility metrics."""
        btc = self._fetch_price("BTCUSDT")
        eth = self._fetch_price("ETHUSDT")
        snap = self._build_snapshot(btc, eth)
        log.debug(
            "TICK │ btc=$%.2f eth=$%.2f │ btc_1m=%.3f%% btc_5m=%.3f%% vol_5m=%.4f%% range_5m=%.3f%%",
            snap.btc_price, snap.eth_price,
            snap.btc_pct_change_1m, snap.btc_pct_change_5m,
            snap.btc_rolling_vol_5m, snap.btc_range_pct_5m,
        )
        return snap
