"""
Price tracker for lag arbitrage signal detection.

KEY INSIGHT: Polymarket 1H markets resolve based on Binance 1H candle.
- Reference price = candle OPEN (not close)
- If close >= open → "Up" wins
- If close < open → "Down" wins

TRIGGER LOGIC (momentum-based):
- PRIMARY: Momentum crosses threshold → direction signal
- SECONDARY: Candle move confirms direction (not contradicting)
- Enter during lag window when Polymarket hasn't caught up
"""

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

import requests

from src.config import LagArbConfig
from src.data.binance_ws import AggTrade
from src.market.discovery import ASSET_TO_BINANCE_SYMBOL
from src.utils.logging import get_logger

logger = get_logger("price_tracker")

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"


class Direction(Enum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


@dataclass
class CandleState:
    """State of current Binance candle"""

    symbol: str
    interval: str  # "1h" or "15m"
    open_time: int  # Unix ms
    close_time: int  # Unix ms
    open_price: float  # THE reference price
    current_price: float  # Latest spot price
    high: float
    low: float
    fetched_at: datetime

    @property
    def move_from_open(self) -> float:
        """Percentage move from candle open"""
        if self.open_price == 0:
            return 0.0
        return (self.current_price - self.open_price) / self.open_price

    @property
    def time_remaining_sec(self) -> float:
        """Seconds until candle closes"""
        now_ms = datetime.now().timestamp() * 1000
        return max(0, (self.close_time - now_ms) / 1000)

    @property
    def is_stale(self) -> bool:
        """Check if candle data needs refresh"""
        # Refresh if past close time
        now_ms = datetime.now().timestamp() * 1000
        return now_ms > self.close_time


@dataclass
class DirectionSignal:
    """
    Signal indicating predicted market direction.

    Based on momentum (primary trigger) with candle move
    confirmation (secondary - ensures not contradicting).
    """

    symbol: str
    direction: Direction
    move_from_open: float  # % move from candle open (for confirmation)
    momentum: float  # Short-term momentum (PRIMARY trigger)
    confidence: float  # 0.0 to 1.0
    current_price: float
    candle_open: float
    timestamp: datetime
    momentum_threshold: float = 0.001  # Threshold used for trigger

    @property
    def is_significant(self) -> bool:
        """Check if signal is actionable (momentum-based)"""
        return (
            self.direction != Direction.NEUTRAL
            and abs(self.momentum) >= self.momentum_threshold  # Momentum crosses threshold
            and self.confidence >= 0.5
        )

    @property
    def expected_winner(self) -> str | None:
        """Which outcome should win at resolution?"""
        if self.direction == Direction.UP:
            return "UP"
        elif self.direction == Direction.DOWN:
            return "DOWN"
        return None


@dataclass
class PricePoint:
    """A single price observation"""

    price: float
    timestamp: datetime
    direction: str  # "buy" or "sell"
    quantity: float


def fetch_candle_open(symbol: str, interval: str = "1h") -> CandleState | None:
    """
    Fetch current candle from Binance Klines API.

    GET https://api.binance.com/api/v3/klines?symbol=BTCUSDT&interval=1h&limit=1

    Response: [[open_time, open, high, low, close, volume, close_time, ...]]
    """
    try:
        resp = requests.get(
            BINANCE_KLINES_URL,
            params={"symbol": symbol, "interval": interval, "limit": 1},
            timeout=5,
        )
        resp.raise_for_status()
        kline = resp.json()[0]

        return CandleState(
            symbol=symbol,
            interval=interval,
            open_time=int(kline[0]),
            close_time=int(kline[6]),
            open_price=float(kline[1]),  # THE reference price
            current_price=float(kline[4]),  # Current close (within candle)
            high=float(kline[2]),
            low=float(kline[3]),
            fetched_at=datetime.now(),
        )
    except Exception as e:
        logger.error("KLINES_ERROR", f"symbol={symbol} error={e}")
        return None


class SymbolTracker:
    """Tracks price and candle state for a single symbol"""

    def __init__(
        self,
        symbol: str,
        interval: str = "1h",
        momentum_window_sec: float = 10.0,
        move_threshold: float = 0.002,  # 0.2% from candle open (confirmation)
        momentum_trigger_threshold: float = 0.001,  # 0.1% momentum = PRIMARY trigger
    ):
        self.symbol = symbol
        self.interval = interval
        self.momentum_window_sec = momentum_window_sec
        self.move_threshold = move_threshold  # For candle confirmation
        self.momentum_trigger_threshold = momentum_trigger_threshold  # PRIMARY trigger

        # Candle state (fetched from Klines API)
        self.candle: CandleState | None = None

        # Rolling window of price points (for momentum)
        self.prices: deque[PricePoint] = deque()

        # Current spot price (from WebSocket)
        self.current_price: float = 0.0
        self.last_signal: DirectionSignal | None = None

    def refresh_candle(self) -> bool:
        """Fetch fresh candle data from Binance"""
        candle = fetch_candle_open(self.symbol, self.interval)
        if candle:
            self.candle = candle
            logger.info(
                "CANDLE_REFRESH",
                f"symbol={self.symbol} open={candle.open_price:.2f} "
                f"remaining={candle.time_remaining_sec:.0f}s",
            )
            return True
        return False

    def add_trade(self, trade: AggTrade):
        """Add a trade from WebSocket"""
        now = datetime.now()

        point = PricePoint(
            price=trade.price,
            timestamp=now,
            direction=trade.direction,
            quantity=trade.quantity,
        )

        self.prices.append(point)
        self.current_price = trade.price

        # Update candle's current price
        if self.candle:
            self.candle.current_price = trade.price

        # Prune old data
        self._prune_old_data(now)

    def _prune_old_data(self, now: datetime):
        """Remove data older than momentum window"""
        cutoff = now.timestamp() - self.momentum_window_sec

        while self.prices and self.prices[0].timestamp.timestamp() < cutoff:
            self.prices.popleft()

    def get_momentum(self) -> float:
        """Calculate short-term momentum (10-sec window)"""
        if len(self.prices) < 2:
            return 0.0

        oldest = self.prices[0].price
        newest = self.prices[-1].price

        if oldest == 0:
            return 0.0

        return (newest - oldest) / oldest

    def is_candle_confirming(self, direction: Direction) -> bool:
        """
        Check if candle move doesn't contradict momentum direction.

        For momentum-based triggers, we just need candle to not be
        strongly contradicting the momentum direction.
        """
        if not self.candle:
            return True  # No candle data, don't block

        move = self.candle.move_from_open

        if direction == Direction.UP:
            # Candle shouldn't be strongly down (contradicting UP momentum)
            return move >= -self.move_threshold
        elif direction == Direction.DOWN:
            # Candle shouldn't be strongly up (contradicting DOWN momentum)
            return move <= self.move_threshold

        return True

    def get_signal(self) -> DirectionSignal:
        """
        Calculate direction signal based on MOMENTUM (primary).

        Primary: momentum crosses threshold → direction signal
        Secondary: candle move confirms (not contradicting)
        """
        if not self.candle or self.current_price == 0:
            return DirectionSignal(
                symbol=self.symbol,
                direction=Direction.NEUTRAL,
                move_from_open=0.0,
                momentum=0.0,
                confidence=0.0,
                current_price=self.current_price,
                candle_open=0.0,
                timestamp=datetime.now(),
                momentum_threshold=self.momentum_trigger_threshold,
            )

        # Check if candle is stale (needs refresh)
        if self.candle.is_stale:
            self.refresh_candle()

        move = self.candle.move_from_open
        momentum = self.get_momentum()

        # PRIMARY: Determine direction from MOMENTUM
        if momentum >= self.momentum_trigger_threshold:
            direction = Direction.UP
        elif momentum <= -self.momentum_trigger_threshold:
            direction = Direction.DOWN
        else:
            direction = Direction.NEUTRAL

        # SECONDARY: Calculate confidence based on candle confirmation
        # Higher if candle move doesn't contradict momentum direction
        if direction != Direction.NEUTRAL:
            candle_confirms = self.is_candle_confirming(direction)
            confidence = 0.8 if candle_confirms else 0.5
        else:
            confidence = 0.0

        signal = DirectionSignal(
            symbol=self.symbol,
            direction=direction,
            move_from_open=move,
            momentum=momentum,
            confidence=confidence,
            current_price=self.current_price,
            candle_open=self.candle.open_price,
            timestamp=datetime.now(),
            momentum_threshold=self.momentum_trigger_threshold,
        )

        self.last_signal = signal
        return signal


class PriceTracker:
    """
    Tracks prices across multiple symbols for lag arbitrage.

    For 1H markets:
    - Fetches candle OPEN from Binance Klines API
    - Compares spot vs candle open to predict winner
    - Detects when Polymarket hasn't caught up (lag window)
    """

    def __init__(
        self,
        config: LagArbConfig,
        on_signal: Callable[[DirectionSignal], None] | None = None,
        assets: list[str] | None = None,
    ):
        self.config = config
        self.on_signal = on_signal

        self.trackers: dict[str, SymbolTracker] = {}

        # Map Polymarket assets to Binance symbols (dynamic from config)
        self.asset_to_symbol = self._build_asset_mapping(assets)

    def _build_asset_mapping(self, assets: list[str] | None) -> dict[str, str]:
        """Build asset-to-symbol mapping from config assets.

        Maps both full names and short names to Binance symbols:
        - "bitcoin" -> "BTCUSDT"
        - "btc" -> "BTCUSDT" (short name derived from first 3 chars or full name)
        """
        if assets is None:
            # Fallback to default BTC/ETH only
            return {"btc": "BTCUSDT", "eth": "ETHUSDT"}

        mapping = {}
        for asset in assets:
            if asset in ASSET_TO_BINANCE_SYMBOL:
                symbol = ASSET_TO_BINANCE_SYMBOL[asset]
                # Add full name mapping
                mapping[asset] = symbol
                # Add short name mapping (first 3-4 chars based on common abbreviations)
                short_names = {
                    "bitcoin": "btc", "ethereum": "eth", "solana": "sol",
                    "cardano": "ada", "dogecoin": "doge", "avalanche": "avax",
                    "polkadot": "dot", "chainlink": "link", "litecoin": "ltc",
                    "shiba": "shib", "aptos": "apt", "near": "near",
                    "xrp": "xrp", "bnb": "bnb",
                }
                short = short_names.get(asset, asset[:3])
                mapping[short] = symbol

        return mapping

    def initialize(self):
        """Initialize trackers and fetch initial candle data"""
        for _asset, symbol in self.asset_to_symbol.items():
            tracker = self._get_or_create_tracker(symbol)
            tracker.refresh_candle()

    def _get_or_create_tracker(self, symbol: str) -> SymbolTracker:
        """Get or create tracker for symbol"""
        if symbol not in self.trackers:
            self.trackers[symbol] = SymbolTracker(
                symbol=symbol,
                interval=self.config.candle_interval,  # Use 1H candles (0% fees)
                momentum_window_sec=self.config.spot_momentum_window_sec,
                move_threshold=self.config.spot_move_threshold_pct,  # For candle confirmation
                momentum_trigger_threshold=self.config.momentum_trigger_threshold_pct,  # PRIMARY trigger
            )
        return self.trackers[symbol]

    def refresh_candles(self):
        """Refresh all candle data (call at top of each hour)"""
        for tracker in self.trackers.values():
            tracker.refresh_candle()

    def on_trade(self, trade: AggTrade):
        """
        Handle incoming trade from Binance WebSocket.

        Updates tracker and emits signal if direction is clear.
        """
        tracker = self._get_or_create_tracker(trade.symbol)
        tracker.add_trade(trade)

        # Get current signal
        signal = tracker.get_signal()

        if signal.is_significant:
            logger.info(
                "DIRECTION_SIGNAL",
                f"symbol={signal.symbol} dir={signal.direction.value} "
                f"momentum={signal.momentum * 100:.3f}% "
                f"spot={signal.current_price:.2f} open={signal.candle_open:.2f}",
            )

            if self.on_signal:
                self.on_signal(signal)

    def get_signal(self, symbol: str) -> DirectionSignal | None:
        """Get current direction signal for a symbol"""
        tracker = self.trackers.get(symbol.upper())
        if tracker:
            return tracker.get_signal()
        return None

    def get_price(self, symbol: str) -> float | None:
        """Get current price for a symbol"""
        tracker = self.trackers.get(symbol.upper())
        if tracker:
            return tracker.current_price
        return None

    def get_candle_open(self, symbol: str) -> float | None:
        """Get candle open price for a symbol"""
        tracker = self.trackers.get(symbol.upper())
        if tracker and tracker.candle:
            return tracker.candle.open_price
        return None

    def get_asset_signal(self, asset: str) -> DirectionSignal | None:
        """
        Get direction signal for a Polymarket asset.

        Args:
            asset: "btc" or "eth"

        Returns:
            DirectionSignal if tracking, else None
        """
        symbol = self.asset_to_symbol.get(asset.lower())
        if symbol:
            return self.get_signal(symbol)
        return None


# Backwards compatibility alias
MomentumSignal = DirectionSignal
MomentumDirection = Direction
