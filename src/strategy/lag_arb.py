"""
Lag arbitrage strategy (Phase 2).

KEY INSIGHT: Polymarket 1H markets resolve based on Binance 1H candle.
- Reference price = candle OPEN (not close)
- If close >= open → "Up" wins at resolution
- If close < open → "Down" wins at resolution

Strategy:
1. Fetch candle OPEN from Binance Klines API
2. Compare current spot vs candle open
3. If spot > open + threshold → "Up" is expected winner
4. If spot < open - threshold → "Down" is expected winner
5. If Polymarket hasn't repriced (combined_ask < $1.00), that's the arbitrage
6. Buy BOTH sides during the lag window
7. Exit on price normalization or hold to resolution

Why this works:
- Polymarket lags Binance by 1-5 seconds
- When spot crosses above candle open, "Up" becomes likely winner
- Market makers are slow to reprice
- We buy BOTH sides during the lag for < $1.00
- Even if wrong about direction, we profit if combined < $1.00
"""

from datetime import datetime
from typing import Optional, Dict
from dataclasses import dataclass

from src.config import LagArbConfig, TradingConfig
from src.market.state import MarketState
from src.data.price_tracker import DirectionSignal, Direction
from src.strategy.signals import (
    ArbOpportunity,
    ExitReason,
    Signal,
    SignalDetector,
    SignalType,
)
from src.utils.logging import get_logger

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
    ):
        self.trading = trading_config
        self.config = lag_config

        # Active lag windows by symbol
        self.lag_windows: Dict[str, LagWindow] = {}

        # Map market slugs to Binance symbols
        self.market_to_symbol = {
            "btc": "BTCUSDT",
            "eth": "ETHUSDT",
        }

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
            f"symbol={signal.symbol} expected_winner={expected_winner} "
            f"move_from_open={signal.move_from_open:.4f} ({signal.move_from_open*100:.2f}%) "
            f"spot={signal.current_price:.2f} candle_open={signal.candle_open:.2f} "
            f"window_ms={self.config.max_lag_window_ms}",
        )

    # Backwards compatibility
    def on_momentum_signal(self, signal: DirectionSignal):
        """Alias for on_direction_signal (backwards compatibility)"""
        self.on_direction_signal(signal)

    def _get_symbol_for_market(self, market: MarketState) -> Optional[str]:
        """Get Binance symbol for a market"""
        slug = market.slug.lower()
        for asset, symbol in self.market_to_symbol.items():
            if asset in slug:
                return symbol
        return None

    def _get_active_window(self, symbol: str) -> Optional[LagWindow]:
        """Get active (non-expired) lag window for symbol"""
        window = self.lag_windows.get(symbol)
        if window and not window.is_expired:
            return window

        # Clean up expired window
        if window:
            del self.lag_windows[symbol]
        return None

    def check_entry(self, market: MarketState) -> Optional[Signal]:
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
    ) -> Optional[Signal]:
        """
        Check if position should exit.
        
        Lag arb exits more aggressively:
        1. Exit if combined_bid > entry_cost (any profit available)
        2. Exit on price normalization (spread < threshold)
        3. Otherwise hold to resolution (guaranteed profit if entry < $1.00)
        """
        if not market.is_valid:
            return None

        entry_cost = entry_up_price + entry_down_price
        current_value = market.combined_bid

        # Exit on any profit (more aggressive than conservative)
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

        # Exit on price normalization (spread tightened)
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
