"""Data structures and shared constants for the complete-set arbitrage strategy."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
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
    market_type: str  # "updown-15m" or "up-or-down"
    condition_id: str = ""  # needed for on-chain redemption contract call
    neg_risk: bool = False  # NegRisk markets use NegRiskAdapter for merge/redeem


@dataclass
class MarketInventory:
    up_shares: Decimal = field(default_factory=lambda: Decimal("0"))
    down_shares: Decimal = field(default_factory=lambda: Decimal("0"))
    up_cost: Decimal = field(default_factory=lambda: Decimal("0"))
    down_cost: Decimal = field(default_factory=lambda: Decimal("0"))
    last_up_fill_at: Optional[float] = None
    last_down_fill_at: Optional[float] = None
    last_up_fill_price: Optional[Decimal] = None
    last_down_fill_price: Optional[Decimal] = None
    last_top_up_at: Optional[float] = None
    last_merge_at: Optional[float] = None
    filled_up_shares: Decimal = field(default_factory=lambda: Decimal("0"))
    filled_down_shares: Decimal = field(default_factory=lambda: Decimal("0"))
    entry_dynamic_edge: Decimal = field(default_factory=lambda: Decimal("0"))
    prior_merge_pnl: Decimal = field(default_factory=lambda: Decimal("0"))
    bootstrapped_up: bool = False
    bootstrapped_down: bool = False

    @property
    def imbalance(self) -> Decimal:
        return self.up_shares - self.down_shares

    @property
    def up_vwap(self) -> Optional[Decimal]:
        if self.up_shares <= 0:
            return None
        return self.up_cost / self.up_shares

    @property
    def down_vwap(self) -> Optional[Decimal]:
        if self.down_shares <= 0:
            return None
        return self.down_cost / self.down_shares

    def add_up(self, shares: Decimal, fill_at: float, fill_price: Decimal) -> MarketInventory:
        return replace(
            self,
            up_shares=self.up_shares + shares,
            up_cost=self.up_cost + (shares * fill_price),
            last_up_fill_at=fill_at,
            last_up_fill_price=fill_price,
            filled_up_shares=self.filled_up_shares + shares,
            bootstrapped_up=False,
        )

    def add_down(self, shares: Decimal, fill_at: float, fill_price: Decimal) -> MarketInventory:
        return replace(
            self,
            down_shares=self.down_shares + shares,
            down_cost=self.down_cost + (shares * fill_price),
            last_down_fill_at=fill_at,
            last_down_fill_price=fill_price,
            filled_down_shares=self.filled_down_shares + shares,
            bootstrapped_down=False,
        )

    def reduce_up(self, shares: Decimal, price: Decimal) -> MarketInventory:
        new_up = max(ZERO, self.up_shares - shares)
        ratio = new_up / self.up_shares if self.up_shares > 0 else ZERO
        return replace(
            self,
            up_shares=new_up,
            up_cost=self.up_cost * ratio,
            filled_up_shares=max(ZERO, self.filled_up_shares - shares),
        )

    def reduce_down(self, shares: Decimal, price: Decimal) -> MarketInventory:
        new_down = max(ZERO, self.down_shares - shares)
        ratio = new_down / self.down_shares if self.down_shares > 0 else ZERO
        return replace(
            self,
            down_shares=new_down,
            down_cost=self.down_cost * ratio,
            filled_down_shares=max(ZERO, self.filled_down_shares - shares),
        )

    def mark_top_up(self, at: float) -> MarketInventory:
        return replace(self, last_top_up_at=at)


@dataclass
class PendingRedemption:
    market: GabagoolMarket
    inventory: MarketInventory
    eligible_at: float  # end_time + 60 (wait for on-chain settlement)
    attempts: int = 0
    last_attempt_at: float = 0.0


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
