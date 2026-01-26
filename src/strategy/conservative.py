"""
Conservative arbitrage strategy (Phase 1).

Strategy:
1. Monitor Up/Down markets
2. When YES_ask + NO_ask < threshold (e.g., $0.99), buy both
3. Hold until resolution OR exit early if one side pumps
4. Guaranteed profit if entry < $1.00
"""

from typing import Optional

from src.config import ConservativeConfig, TradingConfig
from src.market.state import MarketState
from src.strategy.signals import (
    ArbOpportunity,
    ExitReason,
    Signal,
    SignalDetector,
    SignalType,
)
from src.utils.logging import get_logger

logger = get_logger("conservative")


class ConservativeStrategy(SignalDetector):
    """
    Conservative arbitrage: buy both sides when combined < threshold.
    """

    def __init__(
        self,
        trading_config: TradingConfig,
        strategy_config: ConservativeConfig,
    ):
        self.trading = trading_config
        self.config = strategy_config

    def check_entry(self, market: MarketState) -> Optional[Signal]:
        """
        Check if market has entry opportunity.

        Entry conditions:
        1. combined_ask < max_combined_price (e.g., $0.99)
        2. time_to_resolution > min_time
        3. gross_profit >= min_spread
        4. net_profit >= min_net_profit (after fees)
        """
        if not market.is_valid:
            return None

        combined = market.combined_ask

        # Check price threshold
        if combined >= self.config.max_combined_price:
            return None

        # Check time to resolution
        ttr = market.time_to_resolution
        if ttr is not None and ttr < self.config.min_time_to_resolution_sec:
            logger.debug("SKIP_TIME", f"market={market.slug} ttr={ttr:.0f}s")
            return None

        # Calculate profits
        gross_profit = market.potential_profit
        estimated_fees = combined * self.trading.fee_rate
        net_profit = gross_profit - estimated_fees

        # Check profit thresholds
        if gross_profit < self.trading.min_spread:
            return None

        if net_profit < self.trading.min_net_profit:
            return None

        # Create opportunity
        opp = ArbOpportunity.from_market(market, self.trading.fee_rate)

        logger.info(
            "ENTRY_SIGNAL",
            f"market={market.slug} combined={combined:.4f} "
            f"gross={gross_profit:.4f} net={net_profit:.4f}",
        )

        return Signal(
            signal_type=SignalType.ENTRY,
            market_id=market.market_id,
            opportunity=opp,
            confidence=1.0,
        )

    def check_exit(
        self,
        market: MarketState,
        entry_up_price: float,
        entry_down_price: float,
    ) -> Optional[Signal]:
        """
        Check if position should exit.

        Exit conditions:
        1. One side pumped > threshold (e.g., +10%)
        2. Approaching resolution
        3. Combined bid > entry cost (profit available now)
        """
        if not market.is_valid:
            return None

        entry_cost = entry_up_price + entry_down_price

        # Check pump exit - UP side
        up_change = (market.up_best_bid - entry_up_price) / entry_up_price
        if up_change >= self.config.exit_on_pump_threshold:
            logger.info(
                "EXIT_PUMP_UP",
                f"market={market.slug} up_change={up_change:.2%}",
            )
            return Signal(
                signal_type=SignalType.EXIT,
                market_id=market.market_id,
                exit_reason=ExitReason.PUMP_EXIT,
            )

        # Check pump exit - DOWN side
        down_change = (market.down_best_bid - entry_down_price) / entry_down_price
        if down_change >= self.config.exit_on_pump_threshold:
            logger.info(
                "EXIT_PUMP_DOWN",
                f"market={market.slug} down_change={down_change:.2%}",
            )
            return Signal(
                signal_type=SignalType.EXIT,
                market_id=market.market_id,
                exit_reason=ExitReason.PUMP_EXIT,
            )

        # Check early exit on profit
        current_value = market.combined_bid
        if current_value > entry_cost * 1.005:  # 0.5% profit threshold
            logger.info(
                "EXIT_PROFIT",
                f"market={market.slug} entry={entry_cost:.4f} current={current_value:.4f}",
            )
            return Signal(
                signal_type=SignalType.EXIT,
                market_id=market.market_id,
                exit_reason=ExitReason.EARLY_EXIT,
            )

        # Check time to resolution
        ttr = market.time_to_resolution
        if ttr is not None and ttr < 60:  # Exit 60s before resolution
            logger.info(
                "EXIT_TIME",
                f"market={market.slug} ttr={ttr:.0f}s",
            )
            return Signal(
                signal_type=SignalType.EXIT,
                market_id=market.market_id,
                exit_reason=ExitReason.TIME_LIMIT,
            )

        return None


def scan_for_opportunities(
    markets: list[MarketState],
    trading_config: TradingConfig,
    strategy_config: ConservativeConfig,
) -> list[ArbOpportunity]:
    """
    Scan markets for conservative arb opportunities.

    This is the polling-mode equivalent of the original arb_bot logic.
    """
    strategy = ConservativeStrategy(trading_config, strategy_config)
    opportunities = []

    for market in markets:
        signal = strategy.check_entry(market)
        if signal and signal.opportunity:
            opportunities.append(signal.opportunity)

    return opportunities
