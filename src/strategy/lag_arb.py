"""
Lag arbitrage strategy (Phase 2) - Momentum-based trigger.

KEY INSIGHT: Polymarket 1H markets resolve based on Binance 1H candle.
- Reference price = candle OPEN (not close)
- If close >= open → "Up" wins at resolution
- If close < open → "Down" wins at resolution

Strategy (momentum-based):
1. PRIMARY: Detect momentum in spot price (10-sec rolling window)
2. SECONDARY: Confirm candle move doesn't contradict
3. If momentum > threshold → direction signal
4. If Polymarket hasn't repriced (combined_ask < $1.00), enter
5. Buy BOTH sides during the lag window

Exit Strategy (aggressive):
1. Exit if max hold time exceeded (force exit after 5 min)
2. Exit if one side pumps >= threshold (3% default)
3. Exit if combined_bid > entry_cost (any profit)
4. Exit on price normalization (spread < 0.5%)
5. Otherwise hold to resolution

Why this works:
- Polymarket lags Binance by 1-5 seconds
- Momentum catches price moves EARLY (before candle cross)
- We enter during the lag, exit on pump (capture repricing)
- Even if wrong about direction, profit if combined < $1.00
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime

from src.config import LagArbConfig, TradingConfig
from src.data.price_tracker import Direction, DirectionSignal
from src.market.state import MarketState
from src.strategy.signals import (
    ArbOpportunity,
    ExitReason,
    Signal,
    SignalDetector,
    SignalType,
)
from src.utils.logging import get_logger

# Type alias for event callback
EventCallback = Callable[[str, str, dict], None]

logger = get_logger("lag_arb")


@dataclass
class LagWindow:
    """
    Tracks an active lag arbitrage window.

    Created when spot price crosses above/below candle open,
    indicating which side SHOULD win at resolution.
    """

    symbol: str
    expected_winner: str  # "UP" or "DOWN"
    direction: Direction
    start_time: datetime
    signal: DirectionSignal
    expected_duration_ms: int
    entry_made: bool = False

    @property
    def is_expired(self) -> bool:
        """Check if lag window has expired"""
        elapsed_ms = (datetime.now() - self.start_time).total_seconds() * 1000
        return elapsed_ms > self.expected_duration_ms

    @property
    def remaining_ms(self) -> float:
        """Milliseconds remaining in window"""
        elapsed_ms = (datetime.now() - self.start_time).total_seconds() * 1000
        return max(0, self.expected_duration_ms - elapsed_ms)


class LagArbStrategy(SignalDetector):
    """
    Lag arbitrage strategy using Binance candle comparison.

    Primary signal: spot vs candle_open → predicts resolution winner
    Secondary signal: momentum → confirms not reversing

    More aggressive than conservative strategy:
    - Enters during predicted lag windows
    - Accepts entries up to combined_ask = $1.00 (0% fees on 1H)
    - Exits on price normalization (don't wait for resolution)
    """

    def __init__(
        self,
        trading_config: TradingConfig,
        lag_config: LagArbConfig,
        on_event: EventCallback | None = None,
    ):
        self.trading = trading_config
        self.config = lag_config
        self.on_event = on_event

        # Active lag windows by symbol
        self.lag_windows: dict[str, LagWindow] = {}

        # Map market slugs to Binance symbols
        self.market_to_symbol = {
            "btc": "BTCUSDT",
            "eth": "ETHUSDT",
        }

    def _emit_event(self, event_type: str, symbol: str, details: dict):
        """Emit an event through the callback if registered"""
        if self.on_event:
            self.on_event(event_type, symbol, details)

    def on_direction_signal(self, signal: DirectionSignal):
        """
        Handle direction signal from price tracker.

        Opens a lag window when spot crosses significantly above/below candle open.
        """
        if not signal.is_significant:
            return

        expected_winner = signal.expected_winner
        if not expected_winner:
            return

        # Create or update lag window
        window = LagWindow(
            symbol=signal.symbol,
            expected_winner=expected_winner,
            direction=signal.direction,
            start_time=datetime.now(),
            signal=signal,
            expected_duration_ms=self.config.max_lag_window_ms,
        )

        self.lag_windows[signal.symbol] = window

        logger.info(
            "LAG_WINDOW_OPEN",
            f"symbol={signal.symbol} winner={expected_winner} "
            f"momentum={signal.momentum * 100:.3f}% "
            f"spot={signal.current_price:.2f} open={signal.candle_open:.2f} "
            f"window={self.config.max_lag_window_ms}ms",
        )

        # Emit event for dashboard
        self._emit_event(
            "LAG_WINDOW_OPEN",
            signal.symbol,
            {
                "expected_winner": expected_winner,
                "momentum": signal.momentum,
                "spot_price": signal.current_price,
                "candle_open": signal.candle_open,
                "window_duration_ms": self.config.max_lag_window_ms,
            },
        )

    # Backwards compatibility
    def on_momentum_signal(self, signal: DirectionSignal):
        """Alias for on_direction_signal (backwards compatibility)"""
        self.on_direction_signal(signal)

    def _get_symbol_for_market(self, market: MarketState) -> str | None:
        """Get Binance symbol for a market"""
        slug = market.slug.lower()
        for asset, symbol in self.market_to_symbol.items():
            if asset in slug:
                return symbol
        return None

    def _get_active_window(self, symbol: str) -> LagWindow | None:
        """Get active (non-expired) lag window for symbol"""
        window = self.lag_windows.get(symbol)
        if window and not window.is_expired:
            return window

        # Clean up expired window
        if window:
            logger.info(
                "LAG_WINDOW_EXPIRED",
                f"symbol={symbol} winner={window.expected_winner} entry_made={window.entry_made}",
            )
            # Emit event for dashboard
            self._emit_event(
                "LAG_WINDOW_EXPIRED",
                symbol,
                {
                    "expected_winner": window.expected_winner,
                    "entry_made": window.entry_made,
                },
            )
            del self.lag_windows[symbol]
        return None

    def check_entry(self, market: MarketState) -> Signal | None:
        """
        Check if market has lag arbitrage entry opportunity.

        Entry conditions:
        1. Active lag window (spot crossed above/below candle open)
        2. combined_ask < max_combined_price (up to $1.00 for 0% fee markets)
        3. Fresh book data (not stale)
        4. Enough time to resolution

        We're buying BOTH sides, so direction doesn't affect sizing.
        We profit as long as combined < $1.00 at resolution.
        """
        if not market.is_valid:
            return None

        # Get corresponding Binance symbol
        symbol = self._get_symbol_for_market(market)
        if not symbol:
            return None

        # Check for active lag window
        window = self._get_active_window(symbol)
        if not window:
            return None

        combined = market.combined_ask

        # Lag arb uses aggressive threshold (up to $1.00 for 0% fee 1H markets)
        if combined >= self.config.max_combined_price:
            logger.info(
                "LAG_ENTRY_SKIP",
                f"market={market.slug} combined={combined:.4f} "
                f"max={self.config.max_combined_price:.4f} "
                f"winner={window.expected_winner} window_remaining={window.remaining_ms:.0f}ms",
            )
            # Emit event for dashboard
            self._emit_event(
                "ENTRY_SKIP",
                market.slug,
                {
                    "reason": "combined_price_too_high",
                    "combined": combined,
                    "max_combined": self.config.max_combined_price,
                    "expected_winner": window.expected_winner,
                    "window_remaining_ms": window.remaining_ms,
                },
            )
            return None

        # Calculate profits
        # For 1H markets: 0% fees
        # For 15m markets: ~3% fees at 50/50, but we're not targeting those now
        gross_profit = 1.0 - combined
        estimated_fees = combined * self.trading.fee_rate  # 0 for 1H markets
        net_profit = gross_profit - estimated_fees

        # Accept any positive net profit during lag window
        if net_profit <= 0:
            return None

        # Create opportunity
        opp = ArbOpportunity.from_market(market, self.trading.fee_rate)
        opp.confidence = window.signal.confidence

        logger.info(
            "LAG_ENTRY_SIGNAL",
            f"market={market.slug} combined={combined:.4f} "
            f"gross={gross_profit:.4f} net={net_profit:.4f} "
            f"expected_winner={window.expected_winner} "
            f"move_from_open={window.signal.move_from_open:.4f} "
            f"window_remaining_ms={window.remaining_ms:.0f}",
        )

        window.entry_made = True

        return Signal(
            signal_type=SignalType.ENTRY,
            market_id=market.market_id,
            opportunity=opp,
            confidence=window.signal.confidence,
        )

    def check_exit(
        self,
        market: MarketState,
        entry_up_price: float,
        entry_down_price: float,
        entry_time: datetime | None = None,
    ) -> Signal | None:
        """
        Check if position should exit.

        Lag arb exits aggressively with multiple triggers:
        1. Exit if max hold time exceeded (force exit)
        2. Exit if one side pumps >= threshold (3% default)
        3. Exit if combined_bid > entry_cost (any profit available)
        4. Exit on price normalization (spread < threshold)
        5. Otherwise hold to resolution (guaranteed profit if entry < $1.00)
        """
        if not market.is_valid:
            return None

        entry_cost = entry_up_price + entry_down_price

        # 1. Check max hold time (force exit after N seconds)
        if entry_time:
            hold_duration = (datetime.now() - entry_time).total_seconds()
            if hold_duration >= self.config.max_hold_time_sec:
                logger.info(
                    "LAG_EXIT_MAX_HOLD",
                    f"market={market.slug} duration={hold_duration:.0f}s "
                    f"max={self.config.max_hold_time_sec}s",
                )
                return Signal(
                    signal_type=SignalType.EXIT,
                    market_id=market.market_id,
                    exit_reason=ExitReason.EARLY_EXIT,
                )

        # 2. Check single-side pump (UP side)
        if entry_up_price > 0:
            up_change = (market.up_best_bid - entry_up_price) / entry_up_price
            if up_change >= self.config.pump_exit_threshold_pct:
                logger.info(
                    "LAG_EXIT_PUMP_UP",
                    f"market={market.slug} up_change={up_change:.2%} "
                    f"threshold={self.config.pump_exit_threshold_pct:.2%} "
                    f"entry={entry_up_price:.4f} current={market.up_best_bid:.4f}",
                )
                return Signal(
                    signal_type=SignalType.EXIT,
                    market_id=market.market_id,
                    exit_reason=ExitReason.PUMP_EXIT,
                )

        # 3. Check single-side pump (DOWN side)
        if entry_down_price > 0:
            down_change = (market.down_best_bid - entry_down_price) / entry_down_price
            if down_change >= self.config.pump_exit_threshold_pct:
                logger.info(
                    "LAG_EXIT_PUMP_DOWN",
                    f"market={market.slug} down_change={down_change:.2%} "
                    f"threshold={self.config.pump_exit_threshold_pct:.2%} "
                    f"entry={entry_down_price:.4f} current={market.down_best_bid:.4f}",
                )
                return Signal(
                    signal_type=SignalType.EXIT,
                    market_id=market.market_id,
                    exit_reason=ExitReason.PUMP_EXIT,
                )

        # 4. Exit on any profit (combined bid > entry cost)
        current_value = market.combined_bid
        if current_value > entry_cost:
            profit = current_value - entry_cost
            profit_pct = profit / entry_cost

            logger.info(
                "LAG_EXIT_PROFIT",
                f"market={market.slug} entry={entry_cost:.4f} "
                f"current={current_value:.4f} profit={profit:.4f} ({profit_pct:.2%})",
            )

            return Signal(
                signal_type=SignalType.EXIT,
                market_id=market.market_id,
                exit_reason=ExitReason.EARLY_EXIT,
            )

        # 5. Exit on price normalization (spread tightened)
        spread = market.combined_ask - market.combined_bid
        if spread < 0.005:  # < 0.5% spread = normalized
            logger.info(
                "LAG_EXIT_NORMALIZED",
                f"market={market.slug} spread={spread:.4f}",
            )

            return Signal(
                signal_type=SignalType.EXIT,
                market_id=market.market_id,
                exit_reason=ExitReason.EARLY_EXIT,
            )

        # Otherwise hold to resolution
        return None

    def get_active_windows(self) -> list[LagWindow]:
        """Get all active (non-expired) lag windows"""
        active = []
        expired = []

        for symbol, window in self.lag_windows.items():
            if window.is_expired:
                expired.append(symbol)
            else:
                active.append(window)

        # Clean up expired
        for symbol in expired:
            del self.lag_windows[symbol]

        return active
