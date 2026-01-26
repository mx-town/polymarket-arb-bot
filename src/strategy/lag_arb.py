"""
Lag arbitrage strategy (Phase 2).

Exploits the lag between Binance spot price moves and Polymarket
order book repricing. When spot moves sharply, Polymarket prices
lag by 1-5 seconds, creating brief arbitrage windows.

Strategy:
1. Monitor Binance spot prices (BTC/ETH)
2. Detect significant momentum (>0.1% in 10 seconds)
3. When spot moves UP: Polymarket DOWN prices are stale (buy before reprice)
4. When spot moves DOWN: Polymarket UP prices are stale (buy before reprice)
5. Enter when combined_ask < $1.00 during predicted lag window
6. Exit quickly on price normalization (don't wait for resolution)
"""

from datetime import datetime, timedelta
from typing import Optional, Dict
from dataclasses import dataclass

from src.config import LagArbConfig, TradingConfig
from src.market.state import MarketState
from src.data.price_tracker import MomentumSignal, MomentumDirection
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
    """Tracks an active lag arbitrage window"""

    symbol: str
    direction: MomentumDirection
    start_time: datetime
    signal: MomentumSignal
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
    Lag arbitrage strategy using Binance momentum signals.

    More aggressive than conservative strategy:
    - Enters during predicted lag windows
    - Accepts lower profit margins
    - Exits on price normalization (not just resolution)
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

    def on_momentum_signal(self, signal: MomentumSignal):
        """
        Handle momentum signal from price tracker.

        Opens a lag window if signal is significant.
        """
        if not signal.is_significant:
            return

        # Create or update lag window
        window = LagWindow(
            symbol=signal.symbol,
            direction=signal.direction,
            start_time=datetime.now(),
            signal=signal,
            expected_duration_ms=self.config.max_lag_window_ms,
        )

        self.lag_windows[signal.symbol] = window

        logger.info(
            "LAG_WINDOW_OPEN",
            f"symbol={signal.symbol} dir={signal.direction.value} "
            f"window_ms={self.config.max_lag_window_ms}",
        )

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
        1. Active lag window for this market's asset
        2. combined_ask < max_combined_price (up to $1.00)
        3. Profit margin exists (even if small during lag)
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

        # Lag arb uses more aggressive threshold
        if combined >= self.config.max_combined_price:
            return None

        # Calculate profits (accept lower margins during lag)
        gross_profit = 1.0 - combined
        estimated_fees = combined * self.trading.fee_rate
        net_profit = gross_profit - estimated_fees

        # During lag window, accept any positive net profit
        if net_profit <= 0:
            return None

        # Create opportunity with lag context
        opp = ArbOpportunity.from_market(market, self.trading.fee_rate)
        opp.confidence = window.signal.confidence

        # Determine which side is stale based on momentum direction
        # If spot moved UP, DOWN side is stale (buy it before it reprices up)
        # If spot moved DOWN, UP side is stale (buy it before it reprices down)
        stale_side = "DOWN" if window.direction == MomentumDirection.UP else "UP"

        logger.info(
            "LAG_ENTRY_SIGNAL",
            f"market={market.slug} combined={combined:.4f} "
            f"net={net_profit:.4f} stale_side={stale_side} "
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
        1. Exit on price normalization (spread < threshold)
        2. Exit if combined bid > entry (any profit)
        3. Exit if holding too long (lag window concept)
        """
        if not market.is_valid:
            return None

        entry_cost = entry_up_price + entry_down_price
        current_value = market.combined_bid

        # Exit on any profit (more aggressive than conservative)
        if current_value > entry_cost:
            profit_pct = (current_value - entry_cost) / entry_cost

            logger.info(
                "LAG_EXIT_PROFIT",
                f"market={market.slug} entry={entry_cost:.4f} "
                f"current={current_value:.4f} profit={profit_pct:.4f}",
            )

            return Signal(
                signal_type=SignalType.EXIT,
                market_id=market.market_id,
                exit_reason=ExitReason.EARLY_EXIT,
            )

        # Exit on price normalization
        # If combined_bid is close to combined_ask, prices have normalized
        spread = market.combined_ask - market.combined_bid
        if spread < 0.005:  # Normalized when spread < 0.5%
            logger.info(
                "LAG_EXIT_NORMALIZED",
                f"market={market.slug} spread={spread:.4f}",
            )

            return Signal(
                signal_type=SignalType.EXIT,
                market_id=market.market_id,
                exit_reason=ExitReason.EARLY_EXIT,
            )

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
