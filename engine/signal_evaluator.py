"""
Signal Evaluator

Stateless multi-tier signal detection for the polymarket-arb-bot.

Evaluates market conditions across four tiers:
1. DUTCH_BOOK: Zero-risk arbitrage (combined < 1.0)
2. LAG_ARB: Momentum-based lag arbitrage
3. MOMENTUM: Directional momentum signals with model confirmation
4. FLASH_CRASH: Contrarian reversion signals

Returns UnifiedSignals sorted by priority (lowest tier value = highest priority).
"""

import logging
from datetime import datetime
from typing import Optional

from engine.types import (
    UnifiedSignal,
    Direction,
    SignalTier,
    MarketContext,
    ModelOutput,
)
from engine.config import SignalEvaluatorConfig

# Optional import with None fallback
try:
    from engine.model_bridge import ModelBridge
except ImportError:
    ModelBridge = None  # type: ignore

logger = logging.getLogger(__name__)


class SignalEvaluator:
    """
    Stateless multi-tier signal evaluator.
    
    Evaluates market conditions and returns triggered signals sorted by priority.
    Supports config hot-reload and optional model integration.
    
    Usage:
        evaluator = SignalEvaluator(model_bridge, config)
        signals = evaluator.evaluate(
            momentum=0.0015,
            deviation_pct=0.002,
            spot_price=50000,
            candle_open=49900,
            market=market_ctx,
            symbol="BTCUSDT",
            time_remaining_sec=3000,
        )
        if signals:
            best = signals[0]  # Highest priority signal
    """
    
    def __init__(
        self,
        model_bridge: Optional["ModelBridge"] = None,
        config: Optional[SignalEvaluatorConfig] = None,
    ):
        """
        Initialize signal evaluator.
        
        Args:
            model_bridge: Optional ModelBridge for probability estimates
            config: SignalEvaluatorConfig with thresholds (defaults to defaults)
        """
        self.model_bridge = model_bridge
        self.config = config or SignalEvaluatorConfig()
    
    def update_config(self, config: SignalEvaluatorConfig) -> None:
        """
        Update configuration (hot-reload support).
        
        Args:
            config: New SignalEvaluatorConfig
        """
        self.config = config
        logger.info(
            "SIGNAL_EVALUATOR config updated",
            f"dutch_book_threshold={config.dutch_book_threshold} "
            f"momentum_threshold={config.momentum_trigger_threshold_pct}"
        )
    
    def evaluate(
        self,
        momentum: float,
        deviation_pct: float,
        spot_price: float,
        candle_open: float,
        market: Optional[MarketContext] = None,
        symbol: str = "",
        time_remaining_sec: int = 0,
    ) -> list[UnifiedSignal]:
        """
        Evaluate market conditions and return triggered signals.
        
        Checks tiers in order (DUTCH_BOOK -> LAG_ARB -> MOMENTUM -> FLASH_CRASH)
        and returns all triggered signals sorted by priority.
        
        Args:
            momentum: Current momentum value (from PriceTracker)
            deviation_pct: Price deviation from open (percentage)
            spot_price: Current spot price
            candle_open: Candle open price
            market: Optional MarketContext with order book prices
            symbol: Trading symbol (e.g., "BTCUSDT")
            time_remaining_sec: Seconds until market resolution
        
        Returns:
            List of UnifiedSignals sorted by priority (lowest tier value first)
        """
        signals: list[UnifiedSignal] = []
        timestamp = datetime.now()
        timestamp_ms = int(timestamp.timestamp() * 1000)
        
        # Calculate move from open
        move_from_open = deviation_pct
        
        # Get model output if available
        model_output: Optional[ModelOutput] = None
        if self.model_bridge and self.model_bridge.is_loaded and market:
            model_output = self.model_bridge.evaluate(
                deviation_pct=deviation_pct,
                time_remaining_sec=time_remaining_sec,
                spot_price=spot_price,
                candle_open=candle_open,
                market_price_up=market.up_price if market else None,
                market_price_down=market.down_price if market else None,
            )
        
        # Tier 1: DUTCH_BOOK (Zero Risk)
        if market and market.combined_ask < self.config.dutch_book_threshold:
            signal = self._create_dutch_book_signal(
                timestamp=timestamp,
                timestamp_ms=timestamp_ms,
                spot_price=spot_price,
                candle_open=candle_open,
                market=market,
                symbol=symbol,
                move_from_open=move_from_open,
            )
            if signal:
                signals.append(signal)
        
        # Tier 2: LAG_ARB (Momentum-based)
        if abs(momentum) >= self.config.momentum_trigger_threshold_pct:
            if market and market.combined_ask < self.config.max_combined_price:
                signal = self._create_lag_arb_signal(
                    timestamp=timestamp,
                    timestamp_ms=timestamp_ms,
                    momentum=momentum,
                    deviation_pct=deviation_pct,
                    spot_price=spot_price,
                    candle_open=candle_open,
                    market=market,
                    symbol=symbol,
                    time_remaining_sec=time_remaining_sec,
                    move_from_open=move_from_open,
                    model_output=model_output,
                )
                if signal:
                    signals.append(signal)
        
        # Tier 3: MOMENTUM (Model-confirmed directional)
        if model_output and model_output.has_edge:
            if (
                model_output.edge_after_fees >= self.config.momentum_min_edge
                and model_output.confidence_score >= self.config.momentum_min_confidence
            ):
                signal = self._create_momentum_signal(
                    timestamp=timestamp,
                    timestamp_ms=timestamp_ms,
                    momentum=momentum,
                    deviation_pct=deviation_pct,
                    spot_price=spot_price,
                    candle_open=candle_open,
                    market=market,
                    symbol=symbol,
                    time_remaining_sec=time_remaining_sec,
                    move_from_open=move_from_open,
                    model_output=model_output,
                )
                if signal:
                    signals.append(signal)
        
        # Tier 4: FLASH_CRASH (Contrarian reversion)
        if abs(deviation_pct) >= self.config.flash_crash_threshold_pct:
            signal = self._create_flash_crash_signal(
                timestamp=timestamp,
                timestamp_ms=timestamp_ms,
                momentum=momentum,
                deviation_pct=deviation_pct,
                spot_price=spot_price,
                candle_open=candle_open,
                market=market,
                symbol=symbol,
                time_remaining_sec=time_remaining_sec,
                move_from_open=move_from_open,
            )
            if signal:
                signals.append(signal)
        
        # Sort by priority (lowest tier value = highest priority)
        signals.sort(key=lambda s: s.priority)
        
        return signals
    
    def _create_dutch_book_signal(
        self,
        timestamp: datetime,
        timestamp_ms: int,
        spot_price: float,
        candle_open: float,
        market: MarketContext,
        symbol: str,
        move_from_open: float,
    ) -> Optional[UnifiedSignal]:
        """Create DUTCH_BOOK signal (Tier 1)."""
        if market.combined_ask >= 1.0:
            return None
        
        # Profit is guaranteed: 1.0 - combined_ask
        profit = 1.0 - market.combined_ask
        profit_pct = profit / market.combined_ask if market.combined_ask > 0 else 0.0
        
        # Determine direction based on which side is cheaper
        # Buy both sides, but signal direction indicates primary opportunity
        direction = Direction.UP if market.up_price < market.down_price else Direction.DOWN
        
        return UnifiedSignal(
            tier=SignalTier.DUTCH_BOOK,
            direction=direction,
            symbol=symbol,
            market_id=None,  # MarketContext doesn't include market_id
            timestamp=timestamp,
            timestamp_ms=timestamp_ms,
            momentum=0.0,  # Not relevant for Dutch Book
            candle_open=candle_open,
            spot_price=spot_price,
            move_from_open=move_from_open,
            market=market,
            model=None,  # Not needed for Dutch Book
            expected_edge=profit,
            confidence=1.0,  # Zero risk
            metadata={
                "profit_pct": profit_pct,
                "combined_ask": market.combined_ask,
                "up_price": market.up_price,
                "down_price": market.down_price,
            },
        )
    
    def _create_lag_arb_signal(
        self,
        timestamp: datetime,
        timestamp_ms: int,
        momentum: float,
        deviation_pct: float,
        spot_price: float,
        candle_open: float,
        market: Optional[MarketContext],
        symbol: str,
        time_remaining_sec: int,
        move_from_open: float,
        model_output: Optional[ModelOutput],
    ) -> Optional[UnifiedSignal]:
        """Create LAG_ARB signal (Tier 2)."""
        # Determine direction from momentum
        direction = Direction.UP if momentum > 0 else Direction.DOWN
        
        # Calculate expected edge
        # If model available, use model edge; otherwise estimate from momentum
        if model_output and model_output.has_edge:
            expected_edge = model_output.edge_after_fees
            confidence = model_output.confidence_score
        else:
            # Estimate edge from momentum strength
            expected_edge = abs(momentum) * 2.0  # Rough heuristic
            confidence = 0.7  # Medium confidence for lag arb
        
        # Check minimum edge threshold
        if expected_edge < self.config.momentum_min_edge:
            return None
        
        return UnifiedSignal(
            tier=SignalTier.LAG_ARB,
            direction=direction,
            symbol=symbol,
            market_id=None,
            timestamp=timestamp,
            timestamp_ms=timestamp_ms,
            momentum=momentum,
            candle_open=candle_open,
            spot_price=spot_price,
            move_from_open=move_from_open,
            market=market,
            model=model_output,
            expected_edge=expected_edge,
            confidence=confidence,
            metadata={
                "momentum": momentum,
                "deviation_pct": deviation_pct,
                "expected_lag_ms": self.config.expected_lag_ms,
                "max_lag_window_ms": self.config.max_lag_window_ms,
            },
        )
    
    def _create_momentum_signal(
        self,
        timestamp: datetime,
        timestamp_ms: int,
        momentum: float,
        deviation_pct: float,
        spot_price: float,
        candle_open: float,
        market: Optional[MarketContext],
        symbol: str,
        time_remaining_sec: int,
        move_from_open: float,
        model_output: ModelOutput,
    ) -> Optional[UnifiedSignal]:
        """Create MOMENTUM signal (Tier 3)."""
        # Use model direction
        direction = model_output.direction
        
        # Check time remaining
        if time_remaining_sec < self.config.min_time_remaining_sec:
            return None
        
        return UnifiedSignal(
            tier=SignalTier.MOMENTUM,
            direction=direction,
            symbol=symbol,
            market_id=None,
            timestamp=timestamp,
            timestamp_ms=timestamp_ms,
            momentum=momentum,
            candle_open=candle_open,
            spot_price=spot_price,
            move_from_open=move_from_open,
            market=market,
            model=model_output,
            expected_edge=model_output.edge_after_fees,
            confidence=model_output.confidence_score,
            metadata={
                "prob_up": model_output.prob_up,
                "kelly_fraction": model_output.kelly_fraction,
                "is_reliable": model_output.is_reliable,
                "vol_regime": model_output.vol_regime,
            },
        )
    
    def _create_flash_crash_signal(
        self,
        timestamp: datetime,
        timestamp_ms: int,
        momentum: float,
        deviation_pct: float,
        spot_price: float,
        candle_open: float,
        market: Optional[MarketContext],
        symbol: str,
        time_remaining_sec: int,
        move_from_open: float,
    ) -> Optional[UnifiedSignal]:
        """Create FLASH_CRASH signal (Tier 4)."""
        # Flash crash is contrarian: buy the crashed side expecting reversion
        # If deviation is negative (price dropped), buy UP expecting bounce
        # If deviation is positive (price spiked), buy DOWN expecting drop
        
        if deviation_pct < -self.config.flash_crash_threshold_pct:
            # Price crashed down, buy UP (contrarian)
            direction = Direction.UP
            expected_reversion = abs(deviation_pct) * self.config.flash_crash_reversion_target
        elif deviation_pct > self.config.flash_crash_threshold_pct:
            # Price spiked up, buy DOWN (contrarian)
            direction = Direction.DOWN
            expected_reversion = abs(deviation_pct) * self.config.flash_crash_reversion_target
        else:
            return None
        
        # Lower confidence for flash crash (high risk/reward)
        confidence = 0.4
        
        return UnifiedSignal(
            tier=SignalTier.FLASH_CRASH,
            direction=direction,
            symbol=symbol,
            market_id=None,
            timestamp=timestamp,
            timestamp_ms=timestamp_ms,
            momentum=momentum,
            candle_open=candle_open,
            spot_price=spot_price,
            move_from_open=move_from_open,
            market=market,
            model=None,  # Flash crash doesn't use model
            expected_edge=expected_reversion,
            confidence=confidence,
            metadata={
                "deviation_pct": deviation_pct,
                "reversion_target": self.config.flash_crash_reversion_target,
                "is_contrarian": True,
            },
        )
