"""Data structures for the complete-set arbitrage strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional


class Direction(Enum):
    UP = "UP"
    DOWN = "DOWN"


class ReplaceDecision(Enum):
    SKIP = "SKIP"
    PLACE = "PLACE"
    REPLACE = "REPLACE"


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

    @property
    def imbalance(self) -> Decimal:
        return self.up_shares - self.down_shares

    @property
    def up_vwap(self) -> Optional[Decimal]:
        return (self.up_cost / self.up_shares) if self.up_shares > 0 else None

    @property
    def down_vwap(self) -> Optional[Decimal]:
        return (self.down_cost / self.down_shares) if self.down_shares > 0 else None

    def add_up(self, shares: Decimal, fill_at: float, fill_price: Decimal) -> MarketInventory:
        return MarketInventory(
            up_shares=self.up_shares + shares,
            down_shares=self.down_shares,
            up_cost=self.up_cost + (shares * fill_price),
            down_cost=self.down_cost,
            last_up_fill_at=fill_at,
            last_down_fill_at=self.last_down_fill_at,
            last_up_fill_price=fill_price,
            last_down_fill_price=self.last_down_fill_price,
            last_top_up_at=self.last_top_up_at,
            last_merge_at=self.last_merge_at,
            filled_up_shares=self.filled_up_shares + shares,
            filled_down_shares=self.filled_down_shares,
        )

    def add_down(self, shares: Decimal, fill_at: float, fill_price: Decimal) -> MarketInventory:
        return MarketInventory(
            up_shares=self.up_shares,
            down_shares=self.down_shares + shares,
            up_cost=self.up_cost,
            down_cost=self.down_cost + (shares * fill_price),
            last_up_fill_at=self.last_up_fill_at,
            last_down_fill_at=fill_at,
            last_up_fill_price=self.last_up_fill_price,
            last_down_fill_price=fill_price,
            last_top_up_at=self.last_top_up_at,
            last_merge_at=self.last_merge_at,
            filled_up_shares=self.filled_up_shares,
            filled_down_shares=self.filled_down_shares + shares,
        )

    def reduce_up(self, shares: Decimal, price: Decimal) -> MarketInventory:
        new_up = max(Decimal("0"), self.up_shares - shares)
        ratio = new_up / self.up_shares if self.up_shares > 0 else Decimal("0")
        return MarketInventory(
            up_shares=new_up,
            down_shares=self.down_shares,
            up_cost=self.up_cost * ratio,
            down_cost=self.down_cost,
            last_up_fill_at=self.last_up_fill_at,
            last_down_fill_at=self.last_down_fill_at,
            last_up_fill_price=self.last_up_fill_price,
            last_down_fill_price=self.last_down_fill_price,
            last_top_up_at=self.last_top_up_at,
            last_merge_at=self.last_merge_at,
            filled_up_shares=max(Decimal("0"), self.filled_up_shares - shares),
            filled_down_shares=self.filled_down_shares,
        )

    def reduce_down(self, shares: Decimal, price: Decimal) -> MarketInventory:
        new_down = max(Decimal("0"), self.down_shares - shares)
        ratio = new_down / self.down_shares if self.down_shares > 0 else Decimal("0")
        return MarketInventory(
            up_shares=self.up_shares,
            down_shares=new_down,
            up_cost=self.up_cost,
            down_cost=self.down_cost * ratio,
            last_up_fill_at=self.last_up_fill_at,
            last_down_fill_at=self.last_down_fill_at,
            last_up_fill_price=self.last_up_fill_price,
            last_down_fill_price=self.last_down_fill_price,
            last_top_up_at=self.last_top_up_at,
            last_merge_at=self.last_merge_at,
            filled_up_shares=self.filled_up_shares,
            filled_down_shares=max(Decimal("0"), self.filled_down_shares - shares),
        )

    def mark_top_up(self, at: float) -> MarketInventory:
        return MarketInventory(
            up_shares=self.up_shares,
            down_shares=self.down_shares,
            up_cost=self.up_cost,
            down_cost=self.down_cost,
            last_up_fill_at=self.last_up_fill_at,
            last_down_fill_at=self.last_down_fill_at,
            last_up_fill_price=self.last_up_fill_price,
            last_down_fill_price=self.last_down_fill_price,
            last_top_up_at=at,
            last_merge_at=self.last_merge_at,
            filled_up_shares=self.filled_up_shares,
            filled_down_shares=self.filled_down_shares,
        )


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
