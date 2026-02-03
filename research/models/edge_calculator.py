"""
Edge Calculator

Determines trading opportunities by comparing model probability estimates
to market prices. Accounts for fees, confidence, and position sizing.
"""

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Optional

import numpy as np

from .probability_surface import ProbabilitySurface

logger = logging.getLogger(__name__)


class Direction(Enum):
    """Trade direction."""
    UP = "UP"
    DOWN = "DOWN"
    NONE = "NONE"


@dataclass
class TradingOpportunity:
    """A potential trading opportunity identified by edge analysis."""
    # Context
    deviation_pct: float
    time_remaining: int
    vol_regime: str

    # Model estimates
    model_prob_up: float
    model_ci_lower: float
    model_ci_upper: float
    is_reliable: bool

    # Market prices
    market_price_up: float  # Cost to buy UP (YES) token
    market_price_down: float  # Cost to buy DOWN (NO) token

    # Edge analysis
    direction: Direction
    raw_edge: float  # model_prob - market_price
    edge_after_fees: float  # Accounting for round-trip fees
    expected_value: float  # Edge * position size
    kelly_fraction: float  # Optimal position sizing

    # Risk metrics
    confidence_score: float  # 0-1 based on sample size and CI width
    min_edge: float  # Conservative edge using CI bound

    # Trading signals
    is_tradeable: bool  # Meets all criteria
    reject_reason: Optional[str] = None


