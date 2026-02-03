"""
Model Bridge

Wraps ProbabilitySurface and EdgeCalculator from the research module for safe,
optional use by the trading bot. Handles missing files gracefully and provides
a simple interface for model evaluation.
"""

import logging
from pathlib import Path
from typing import Optional

from research.models import EdgeCalculator, ProbabilitySurface
from engine.types import Direction, ModelOutput

logger = logging.getLogger(__name__)


class ModelBridge:
    """
    Bridge between research models and trading bot.
    
    Provides safe, optional access to probability models. Returns None when
    models are unavailable or on errors, allowing the bot to operate without
    model dependencies.
    
    Usage:
        bridge = ModelBridge(
            surface_path="research/models/probability_surface.json",
            fee_rate=0.0,
            min_edge=0.03,
        )
        
        if bridge.is_loaded:
            output = bridge.evaluate(
                deviation_pct=0.002,
                time_remaining_sec=3000,
                vol_regime="medium",
                spot_price=50000,
                candle_open=49900,
                fee_rate=0.0,
            )
    """
    
    def __init__(
        self,
        surface_path: Optional[str] = None,
        fee_rate: float = 0.0,
        min_edge: float = 0.03,
        min_confidence_score: float = 0.5,
        require_reliable: bool = True,
        use_conservative_edge: bool = True,
    ):
        """
        Initialize model bridge.
        
        Args:
            surface_path: Path to ProbabilitySurface JSON file (None = no model)
            fee_rate: Trading fee rate (0.0 for 1H markets, 0.03 for 15m)
            min_edge: Minimum edge threshold for trading
            min_confidence_score: Minimum confidence score (0-1)
            require_reliable: Only use reliable buckets (n >= 30)
            use_conservative_edge: Use CI lower bound for edge calculation
        """
        self.surface_path = surface_path
        self.fee_rate = fee_rate
        self.min_edge = min_edge
        self.min_confidence_score = min_confidence_score
        self.require_reliable = require_reliable
        self.use_conservative_edge = use_conservative_edge
        
        self._surface: Optional[ProbabilitySurface] = None
        self._calculator: Optional[EdgeCalculator] = None
        
        # Try to load if path provided
        if surface_path:
            self._load_surface()
    
    def _load_surface(self) -> bool:
        """
        Load ProbabilitySurface from JSON file.
        
        Returns:
            True if loaded successfully, False otherwise
        """
        if not self.surface_path:
            return False
        
        try:
            path = Path(self.surface_path)
            if not path.exists():
                logger.warning(
                    f"MODEL_BRIDGE surface file not found | path={self.surface_path}"
                )
                return False
            
            self._surface = ProbabilitySurface.load(str(path))
            self._calculator = EdgeCalculator(
                surface=self._surface,
                fee_rate=self.fee_rate,
                min_edge_threshold=self.min_edge,
                min_confidence_score=self.min_confidence_score,
                require_reliable=self.require_reliable,
                use_conservative_edge=self.use_conservative_edge,
            )
            
            logger.info(
                f"MODEL_BRIDGE loaded successfully | path={self.surface_path} buckets={len(self._surface.buckets)}"
            )
            return True
            
        except Exception as e:
            logger.error(
                f"MODEL_BRIDGE load failed | path={self.surface_path} error={str(e)}"
            )
            self._surface = None
            self._calculator = None
            return False
    
    @property
    def is_loaded(self) -> bool:
        """True if model is loaded and ready to use."""
        return self._surface is not None and self._calculator is not None
    
    def reload(self) -> bool:
        """
        Reload the model from disk (hot-reload).
        
        Returns:
            True if reloaded successfully, False otherwise
        """
        logger.info(f"MODEL_BRIDGE reloading | path={self.surface_path}")
        return self._load_surface()
    
    def evaluate(
        self,
        deviation_pct: Optional[float] = None,
        time_remaining_sec: int = 0,
        vol_regime: str = "medium",
        spot_price: Optional[float] = None,
        candle_open: Optional[float] = None,
        fee_rate: Optional[float] = None,
        market_price_up: Optional[float] = None,
        market_price_down: Optional[float] = None,
    ) -> Optional[ModelOutput]:
        """
        Evaluate model for current market conditions.
        
        Args:
            deviation_pct: Price deviation from window open (if None, calculated from spot/candle)
            time_remaining_sec: Seconds until market resolution
            vol_regime: Volatility regime ("low", "medium", "high", or "all")
            spot_price: Current spot price (used if deviation_pct not provided)
            candle_open: Candle open price (used if deviation_pct not provided)
            fee_rate: Override fee rate for this evaluation (uses instance default if None)
            market_price_up: Market price for UP token (required for edge calculation)
            market_price_down: Market price for DOWN token (required for edge calculation)
        
        Returns:
            ModelOutput if model available and evaluation successful, None otherwise
        """
        if not self.is_loaded:
            return None
        
        try:
            # Calculate deviation if not provided
            if deviation_pct is None:
                if spot_price is None or candle_open is None or candle_open == 0:
                    logger.warning(
                        f"MODEL_BRIDGE missing deviation data | spot_price={spot_price} candle_open={candle_open}"
                    )
                    return None
                deviation_pct = (spot_price - candle_open) / candle_open
            
            # Convert time from seconds to minutes (ProbabilitySurface uses minutes)
            time_remaining_min = max(0, int(time_remaining_sec / 60))
            
            # Use provided fee_rate or instance default
            eval_fee_rate = fee_rate if fee_rate is not None else self.fee_rate
            
            # If market prices not provided, we can't calculate edge
            # But we can still return probability estimates
            if market_price_up is None or market_price_down is None:
                # Get probability only (no edge calculation)
                prob, ci_lower, ci_upper, is_reliable = self._surface.get_probability(
                    deviation_pct=deviation_pct,
                    time_remaining=time_remaining_min,
                    vol_regime=vol_regime,
                )
                
                # Return basic model output without edge
                return ModelOutput(
                    prob_up=prob,
                    ci_lower=ci_lower,
                    ci_upper=ci_upper,
                    is_reliable=is_reliable,
                    edge_after_fees=0.0,
                    confidence_score=0.0,
                    kelly_fraction=0.0,
                    direction=Direction.NEUTRAL,
                    deviation_pct=deviation_pct,
                    vol_regime=vol_regime,
                )
            
            # Calculate edge using EdgeCalculator
            # Temporarily update calculator fee_rate if override provided
            original_fee_rate = self._calculator.fee_rate
            if fee_rate is not None:
                self._calculator.fee_rate = fee_rate
            
            try:
                opportunity = self._calculator.calculate_edge(
                    deviation_pct=deviation_pct,
                    time_remaining=time_remaining_min,
                    market_price_up=market_price_up,
                    market_price_down=market_price_down,
                    vol_regime=vol_regime,
                )
            finally:
                # Restore original fee_rate
                if fee_rate is not None:
                    self._calculator.fee_rate = original_fee_rate
            
            # Convert research.Direction to engine.types.Direction
            direction = self._convert_direction(opportunity.direction)
            
            return ModelOutput(
                prob_up=opportunity.model_prob_up,
                ci_lower=opportunity.model_ci_lower,
                ci_upper=opportunity.model_ci_upper,
                is_reliable=opportunity.is_reliable,
                edge_after_fees=opportunity.edge_after_fees,
                confidence_score=opportunity.confidence_score,
                kelly_fraction=opportunity.kelly_fraction,
                direction=direction,
                deviation_pct=deviation_pct,
                vol_regime=vol_regime,
            )
            
        except Exception as e:
            logger.error(
                f"MODEL_BRIDGE evaluation failed | error={str(e)} deviation_pct={deviation_pct}"
            )
            return None
    
    @staticmethod
    def _convert_direction(research_direction) -> Direction:
        """
        Convert research.models.Direction to engine.types.Direction.
        
        Args:
            research_direction: Direction enum from research.models.edge_calculator
        
        Returns:
            Direction enum from engine.types
        """
        from research.models.edge_calculator import Direction as ResearchDirection
        
        if research_direction == ResearchDirection.UP:
            return Direction.UP
        elif research_direction == ResearchDirection.DOWN:
            return Direction.DOWN
        else:
            return Direction.NEUTRAL
