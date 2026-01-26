"""
Signal detection base classes and data structures.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from src.market.state import MarketState


class SignalType(Enum):
    ENTRY = "entry"
    EXIT = "exit"
    HOLD = "hold"


class ExitReason(Enum):
    RESOLUTION = "resolution"
    PUMP_EXIT = "pump_exit"
    EARLY_EXIT = "early_exit"
    STOP_LOSS = "stop_loss"
    TIME_LIMIT = "time_limit"


@dataclass
class ArbOpportunity:
    """Represents an arbitrage opportunity"""

    market_id: str
    market_name: str
    slug: str

    up_token_id: str
    down_token_id: str

    up_price: float  # Best ask
    down_price: float  # Best ask

    total_cost: float  # up_price + down_price
    gross_profit: float  # 1.0 - total_cost
    net_profit: float  # After fees

    timestamp: datetime

    # Optional metadata
    time_to_resolution: float | None = None
    confidence: float = 1.0  # For lag arb signals

    @property
    def profit_pct(self) -> float:
        """Net profit as percentage"""
        if self.total_cost == 0:
            return 0.0
        return self.net_profit / self.total_cost

    @classmethod
    def from_market(
        cls,
        market: MarketState,
        fee_rate: float = 0.02,
    ) -> "ArbOpportunity":
        """Create opportunity from market state"""
        total_cost = market.combined_ask
        gross_profit = 1.0 - total_cost
        estimated_fees = total_cost * fee_rate
        net_profit = gross_profit - estimated_fees

        return cls(
            market_id=market.market_id,
            market_name=market.question,
            slug=market.slug,
            up_token_id=market.up_token_id,
            down_token_id=market.down_token_id,
            up_price=market.up_best_ask,
            down_price=market.down_best_ask,
            total_cost=total_cost,
            gross_profit=gross_profit,
            net_profit=net_profit,
            timestamp=datetime.now(),
            time_to_resolution=market.time_to_resolution,
        )


@dataclass
class Signal:
    """Trading signal output"""

    signal_type: SignalType
    market_id: str
    opportunity: ArbOpportunity | None = None
    exit_reason: ExitReason | None = None
    confidence: float = 1.0
    timestamp: datetime = None

    def __post_init__(self):
        if self.timestamp is None:
            self.timestamp = datetime.now()


class SignalDetector(ABC):
    """Base class for signal detection strategies"""

    @abstractmethod
    def check_entry(self, market: MarketState) -> Signal | None:
        """Check if market has entry signal"""
        pass

    @abstractmethod
    def check_exit(self, market: MarketState, entry_price: float) -> Signal | None:
        """Check if position should exit"""
        pass