class EdgeCalculator:
    """
    Calculates trading edge from probability model and market prices.

    Features:
    - Compares model P(UP) to market-implied probability
    - Accounts for trading fees (default 3% for 15m markets)
    - Provides Kelly criterion position sizing
    - Filters by minimum edge, sample size, and confidence

    Usage:
        calc = EdgeCalculator(surface, fee_rate=0.03)
        opp = calc.calculate_edge(
            deviation_pct=0.005,
            time_remaining=10,
            market_price_up=0.52,
            market_price_down=0.52,
            vol_regime="medium"
        )
        if opp.is_tradeable:
            print(f"Trade {opp.direction} with {opp.edge_after_fees:.1%} edge")
    """

    def __init__(
        self,
        surface: ProbabilitySurface,
        fee_rate: float = 0.03,  # 3% for 15m markets, 0% for 1H
        min_edge_threshold: float = 0.05,  # 5% minimum edge
        min_confidence_score: float = 0.5,
        require_reliable: bool = True,
        use_conservative_edge: bool = True  # Use CI lower bound
    ):
        """
        Args:
            surface: Fitted probability surface
            fee_rate: Trading fee rate (0.03 = 3%)
            min_edge_threshold: Minimum edge to consider tradeable
            min_confidence_score: Minimum confidence score
            require_reliable: Only trade on reliable buckets (n >= 30)
            use_conservative_edge: Use CI bound for edge calculation
        """
        self.surface = surface
        self.fee_rate = fee_rate
        self.min_edge_threshold = min_edge_threshold
        self.min_confidence_score = min_confidence_score
        self.require_reliable = require_reliable
        self.use_conservative_edge = use_conservative_edge

    def _calculate_confidence_score(
        self,
        sample_size: int,
        ci_width: float
    ) -> float:
        """
        Calculate confidence score based on sample size and CI width.

        Returns value 0-1 where:
        - Higher sample size increases confidence
        - Narrower CI increases confidence
        """
        # Sample size contribution (saturates around n=100)
        size_score = 1 - np.exp(-sample_size / 30)

        # CI width contribution (narrower = better)
        # Perfect CI would be 0, worst is 1.0
        ci_score = 1 - min(ci_width, 1.0)

        # Combined score
        return (size_score * 0.6 + ci_score * 0.4)

    def _calculate_kelly(
        self,
        win_prob: float,
        win_payout: float,
        loss_amount: float
    ) -> float:
        """
        Calculate Kelly criterion fraction.

        Kelly = (p * win - q * loss) / win
        where p = win probability, q = 1-p
        """
        if win_payout <= 0:
            return 0.0

        q = 1 - win_prob
        kelly = (win_prob * win_payout - q * loss_amount) / win_payout

        # Cap at 25% of bankroll for safety
        return max(0.0, min(0.25, kelly))

    def calculate_edge(
        self,
        deviation_pct: float,
        time_remaining: int,
        market_price_up: float,
        market_price_down: float,
        vol_regime: Optional[str] = None
    ) -> TradingOpportunity:
        """
        Calculate trading edge for current market conditions.

        Args:
            deviation_pct: Current price deviation from window open
            time_remaining: Minutes until window close
            market_price_up: Market price for UP token
            market_price_down: Market price for DOWN token
            vol_regime: Volatility regime (None = use "all")

        Returns:
            TradingOpportunity with full analysis
        """
        # Get model probability
        model_prob, ci_lower, ci_upper, is_reliable = self.surface.get_probability(
            deviation_pct=deviation_pct,
            time_remaining=time_remaining,
            vol_regime=vol_regime
        )

        bucket = self.surface.get_bucket(deviation_pct, time_remaining, vol_regime)
        sample_size = bucket.sample_size if bucket else 0
        ci_width = ci_upper - ci_lower

        # Calculate confidence score
        confidence_score = self._calculate_confidence_score(sample_size, ci_width)

        # Market-implied probabilities
        # If market is efficient, prices should sum to ~1.0
        market_total = market_price_up + market_price_down
        implied_prob_up = market_price_up / market_total if market_total > 0 else 0.5

        # Calculate raw edges
        raw_edge_up = model_prob - implied_prob_up
        raw_edge_down = (1 - model_prob) - (1 - implied_prob_up)

        # Determine direction based on larger edge
        if abs(raw_edge_up) >= abs(raw_edge_down) and raw_edge_up > 0:
            direction = Direction.UP
            raw_edge = raw_edge_up
            market_price = market_price_up
            # Conservative edge uses lower CI bound for UP
            min_edge = ci_lower - implied_prob_up
        elif raw_edge_down > 0:
            direction = Direction.DOWN
            raw_edge = raw_edge_down
            market_price = market_price_down
            # Conservative edge uses upper CI bound inverted for DOWN
            min_edge = (1 - ci_upper) - (1 - implied_prob_up)
        else:
            direction = Direction.NONE
            raw_edge = 0.0
            market_price = 0.5
            min_edge = 0.0

        # Account for fees
        # Fee applies when buying and potentially when selling
        # Worst case: fee on both buy and sell
        total_fee_drag = self.fee_rate * 2
        edge_after_fees = raw_edge - total_fee_drag

        # Use conservative edge if configured
        if self.use_conservative_edge:
            effective_edge = min_edge - total_fee_drag
        else:
            effective_edge = edge_after_fees

        # Calculate Kelly fraction for position sizing
        if direction != Direction.NONE and effective_edge > 0:
            # Win payout = 1 - market_price (after fees)
            win_payout = (1 - market_price) * (1 - self.fee_rate)
            loss_amount = market_price
            win_prob = model_prob if direction == Direction.UP else (1 - model_prob)
            kelly_fraction = self._calculate_kelly(win_prob, win_payout, loss_amount)
        else:
            kelly_fraction = 0.0

        # Expected value (per dollar bet)
        expected_value = effective_edge if effective_edge > 0 else 0.0

        # Determine if tradeable
        is_tradeable = True
        reject_reason = None

        if direction == Direction.NONE:
            is_tradeable = False
            reject_reason = "No positive edge found"
        elif self.require_reliable and not is_reliable:
            is_tradeable = False
            reject_reason = f"Insufficient samples ({sample_size} < 30)"
        elif confidence_score < self.min_confidence_score:
            is_tradeable = False
            reject_reason = f"Low confidence ({confidence_score:.2f} < {self.min_confidence_score})"
        elif effective_edge < self.min_edge_threshold:
            is_tradeable = False
            reject_reason = f"Edge too small ({effective_edge:.1%} < {self.min_edge_threshold:.1%})"

        return TradingOpportunity(
            deviation_pct=deviation_pct,
            time_remaining=time_remaining,
            vol_regime=vol_regime or "all",
            model_prob_up=model_prob,
            model_ci_lower=ci_lower,
            model_ci_upper=ci_upper,
            is_reliable=is_reliable,
            market_price_up=market_price_up,
            market_price_down=market_price_down,
            direction=direction,
            raw_edge=raw_edge,
            edge_after_fees=edge_after_fees,
            expected_value=expected_value,
            kelly_fraction=kelly_fraction,
            confidence_score=confidence_score,
            min_edge=min_edge,
            is_tradeable=is_tradeable,
            reject_reason=reject_reason
        )

    def scan_opportunities(
        self,
        market_price_up: float,
        market_price_down: float,
        current_deviation: float,
        current_time_remaining: int,
        vol_regime: Optional[str] = None
    ) -> list[TradingOpportunity]:
        """
        Scan for opportunities at current and nearby conditions.

        Returns list of opportunities sorted by expected value.
        """
        opportunities = []

        # Current conditions
        opp = self.calculate_edge(
            deviation_pct=current_deviation,
            time_remaining=current_time_remaining,
            market_price_up=market_price_up,
            market_price_down=market_price_down,
            vol_regime=vol_regime
        )
        opportunities.append(opp)

        # Also check adjacent time buckets
        for time_offset in [-1, 1]:
            alt_time = current_time_remaining + time_offset
            if alt_time >= 0 and alt_time in self.surface.time_bins:
                opp = self.calculate_edge(
                    deviation_pct=current_deviation,
                    time_remaining=alt_time,
                    market_price_up=market_price_up,
                    market_price_down=market_price_down,
                    vol_regime=vol_regime
                )
                opportunities.append(opp)

        # Sort by expected value
        opportunities.sort(key=lambda x: x.expected_value, reverse=True)

        return opportunities

    def get_fair_price(
        self,
        deviation_pct: float,
        time_remaining: int,
        vol_regime: Optional[str] = None
    ) -> tuple[float, float]:
        """
        Get model's fair price for UP and DOWN tokens.

        Returns (fair_price_up, fair_price_down) accounting for fees.
        """
        model_prob, _, _, _ = self.surface.get_probability(
            deviation_pct=deviation_pct,
            time_remaining=time_remaining,
            vol_regime=vol_regime
        )

        # Fair price is probability adjusted for expected fee drag
        fair_up = model_prob
        fair_down = 1 - model_prob

        return (fair_up, fair_down)


