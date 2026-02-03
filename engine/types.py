"""
Unified signal types for the shared engine.

These types are used by both trading and research modules for consistent
signal representation across the system.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Direction(Enum):
    """Direction of predicted price movement."""
    UP = "up"
    DOWN = "down"
    NEUTRAL = "neutral"


class SignalTier(Enum):
    """
    Signal priority tiers (lower number = higher priority).
    
    DUTCH_BOOK: Zero-risk arbitrage (combined < 1.0)
    LAG_ARB: Momentum-based lag arbitrage
    MOMENTUM: Directional momentum signals
    FLASH_CRASH: Contrarian reversion signals
    """
    DUTCH_BOOK = 1
    LAG_ARB = 2
    MOMENTUM = 3
    FLASH_CRASH = 4


@dataclass
class MarketContext:
    """
    Market state snapshot at signal time.
    
    Captures order book prices and timing information.
    """
    timestamp_ms: int
    up_price: float          # best ask for UP token
    down_price: float        # best ask for DOWN token
    up_bid: float            # best bid for UP token
    down_bid: float          # best bid for DOWN token
    combined_ask: float      # up_price + down_price
    combined_bid: float      # up_bid + down_bid
    time_remaining_sec: int  # seconds until market resolution
    session: str             # trading session (asia, europe, america)
    
    @property
    def spread(self) -> float:
        """Spread between combined ask and bid."""
        return self.combined_ask - self.combined_bid
    
    @property
    def is_dutch_book(self) -> bool:
        """True if combined ask < 1.0 (arbitrage opportunity)."""
        return self.combined_ask < 1.0


@dataclass
class ModelOutput:
    """
    Output from the probability model (ProbabilitySurface + EdgeCalculator).
    
    Contains probability estimates, confidence metrics, and trading recommendations.
    """
    prob_up: float              # Model's probability of UP outcome
    ci_lower: float             # Lower bound of confidence interval
    ci_upper: float             # Upper bound of confidence interval
    is_reliable: bool           # True if sample size sufficient
    edge_after_fees: float      # Expected edge after fees
    confidence_score: float     # Model confidence (0-1)
    kelly_fraction: float       # Optimal bet size fraction
    direction: Direction        # Recommended direction
    deviation_pct: float        # Price deviation from open
    vol_regime: str             # Volatility regime (low, medium, high)
    
    @property
    def has_edge(self) -> bool:
        """True if model indicates positive edge."""
        return self.edge_after_fees > 0 and self.is_reliable


@dataclass
class UnifiedSignal:
    """
    Unified signal type combining momentum, market, and model data.
    
    This is the primary signal type passed between components.
    All fields except momentum data are optional to support
    different signal generation contexts.
    """
    # Identity
    tier: SignalTier
    direction: Direction
    symbol: str                     # e.g., "BTCUSDT"
    market_id: Optional[str]        # Polymarket condition_id
    timestamp: datetime
    timestamp_ms: int
    
    # Momentum data (from PriceTracker -- always present)
    momentum: float                 # Current momentum value
    candle_open: float              # Candle open price
    spot_price: float               # Current spot price
    move_from_open: float           # Percentage move from open
    
    # Market context (from CLOB -- present when market context available)
    market: Optional[MarketContext] = None
    
    # Model output (from ProbabilitySurface -- None when no model loaded)
    model: Optional[ModelOutput] = None
    
    # Computed fields
    expected_edge: float = 0.0
    confidence: float = 0.0
    metadata: dict = field(default_factory=dict)
    
    @property
    def is_actionable(self) -> bool:
        """
        True if this signal should be acted upon.
        
        Requires:
        - Non-neutral direction
        - Sufficient confidence (>= 0.4)
        - Positive expected edge
        """
        return (
            self.direction != Direction.NEUTRAL
            and self.confidence >= 0.4
            and self.expected_edge > 0
        )
    
    @property
    def is_dutch_book(self) -> bool:
        """True if this is a Dutch book (risk-free) opportunity."""
        return self.tier == SignalTier.DUTCH_BOOK
    
    @property
    def priority(self) -> int:
        """Signal priority (lower = higher priority)."""
        return self.tier.value
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "tier": self.tier.name,
            "direction": self.direction.value,
            "symbol": self.symbol,
            "market_id": self.market_id,
            "timestamp": self.timestamp.isoformat(),
            "timestamp_ms": self.timestamp_ms,
            "momentum": self.momentum,
            "candle_open": self.candle_open,
            "spot_price": self.spot_price,
            "move_from_open": self.move_from_open,
            "market": {
                "combined_ask": self.market.combined_ask,
                "combined_bid": self.market.combined_bid,
                "time_remaining_sec": self.market.time_remaining_sec,
                "session": self.market.session,
            } if self.market else None,
            "model": {
                "prob_up": self.model.prob_up,
                "edge_after_fees": self.model.edge_after_fees,
                "kelly_fraction": self.model.kelly_fraction,
                "is_reliable": self.model.is_reliable,
            } if self.model else None,
            "expected_edge": self.expected_edge,
            "confidence": self.confidence,
            "is_actionable": self.is_actionable,
        }
