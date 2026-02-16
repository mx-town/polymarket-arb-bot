"""Shared data structures and constants for Polymarket strategies."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional

# Shared Decimal constants
ZERO = Decimal("0")
ONE = Decimal("1")

# ANSI colors for log highlights
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"
C_RESET = "\033[0m"


class Direction(Enum):
    UP = "UP"
    DOWN = "DOWN"


@dataclass(frozen=True)
class TopOfBook:
    best_bid: Optional[Decimal]
    best_ask: Optional[Decimal]
    best_bid_size: Optional[Decimal]
    best_ask_size: Optional[Decimal]
    updated_at: float  # time.time()


@dataclass(frozen=True)
class GabagoolMarket:
    slug: str
    up_token_id: str
    down_token_id: str
    end_time: float  # epoch seconds
    market_type: str  # "updown-5m", "updown-15m" or "up-or-down"
    condition_id: str = ""  # needed for on-chain redemption contract call
    neg_risk: bool = False  # NegRisk markets use NegRiskAdapter for merge/redeem


@dataclass(frozen=True)
class OrderState:
    order_id: str
    market: Optional[GabagoolMarket]
    token_id: str
    direction: Optional[Direction]
    price: Decimal
    size: Decimal
    placed_at: float  # time.time()
    side: str = "BUY"
    matched_size: Decimal = field(default_factory=lambda: Decimal("0"))
    last_status_check_at: Optional[float] = None
    seconds_to_end_at_entry: Optional[int] = None
    reserved_hedge_notional: Decimal = field(default_factory=lambda: Decimal("0"))
    entry_dynamic_edge: Decimal = field(default_factory=lambda: Decimal("0"))
    consumed_crossing: Decimal = field(default_factory=lambda: Decimal("0"))