class StrategyIntegration:
    """
    Integration layer for using edge calculator with the trading bot.

    Maps to the strategy tiers mentioned in the task:
    - Tier 2: Lag Arb Tilt (probability + lag timing)
    - Tier 3: Directional (probability at extremes)
    - Tier 4: Late Certainty (probability with <2 min remaining)
    """

    def __init__(
        self,
        calculator: EdgeCalculator,
        tier2_min_edge: float = 0.03,  # Lower threshold for lag arb
        tier3_min_edge: float = 0.08,  # Higher for directional
        tier4_min_edge: float = 0.05,  # Late certainty
        tier4_max_time: int = 2  # Minutes remaining for tier 4
    ):
        self.calculator = calculator
        self.tier2_min_edge = tier2_min_edge
        self.tier3_min_edge = tier3_min_edge
        self.tier4_min_edge = tier4_min_edge
        self.tier4_max_time = tier4_max_time

    def evaluate_tier2_signal(
        self,
        deviation_pct: float,
        time_remaining: int,
        market_price_up: float,
        market_price_down: float,
        vol_regime: str = "medium"
    ) -> tuple[bool, Optional[TradingOpportunity]]:
        """
        Evaluate for Tier 2 (Lag Arb Tilt).

        Used to add directional tilt to lag arb positions.
        Lower edge threshold since combined with lag timing.
        """
        opp = self.calculator.calculate_edge(
            deviation_pct=deviation_pct,
            time_remaining=time_remaining,
            market_price_up=market_price_up,
            market_price_down=market_price_down,
            vol_regime=vol_regime
        )

        # Use lower threshold for tier 2
        is_signal = (
            opp.direction != Direction.NONE and
            opp.edge_after_fees >= self.tier2_min_edge and
            opp.confidence_score >= 0.4
        )

        return (is_signal, opp if is_signal else None)

    def evaluate_tier3_signal(
        self,
        deviation_pct: float,
        time_remaining: int,
        market_price_up: float,
        market_price_down: float,
        vol_regime: str = "all"
    ) -> tuple[bool, Optional[TradingOpportunity]]:
        """
        Evaluate for Tier 3 (Directional at extremes).

        Pure directional bets at extreme deviations where
        probability is significantly biased.
        """
        # Check if deviation is extreme enough
        if abs(deviation_pct) < 0.005:  # 0.5%
            return (False, None)

        opp = self.calculator.calculate_edge(
            deviation_pct=deviation_pct,
            time_remaining=time_remaining,
            market_price_up=market_price_up,
            market_price_down=market_price_down,
            vol_regime=vol_regime
        )

        # Higher threshold for pure directional
        is_signal = (
            opp.direction != Direction.NONE and
            opp.edge_after_fees >= self.tier3_min_edge and
            opp.is_reliable and
            opp.confidence_score >= 0.6
        )

        return (is_signal, opp if is_signal else None)

    def evaluate_tier4_signal(
        self,
        deviation_pct: float,
        time_remaining: int,
        market_price_up: float,
        market_price_down: float,
        vol_regime: str = "all"
    ) -> tuple[bool, Optional[TradingOpportunity]]:
        """
        Evaluate for Tier 4 (Late Certainty).

        High-conviction bets with <2 minutes remaining where
        outcome is nearly determined.
        """
        if time_remaining > self.tier4_max_time:
            return (False, None)

        opp = self.calculator.calculate_edge(
            deviation_pct=deviation_pct,
            time_remaining=time_remaining,
            market_price_up=market_price_up,
            market_price_down=market_price_down,
            vol_regime=vol_regime
        )

        # Should have high confidence at late stage
        is_signal = (
            opp.direction != Direction.NONE and
            opp.edge_after_fees >= self.tier4_min_edge and
            opp.model_prob_up > 0.7 or opp.model_prob_up < 0.3  # Strong tilt
        )

        return (is_signal, opp if is_signal else None)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    print("EdgeCalculator module loaded successfully")
    print("Use with ProbabilitySurface to identify trading opportunities")
