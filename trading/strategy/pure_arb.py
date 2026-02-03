"""
Pure arbitrage strategy - enters on price threshold only.

Unlike lag arb, does NOT require momentum signal.
Entry: combined_ask < max_combined_price (default $0.99)
Exit: Hold to resolution (conservative approach)

This strategy implements the "Pure Arb" leg of the OR logic:
- Pure Arb: Combined < $0.99 (any time, no momentum needed)
- Lag Arb: Combined <= $1.00 AND momentum detected

Can run alongside lag arb for maximum opportunity capture.
"""

from trading.config import PureArbConfig, TradingConfig
from trading.market.state import MarketState
from trading.strategy.signals import (
    ArbOpportunity,
    Signal,
    SignalDetector,
    SignalType,
)
from trading.utils.logging import get_logger

logger = get_logger("pure_arb")


class PureArbStrategy(SignalDetector):
    """
    Pure arbitrage: buy both sides when combined < threshold.
    No momentum or signal required - pure price-based entry.
    """

    def __init__(
        self,
        trading_config: TradingConfig,
        pure_arb_config: PureArbConfig,
    ):
        self.trading = trading_config
        self.config = pure_arb_config

    def check_entry(self, market: MarketState) -> Signal | None:
        """
        Check if market has pure arb opportunity.
        Entry condition: combined_ask < max_combined_price
        """
        if not self.config.enabled:
            return None

        if not market.is_valid:
            return None

        combined = market.combined_ask

        if combined >= self.config.max_combined_price:
            return None

        # Calculate profits using pure_arb fee rate
        gross_profit = 1.0 - combined
        estimated_fees = combined * self.config.fee_rate
        net_profit = gross_profit - estimated_fees

        if net_profit < self.config.min_net_profit:
            return None

        opp = ArbOpportunity.from_market(market, self.config.fee_rate)

        logger.info(
            "PURE_ARB_ENTRY",
            f"market={market.slug} combined={combined:.4f} "
            f"gross={gross_profit:.4f} net={net_profit:.4f}",
        )

        return Signal(
            signal_type=SignalType.ENTRY,
            market_id=market.market_id,
            opportunity=opp,
            confidence=1.0,  # High confidence - guaranteed profit
        )

    def check_exit(
        self,
        market: MarketState,
        entry_up_price: float,
        entry_down_price: float,
        entry_time=None,
        position=None,
    ) -> Signal | None:
        """
        Pure arb holds to resolution by default.
        No aggressive exit - profit is guaranteed at resolution.
        """
        # Hold to resolution - no early exit
        return None
