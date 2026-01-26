"""
Price tracker for momentum detection.

Maintains rolling windows of spot prices and detects significant moves
that predict Polymarket lag arbitrage opportunities.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, Dict, Callable
from enum import Enum

from src.data.binance_ws import AggTrade
from src.config import LagArbConfig
from src.utils.logging import get_logger

logger = get_logger("price_tracker")


class MomentumDirection(Enum):
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


@dataclass
class MomentumSignal:
    """Signal indicating significant price momentum"""

    symbol: str
    direction: MomentumDirection
    magnitude: float  # Percentage change (0.01 = 1%)
    confidence: float  # 0.0 to 1.0
    current_price: float
    window_start_price: float
    timestamp: datetime

    @property
    def is_significant(self) -> bool:
        """Check if signal is significant enough to act on"""
        return self.direction != MomentumDirection.NEUTRAL and self.confidence >= 0.5


@dataclass
class PricePoint:
    """A single price observation"""

    price: float
    timestamp: datetime
    direction: str  # "buy" or "sell"
    quantity: float


class SymbolTracker:
    """Tracks price momentum for a single symbol"""

    def __init__(
        self,
        symbol: str,
        window_seconds: float = 10.0,
        move_threshold: float = 0.001,  # 0.1%
    ):
        self.symbol = symbol
        self.window_seconds = window_seconds
        self.move_threshold = move_threshold

        # Rolling window of price points
        self.prices: deque[PricePoint] = deque()

        # Current state
        self.current_price: float = 0.0
        self.last_signal: Optional[MomentumSignal] = None

    def add_trade(self, trade: AggTrade):
        """Add a trade to the tracker"""
        now = datetime.now()

        point = PricePoint(
            price=trade.price,
            timestamp=now,
            direction=trade.direction,
            quantity=trade.quantity,
        )

        self.prices.append(point)
        self.current_price = trade.price

        # Prune old data
        self._prune_old_data(now)

    def _prune_old_data(self, now: datetime):
        """Remove data older than window"""
        cutoff = now.timestamp() - self.window_seconds

        while self.prices and self.prices[0].timestamp.timestamp() < cutoff:
            self.prices.popleft()

    def get_momentum(self) -> MomentumSignal:
        """
        Calculate current momentum.

        Returns a MomentumSignal with:
        - direction: UP/DOWN/NEUTRAL
        - magnitude: absolute percentage change
        - confidence: based on trade direction consistency
        """
        if len(self.prices) < 2:
            return MomentumSignal(
                symbol=self.symbol,
                direction=MomentumDirection.NEUTRAL,
                magnitude=0.0,
                confidence=0.0,
                current_price=self.current_price,
                window_start_price=self.current_price,
                timestamp=datetime.now(),
            )

        # Window start and end prices
        start_price = self.prices[0].price
        end_price = self.prices[-1].price

        if start_price == 0:
            return MomentumSignal(
                symbol=self.symbol,
                direction=MomentumDirection.NEUTRAL,
                magnitude=0.0,
                confidence=0.0,
                current_price=end_price,
                window_start_price=start_price,
                timestamp=datetime.now(),
            )

        # Calculate change
        change = (end_price - start_price) / start_price
        magnitude = abs(change)

        # Determine direction
        if change >= self.move_threshold:
            direction = MomentumDirection.UP
        elif change <= -self.move_threshold:
            direction = MomentumDirection.DOWN
        else:
            direction = MomentumDirection.NEUTRAL

        # Calculate confidence based on trade direction consistency
        buy_volume = sum(p.quantity for p in self.prices if p.direction == "buy")
        sell_volume = sum(p.quantity for p in self.prices if p.direction == "sell")
        total_volume = buy_volume + sell_volume

        if total_volume > 0:
            if direction == MomentumDirection.UP:
                confidence = buy_volume / total_volume
            elif direction == MomentumDirection.DOWN:
                confidence = sell_volume / total_volume
            else:
                confidence = 0.5
        else:
            confidence = 0.5

        signal = MomentumSignal(
            symbol=self.symbol,
            direction=direction,
            magnitude=magnitude,
            confidence=confidence,
            current_price=end_price,
            window_start_price=start_price,
            timestamp=datetime.now(),
        )

        self.last_signal = signal
        return signal


class PriceTracker:
    """
    Tracks prices across multiple symbols and detects momentum.

    Used for lag arbitrage: when Binance moves sharply, Polymarket
    prices lag by 1-5 seconds, creating arbitrage windows.
    """

    def __init__(
        self,
        config: LagArbConfig,
        on_signal: Optional[Callable[[MomentumSignal], None]] = None,
    ):
        self.config = config
        self.on_signal = on_signal

        self.trackers: Dict[str, SymbolTracker] = {}

        # Map Polymarket assets to Binance symbols
        self.asset_to_symbol = {
            "btc": "BTCUSDT",
            "eth": "ETHUSDT",
        }

    def _get_or_create_tracker(self, symbol: str) -> SymbolTracker:
        """Get or create tracker for symbol"""
        if symbol not in self.trackers:
            self.trackers[symbol] = SymbolTracker(
                symbol=symbol,
                window_seconds=self.config.spot_momentum_window_sec,
                move_threshold=self.config.spot_move_threshold_pct,
            )
        return self.trackers[symbol]

    def on_trade(self, trade: AggTrade):
        """
        Handle incoming trade from Binance.

        Updates tracker and emits signal if significant momentum detected.
        """
        tracker = self._get_or_create_tracker(trade.symbol)
        tracker.add_trade(trade)

        # Check for significant momentum
        signal = tracker.get_momentum()

        if signal.is_significant:
            logger.info(
                "MOMENTUM",
                f"symbol={signal.symbol} dir={signal.direction.value} "
                f"mag={signal.magnitude:.4f} conf={signal.confidence:.2f}",
            )

            if self.on_signal:
                self.on_signal(signal)

    def get_momentum(self, symbol: str) -> Optional[MomentumSignal]:
        """Get current momentum signal for a symbol"""
        tracker = self.trackers.get(symbol.upper())
        if tracker:
            return tracker.get_momentum()
        return None

    def get_price(self, symbol: str) -> Optional[float]:
        """Get current price for a symbol"""
        tracker = self.trackers.get(symbol.upper())
        if tracker:
            return tracker.current_price
        return None

    def get_asset_momentum(self, asset: str) -> Optional[MomentumSignal]:
        """
        Get momentum for a Polymarket asset.

        Args:
            asset: "btc" or "eth"

        Returns:
            MomentumSignal if tracking, else None
        """
        symbol = self.asset_to_symbol.get(asset.lower())
        if symbol:
            return self.get_momentum(symbol)
        return None
