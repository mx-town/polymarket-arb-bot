"""
Signal Detectors for Trading Strategies

Implements the four strategy tiers from testing_plan:
1. Dutch Book Arbitrage (Zero Risk)
2. Lag Arbitrage (Low Risk)
3. Momentum/Directional (Medium Risk)
4. Flash Crash Contrarian (High Risk/Reward)

Each detector takes market state and returns a Signal if conditions are met.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from collections import deque

logger = logging.getLogger(__name__)


class SignalType(Enum):
    """Type of trading signal."""
    DUTCH_BOOK = "dutch_book"
    LAG_ARB_UP = "lag_arb_up"
    LAG_ARB_DOWN = "lag_arb_down"
    MOMENTUM_UP = "momentum_up"
    MOMENTUM_DOWN = "momentum_down"
    FLASH_CRASH_UP = "flash_crash_up"
    FLASH_CRASH_DOWN = "flash_crash_down"


@dataclass
class Signal:
    """A trading signal with full context."""
    signal_type: SignalType
    timestamp_ms: int

    # Prices at signal time
    up_price: float
    down_price: float
    combined_price: float

    # Edge calculation
    expected_edge: float
    confidence: float  # 0-1

    # Context
    deviation_pct: float
    time_remaining_sec: int
    session: str

    # Strategy-specific data
    metadata: dict = field(default_factory=dict)

    @property
    def is_profitable(self) -> bool:
        """Check if expected edge is positive."""
        return self.expected_edge > 0


@dataclass
class PricePoint:
    """Single price observation for tracking."""
    timestamp_ms: int
    price: float
    source: str  # "binance", "chainlink", etc.


class DutchBookDetector:
    """
    Tier 1: Dutch Book Arbitrage (Zero Risk)

    Detects when UP + DOWN < $1.00, guaranteeing profit regardless of outcome.

    Trigger: combined_ask < threshold (default $0.99)
    """

    def __init__(
        self,
        threshold: float = 0.99,
        min_profit_pct: float = 0.01  # 1% minimum profit
    ):
        self.threshold = threshold
        self.min_profit_pct = min_profit_pct

    def detect(
        self,
        up_executable_price: float,
        down_executable_price: float,
        timestamp_ms: int,
        time_remaining_sec: int = 0,
        session: str = "all"
    ) -> Optional[Signal]:
        """
        Check for Dutch Book opportunity.

        Args:
            up_executable_price: Actual execution price for UP (from book traversal)
            down_executable_price: Actual execution price for DOWN (from book traversal)
            timestamp_ms: Current timestamp
            time_remaining_sec: Seconds until resolution
            session: Trading session

        Returns:
            Signal if opportunity exists, None otherwise
        """
        combined = up_executable_price + down_executable_price

        if combined >= self.threshold:
            return None

        profit = 1.0 - combined
        profit_pct = profit / combined

        if profit_pct < self.min_profit_pct:
            return None

        return Signal(
            signal_type=SignalType.DUTCH_BOOK,
            timestamp_ms=timestamp_ms,
            up_price=up_executable_price,
            down_price=down_executable_price,
            combined_price=combined,
            expected_edge=profit,
            confidence=1.0,  # Zero risk
            deviation_pct=0.0,  # Not relevant for Dutch Book
            time_remaining_sec=time_remaining_sec,
            session=session,
            metadata={
                "profit_pct": profit_pct,
                "threshold": self.threshold
            }
        )


class LagArbDetector:
    """
    Tier 2: Lag Arbitrage (Low Risk)

    Exploits the 2-5 second delay between Binance spot moves and Chainlink updates.
    Buys the direction Binance indicates before Polymarket reprices.

    Trigger: |Binance - Chainlink| > threshold sustained for min_duration
    """

    def __init__(
        self,
        deviation_threshold: float = 0.001,  # 0.1%
        min_duration_ms: int = 500,
        max_combined_price: float = 0.995,
        min_edge_threshold: float = 0.03  # 3% minimum edge
    ):
        self.deviation_threshold = deviation_threshold
        self.min_duration_ms = min_duration_ms
        self.max_combined_price = max_combined_price
        self.min_edge_threshold = min_edge_threshold

        # Track lag state
        self.lag_start_time: Optional[int] = None
        self.lag_direction: Optional[str] = None

    def detect(
        self,
        binance_price: float,
        chainlink_price: float,
        open_price: float,
        up_price: float,
        down_price: float,
        timestamp_ms: int,
        time_remaining_sec: int,
        session: str = "all",
        model_prob_up: Optional[float] = None
    ) -> Optional[Signal]:
        """
        Check for Lag Arbitrage opportunity.

        Args:
            binance_price: Current Binance spot price
            chainlink_price: Current Chainlink oracle price
            open_price: Window open price (for deviation calc)
            up_price: Current UP token price
            down_price: Current DOWN token price
            timestamp_ms: Current timestamp
            time_remaining_sec: Seconds until resolution
            session: Trading session
            model_prob_up: Optional model probability (for edge calculation)

        Returns:
            Signal if opportunity exists, None otherwise
        """
        # Calculate deviations from open
        binance_deviation = (binance_price - open_price) / open_price
        chainlink_deviation = (chainlink_price - open_price) / open_price
        lag = binance_deviation - chainlink_deviation

        # Check if lag is significant
        if abs(lag) < self.deviation_threshold:
            self._reset_lag_state()
            return None

        # Determine direction
        current_direction = "up" if lag > 0 else "down"

        # Track lag duration
        if self.lag_direction != current_direction:
            self.lag_start_time = timestamp_ms
            self.lag_direction = current_direction

        lag_duration_ms = timestamp_ms - self.lag_start_time

        # Check if sustained long enough
        if lag_duration_ms < self.min_duration_ms:
            return None

        # Check combined price
        combined = up_price + down_price
        if combined > self.max_combined_price:
            return None

        # Calculate edge
        # If Binance moved up, we expect Chainlink to follow, so UP is more likely
        if model_prob_up is not None:
            if current_direction == "up":
                edge = model_prob_up - up_price
            else:
                edge = (1 - model_prob_up) - down_price
        else:
            # Estimate edge from lag size
            edge = abs(lag) * 2  # Rough heuristic

        if edge < self.min_edge_threshold:
            return None

        signal_type = SignalType.LAG_ARB_UP if current_direction == "up" else SignalType.LAG_ARB_DOWN

        return Signal(
            signal_type=signal_type,
            timestamp_ms=timestamp_ms,
            up_price=up_price,
            down_price=down_price,
            combined_price=combined,
            expected_edge=edge,
            confidence=0.7,  # Medium confidence
            deviation_pct=binance_deviation,
            time_remaining_sec=time_remaining_sec,
            session=session,
            metadata={
                "binance_deviation": binance_deviation,
                "chainlink_deviation": chainlink_deviation,
                "lag": lag,
                "lag_duration_ms": lag_duration_ms,
                "model_prob_up": model_prob_up
            }
        )

    def _reset_lag_state(self):
        """Reset lag tracking state."""
        self.lag_start_time = None
        self.lag_direction = None


class MomentumDetector:
    """
    Tier 3: Momentum/Directional (Medium Risk)

    Takes directional positions when velocity, acceleration, and order book
    imbalance all confirm a trend.

    Trigger:
    - velocity > threshold
    - acceleration > 0 (accelerating)
    - book_imbalance > threshold (directional pressure)
    - time_remaining > min_time (avoid late-market noise)
    """

    def __init__(
        self,
        velocity_threshold: float = 0.001,  # 0.1% in 5 seconds = 0.02%/sec
        min_book_imbalance: float = 0.3,
        min_time_remaining_sec: int = 60,
        require_positive_acceleration: bool = True,
        min_edge_threshold: float = 0.05  # 5% minimum edge
    ):
        self.velocity_threshold = velocity_threshold
        self.min_book_imbalance = min_book_imbalance
        self.min_time_remaining_sec = min_time_remaining_sec
        self.require_positive_acceleration = require_positive_acceleration
        self.min_edge_threshold = min_edge_threshold

    def detect(
        self,
        velocity: float,
        acceleration: float,
        book_imbalance: float,
        deviation_pct: float,
        up_price: float,
        down_price: float,
        timestamp_ms: int,
        time_remaining_sec: int,
        session: str = "all",
        model_prob_up: Optional[float] = None
    ) -> Optional[Signal]:
        """
        Check for Momentum opportunity.

        Args:
            velocity: Price velocity ($/sec or pct/sec)
            acceleration: Rate of velocity change
            book_imbalance: Order book imbalance [-1, 1]
            deviation_pct: Current deviation from open
            up_price: Current UP token price
            down_price: Current DOWN token price
            timestamp_ms: Current timestamp
            time_remaining_sec: Seconds until resolution
            session: Trading session
            model_prob_up: Optional model probability

        Returns:
            Signal if opportunity exists, None otherwise
        """
        # Check time remaining
        if time_remaining_sec < self.min_time_remaining_sec:
            return None

        # Check velocity threshold
        if abs(velocity) < self.velocity_threshold:
            return None

        # Check acceleration (if required)
        if self.require_positive_acceleration:
            # For up momentum, we want positive acceleration
            # For down momentum, we want negative acceleration
            if velocity > 0 and acceleration <= 0:
                return None
            if velocity < 0 and acceleration >= 0:
                return None

        # Check book imbalance alignment
        # Positive imbalance = buy pressure, should align with positive velocity
        if velocity > 0 and book_imbalance < self.min_book_imbalance:
            return None
        if velocity < 0 and book_imbalance > -self.min_book_imbalance:
            return None

        # Determine direction
        direction = "up" if velocity > 0 else "down"

        # Calculate edge
        combined = up_price + down_price
        if model_prob_up is not None:
            if direction == "up":
                edge = model_prob_up - up_price
            else:
                edge = (1 - model_prob_up) - down_price
        else:
            # Estimate edge from momentum strength
            edge = abs(velocity) * 10 + abs(book_imbalance) * 0.05

        if edge < self.min_edge_threshold:
            return None

        signal_type = SignalType.MOMENTUM_UP if direction == "up" else SignalType.MOMENTUM_DOWN

        return Signal(
            signal_type=signal_type,
            timestamp_ms=timestamp_ms,
            up_price=up_price,
            down_price=down_price,
            combined_price=combined,
            expected_edge=edge,
            confidence=0.5,  # Lower confidence for directional
            deviation_pct=deviation_pct,
            time_remaining_sec=time_remaining_sec,
            session=session,
            metadata={
                "velocity": velocity,
                "acceleration": acceleration,
                "book_imbalance": book_imbalance,
                "model_prob_up": model_prob_up
            }
        )


class FlashCrashDetector:
    """
    Tier 4: Flash Crash Contrarian (High Risk/Reward)

    Buys the crashed side when a flash crash occurs, expecting mean reversion.

    Trigger: >30% price drop in 10 seconds
    """

    def __init__(
        self,
        drop_threshold: float = 0.30,  # 30% drop
        window_sec: int = 10,
        max_history: int = 100
    ):
        self.drop_threshold = drop_threshold
        self.window_sec = window_sec
        self.window_ms = window_sec * 1000

        # Price history
        self.up_history: deque[PricePoint] = deque(maxlen=max_history)
        self.down_history: deque[PricePoint] = deque(maxlen=max_history)

    def update(
        self,
        up_price: float,
        down_price: float,
        timestamp_ms: int
    ):
        """Update price history."""
        self.up_history.append(PricePoint(timestamp_ms, up_price, "polymarket"))
        self.down_history.append(PricePoint(timestamp_ms, down_price, "polymarket"))

    def detect(
        self,
        up_price: float,
        down_price: float,
        timestamp_ms: int,
        time_remaining_sec: int,
        session: str = "all"
    ) -> Optional[Signal]:
        """
        Check for Flash Crash opportunity.

        Args:
            up_price: Current UP token price
            down_price: Current DOWN token price
            timestamp_ms: Current timestamp
            time_remaining_sec: Seconds until resolution
            session: Trading session

        Returns:
            Signal if flash crash detected, None otherwise
        """
        # Update history
        self.update(up_price, down_price, timestamp_ms)

        # Check UP side for crash
        up_crash = self._check_crash(self.up_history, timestamp_ms)
        if up_crash is not None:
            drop_pct, price_ago = up_crash
            return Signal(
                signal_type=SignalType.FLASH_CRASH_UP,
                timestamp_ms=timestamp_ms,
                up_price=up_price,
                down_price=down_price,
                combined_price=up_price + down_price,
                expected_edge=drop_pct * 0.5,  # Expect 50% reversion
                confidence=0.4,  # High risk
                deviation_pct=0.0,  # Not applicable
                time_remaining_sec=time_remaining_sec,
                session=session,
                metadata={
                    "side": "up",
                    "drop_pct": drop_pct,
                    "price_before": price_ago,
                    "price_now": up_price
                }
            )

        # Check DOWN side for crash
        down_crash = self._check_crash(self.down_history, timestamp_ms)
        if down_crash is not None:
            drop_pct, price_ago = down_crash
            return Signal(
                signal_type=SignalType.FLASH_CRASH_DOWN,
                timestamp_ms=timestamp_ms,
                up_price=up_price,
                down_price=down_price,
                combined_price=up_price + down_price,
                expected_edge=drop_pct * 0.5,
                confidence=0.4,
                deviation_pct=0.0,
                time_remaining_sec=time_remaining_sec,
                session=session,
                metadata={
                    "side": "down",
                    "drop_pct": drop_pct,
                    "price_before": price_ago,
                    "price_now": down_price
                }
            )

        return None

    def _check_crash(
        self,
        history: deque[PricePoint],
        current_time: int
    ) -> Optional[tuple[float, float]]:
        """
        Check if a crash occurred in the history.

        Returns: (drop_pct, price_ago) if crash detected, None otherwise
        """
        if len(history) < 2:
            return None

        current_price = history[-1].price

        # Find price from window_ms ago
        for point in history:
            if current_time - point.timestamp_ms >= self.window_ms:
                price_ago = point.price
                if price_ago > 0:
                    drop_pct = (price_ago - current_price) / price_ago
                    if drop_pct >= self.drop_threshold:
                        return (drop_pct, price_ago)
                break

        return None


class SignalArbiter:
    """
    Arbitrates between multiple signals, prioritizing by strategy tier.

    Priority (highest to lowest):
    1. Dutch Book (zero risk)
    2. Lag Arb (low risk)
    3. Momentum (medium risk)
    4. Flash Crash (high risk)
    """

    PRIORITY = {
        SignalType.DUTCH_BOOK: 1,
        SignalType.LAG_ARB_UP: 2,
        SignalType.LAG_ARB_DOWN: 2,
        SignalType.MOMENTUM_UP: 3,
        SignalType.MOMENTUM_DOWN: 3,
        SignalType.FLASH_CRASH_UP: 4,
        SignalType.FLASH_CRASH_DOWN: 4,
    }

    def __init__(
        self,
        dutch_book: Optional[DutchBookDetector] = None,
        lag_arb: Optional[LagArbDetector] = None,
        momentum: Optional[MomentumDetector] = None,
        flash_crash: Optional[FlashCrashDetector] = None
    ):
        self.dutch_book = dutch_book or DutchBookDetector()
        self.lag_arb = lag_arb or LagArbDetector()
        self.momentum = momentum or MomentumDetector()
        self.flash_crash = flash_crash or FlashCrashDetector()

    def get_best_signal(self, signals: list[Signal]) -> Optional[Signal]:
        """
        Get the highest priority signal from a list.

        Args:
            signals: List of detected signals

        Returns:
            Highest priority signal, or None if list is empty
        """
        if not signals:
            return None

        # Sort by priority (lowest number = highest priority)
        sorted_signals = sorted(
            signals,
            key=lambda s: (self.PRIORITY.get(s.signal_type, 999), -s.expected_edge)
        )

        return sorted_signals[0]

    def evaluate_all(
        self,
        # Market state
        up_executable_price: float,
        down_executable_price: float,
        # Lag arb inputs
        binance_price: Optional[float] = None,
        chainlink_price: Optional[float] = None,
        open_price: Optional[float] = None,
        # Momentum inputs
        velocity: Optional[float] = None,
        acceleration: Optional[float] = None,
        book_imbalance: Optional[float] = None,
        deviation_pct: float = 0.0,
        # Common
        timestamp_ms: int = 0,
        time_remaining_sec: int = 0,
        session: str = "all",
        model_prob_up: Optional[float] = None
    ) -> list[Signal]:
        """
        Evaluate all detectors and return all triggered signals.

        Returns:
            List of triggered signals, sorted by priority
        """
        signals = []

        # Dutch Book
        dutch_signal = self.dutch_book.detect(
            up_executable_price=up_executable_price,
            down_executable_price=down_executable_price,
            timestamp_ms=timestamp_ms,
            time_remaining_sec=time_remaining_sec,
            session=session
        )
        if dutch_signal:
            signals.append(dutch_signal)

        # Lag Arb
        if binance_price and chainlink_price and open_price:
            lag_signal = self.lag_arb.detect(
                binance_price=binance_price,
                chainlink_price=chainlink_price,
                open_price=open_price,
                up_price=up_executable_price,
                down_price=down_executable_price,
                timestamp_ms=timestamp_ms,
                time_remaining_sec=time_remaining_sec,
                session=session,
                model_prob_up=model_prob_up
            )
            if lag_signal:
                signals.append(lag_signal)

        # Momentum
        if velocity is not None and book_imbalance is not None:
            momentum_signal = self.momentum.detect(
                velocity=velocity,
                acceleration=acceleration or 0.0,
                book_imbalance=book_imbalance,
                deviation_pct=deviation_pct,
                up_price=up_executable_price,
                down_price=down_executable_price,
                timestamp_ms=timestamp_ms,
                time_remaining_sec=time_remaining_sec,
                session=session,
                model_prob_up=model_prob_up
            )
            if momentum_signal:
                signals.append(momentum_signal)

        # Flash Crash
        flash_signal = self.flash_crash.detect(
            up_price=up_executable_price,
            down_price=down_executable_price,
            timestamp_ms=timestamp_ms,
            time_remaining_sec=time_remaining_sec,
            session=session
        )
        if flash_signal:
            signals.append(flash_signal)

        # Sort by priority
        signals.sort(key=lambda s: self.PRIORITY.get(s.signal_type, 999))

        return signals
