"""
Configuration classes for the shared engine.

SignalEvaluatorConfig: Configuration for signal detection thresholds
EngineConfig: Overall engine configuration including model paths
"""

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class SignalEvaluatorConfig:
    """
    Configuration for the SignalEvaluator.
    
    Defines thresholds for each signal tier and general evaluation parameters.
    """
    # Dutch Book (Tier 1) thresholds
    dutch_book_threshold: float = 0.99          # Combined < this = Dutch book
    
    # Lag Arb (Tier 2) thresholds
    momentum_trigger_threshold_pct: float = 0.001   # 0.1% momentum trigger
    max_combined_price: float = 0.995               # Max combined for lag arb entry
    expected_lag_ms: int = 2000                     # Expected Polymarket lag
    max_lag_window_ms: int = 5000                   # Max window to wait for repricing
    
    # Momentum (Tier 3) thresholds
    momentum_min_edge: float = 0.03                 # Minimum edge for momentum signals
    momentum_min_confidence: float = 0.5            # Minimum confidence score
    
    # Flash Crash (Tier 4) thresholds
    flash_crash_threshold_pct: float = 0.05         # 5% move threshold
    flash_crash_reversion_target: float = 0.5       # Target 50% reversion
    
    # General
    min_time_remaining_sec: int = 300               # Minimum time to resolution
    require_model_confirmation: bool = False        # Require model for entry
    
    @classmethod
    def from_dict(cls, d: dict) -> "SignalEvaluatorConfig":
        """Create config from dictionary."""
        return cls(
            dutch_book_threshold=d.get("dutch_book_threshold", 0.99),
            momentum_trigger_threshold_pct=d.get("momentum_trigger_threshold_pct", 0.001),
            max_combined_price=d.get("max_combined_price", 0.995),
            expected_lag_ms=d.get("expected_lag_ms", 2000),
            max_lag_window_ms=d.get("max_lag_window_ms", 5000),
            momentum_min_edge=d.get("momentum_min_edge", 0.03),
            momentum_min_confidence=d.get("momentum_min_confidence", 0.5),
            flash_crash_threshold_pct=d.get("flash_crash_threshold_pct", 0.05),
            flash_crash_reversion_target=d.get("flash_crash_reversion_target", 0.5),
            min_time_remaining_sec=d.get("min_time_remaining_sec", 300),
            require_model_confirmation=d.get("require_model_confirmation", False),
        )
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "dutch_book_threshold": self.dutch_book_threshold,
            "momentum_trigger_threshold_pct": self.momentum_trigger_threshold_pct,
            "max_combined_price": self.max_combined_price,
            "expected_lag_ms": self.expected_lag_ms,
            "max_lag_window_ms": self.max_lag_window_ms,
            "momentum_min_edge": self.momentum_min_edge,
            "momentum_min_confidence": self.momentum_min_confidence,
            "flash_crash_threshold_pct": self.flash_crash_threshold_pct,
            "flash_crash_reversion_target": self.flash_crash_reversion_target,
            "min_time_remaining_sec": self.min_time_remaining_sec,
            "require_model_confirmation": self.require_model_confirmation,
        }


@dataclass
class EngineConfig:
    """
    Overall engine configuration.
    
    Includes model paths, feature flags, and global settings.
    """
    # Model paths
    surface_path: str = "research/models/probability_surface.json"
    
    # Feature flags
    use_model: bool = True                      # Enable model-based evaluation
    require_reliable: bool = True               # Require is_reliable from model
    use_conservative_edge: bool = True          # Use conservative edge estimates
    
    # Thresholds
    min_edge_threshold: float = 0.03            # Minimum edge to consider
    min_confidence_score: float = 0.5           # Minimum confidence score
    
    # Fee rates (0 for 1H markets)
    default_fee_rate: float = 0.0
    
    # Signal evaluator config
    signal_config: SignalEvaluatorConfig = field(default_factory=SignalEvaluatorConfig)
    
    @classmethod
    def from_dict(cls, d: dict) -> "EngineConfig":
        """Create config from dictionary."""
        signal_config_dict = d.get("signal_config", {})
        return cls(
            surface_path=d.get("surface_path", "research/models/probability_surface.json"),
            use_model=d.get("use_model", True),
            require_reliable=d.get("require_reliable", True),
            use_conservative_edge=d.get("use_conservative_edge", True),
            min_edge_threshold=d.get("min_edge_threshold", 0.03),
            min_confidence_score=d.get("min_confidence_score", 0.5),
            default_fee_rate=d.get("default_fee_rate", 0.0),
            signal_config=SignalEvaluatorConfig.from_dict(signal_config_dict),
        )
    
    @classmethod
    def from_bot_config(cls, bot_config) -> "EngineConfig":
        """
        Create EngineConfig from a BotConfig.
        
        Maps trading config values to engine config.
        """
        # Try to get engine section if it exists
        engine_dict = getattr(bot_config, "engine", None)
        if engine_dict and hasattr(engine_dict, "surface_path"):
            return cls.from_dict(vars(engine_dict))
        
        # Fall back to lag_arb config values
        lag_arb = getattr(bot_config, "lag_arb", None)
        if lag_arb:
            return cls(
                use_model=True,
                min_edge_threshold=0.03,
                default_fee_rate=getattr(lag_arb, "fee_rate", 0.0),
                signal_config=SignalEvaluatorConfig(
                    momentum_trigger_threshold_pct=getattr(
                        lag_arb, "momentum_trigger_threshold_pct", 0.001
                    ),
                    max_combined_price=getattr(lag_arb, "max_combined_price", 0.995),
                    expected_lag_ms=getattr(lag_arb, "expected_lag_ms", 2000),
                    max_lag_window_ms=getattr(lag_arb, "max_lag_window_ms", 5000),
                ),
            )
        
        # Default config
        return cls()
    
    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "surface_path": self.surface_path,
            "use_model": self.use_model,
            "require_reliable": self.require_reliable,
            "use_conservative_edge": self.use_conservative_edge,
            "min_edge_threshold": self.min_edge_threshold,
            "min_confidence_score": self.min_confidence_score,
            "default_fee_rate": self.default_fee_rate,
            "signal_config": self.signal_config.to_dict(),
        }
