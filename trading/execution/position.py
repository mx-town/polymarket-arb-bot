"""
Position tracking for Polymarket Arbitrage Bot.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class PositionStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    EXITING = "exiting"
    CLOSED = "closed"


@dataclass
class Position:
    """Tracks a single arbitrage position"""

    market_id: str
    slug: str

    # Entry details
    entry_time: datetime
    up_shares: float
    up_entry_price: float
    down_shares: float
    down_entry_price: float

    status: PositionStatus = PositionStatus.PENDING

    # Exit details (filled on close)
    exit_time: datetime | None = None
    up_exit_price: float = 0.0
    down_exit_price: float = 0.0
    exit_reason: str | None = None

    # Partial exit tracking (side-by-side exits)
    up_exited: bool = False
    down_exited: bool = False

    @property
    def total_cost(self) -> float:
        """Total entry cost"""
        return (self.up_shares * self.up_entry_price) + (self.down_shares * self.down_entry_price)

    @property
    def guaranteed_payout(self) -> float:
        """Minimum payout at resolution (one side wins)"""
        return min(self.up_shares, self.down_shares) * 1.0

    @property
    def max_payout(self) -> float:
        """Maximum possible payout"""
        return max(self.up_shares, self.down_shares) * 1.0

    @property
    def entry_combined_price(self) -> float:
        """Combined entry price"""
        return self.up_entry_price + self.down_entry_price

    def current_value(self, up_bid: float, down_bid: float) -> float:
        """Current value if sold now"""
        return (self.up_shares * up_bid) + (self.down_shares * down_bid)

    def current_pnl(self, up_bid: float, down_bid: float) -> float:
        """Unrealized P&L"""
        return self.current_value(up_bid, down_bid) - self.total_cost

    def close(
        self,
        up_exit_price: float,
        down_exit_price: float,
        reason: str,
    ):
        """Mark position as closed"""
        self.status = PositionStatus.CLOSED
        self.exit_time = datetime.now()
        self.up_exit_price = up_exit_price
        self.down_exit_price = down_exit_price
        self.exit_reason = reason

    @property
    def realized_pnl(self) -> float:
        """Realized P&L (only valid when closed)"""
        if self.status != PositionStatus.CLOSED:
            return 0.0
        exit_value = (self.up_shares * self.up_exit_price) + (
            self.down_shares * self.down_exit_price
        )
        return exit_value - self.total_cost

    @property
    def hold_duration_seconds(self) -> float | None:
        """Duration position was held"""
        if not self.exit_time:
            return (datetime.now() - self.entry_time).total_seconds()
        return (self.exit_time - self.entry_time).total_seconds()

    @property
    def is_partially_exited(self) -> bool:
        """Check if one side has been exited"""
        return self.up_exited != self.down_exited

    @property
    def remaining_side(self) -> str | None:
        """Which side still has shares"""
        if self.up_exited and not self.down_exited:
            return "down"
        if self.down_exited and not self.up_exited:
            return "up"
        return None

    def partial_exit(self, side: str, exit_price: float) -> float:
        """Mark one side as exited, return PnL for that side"""
        if side == "up":
            self.up_exited = True
            self.up_exit_price = exit_price
            return (exit_price - self.up_entry_price) * self.up_shares
        else:
            self.down_exited = True
            self.down_exit_price = exit_price
            return (exit_price - self.down_entry_price) * self.down_shares


class PositionManager:
    """Manages all open positions"""

    def __init__(self):
        self.positions: dict[str, Position] = {}  # market_id -> Position
        self.closed_positions: list[Position] = []

    def has_position(self, market_id: str) -> bool:
        """Check if we have an open position in a market"""
        return market_id in self.positions

    def get_position(self, market_id: str) -> Position | None:
        """Get position for a market"""
        return self.positions.get(market_id)

    def open_position(
        self,
        market_id: str,
        slug: str,
        up_shares: float,
        up_entry_price: float,
        down_shares: float,
        down_entry_price: float,
    ) -> Position:
        """Open a new position"""
        position = Position(
            market_id=market_id,
            slug=slug,
            entry_time=datetime.now(),
            up_shares=up_shares,
            up_entry_price=up_entry_price,
            down_shares=down_shares,
            down_entry_price=down_entry_price,
            status=PositionStatus.OPEN,
        )
        self.positions[market_id] = position
        return position

    def close_position(
        self,
        market_id: str,
        up_exit_price: float,
        down_exit_price: float,
        reason: str,
    ) -> Position | None:
        """Close a position"""
        position = self.positions.pop(market_id, None)
        if position:
            position.close(up_exit_price, down_exit_price, reason)
            self.closed_positions.append(position)
        return position

    def partial_exit_position(
        self,
        market_id: str,
        side: str,
        exit_price: float,
    ) -> tuple[Position | None, float]:
        """
        Exit one side of a position.

        Args:
            market_id: Market ID
            side: "up" or "down"
            exit_price: Exit price for this side

        Returns:
            Tuple of (position, pnl_for_this_side)
        """
        position = self.positions.get(market_id)
        if not position:
            return None, 0.0

        pnl = position.partial_exit(side, exit_price)

        # If both sides now exited, move to closed
        if position.up_exited and position.down_exited:
            position.status = PositionStatus.CLOSED
            position.exit_time = datetime.now()
            position.exit_reason = "partial_exits"
            self.closed_positions.append(position)
            del self.positions[market_id]

        return position, pnl

    def get_open_positions(self) -> list[Position]:
        """Get all open positions"""
        return list(self.positions.values())

    def total_exposure(self) -> float:
        """Total USDC currently exposed"""
        return sum(p.total_cost for p in self.positions.values())

    def total_realized_pnl(self) -> float:
        """Total realized P&L from closed positions"""
        return sum(p.realized_pnl for p in self.closed_positions)

    def total_unrealized_pnl(self, market_prices: dict[str, tuple[float, float]]) -> float:
        """
        Total unrealized P&L.

        Args:
            market_prices: Dict of market_id -> (up_bid, down_bid)
        """
        total = 0.0
        for market_id, position in self.positions.items():
            prices = market_prices.get(market_id)
            if prices:
                total += position.current_pnl(prices[0], prices[1])
        return total
