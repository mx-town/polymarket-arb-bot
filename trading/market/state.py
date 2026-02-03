"""
Market state management for Polymarket Arbitrage Bot.

Tracks real-time state of Up/Down markets from WebSocket updates.
"""

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class MarketStatus(Enum):
    ACTIVE = "active"
    CLOSED = "closed"
    RESOLVED = "resolved"


@dataclass
class MarketState:
    """Real-time state of a single Up/Down market"""

    # Identifiers
    market_id: str  # Condition ID
    slug: str
    question: str

    # Token IDs
    up_token_id: str
    down_token_id: str

    # Timing
    resolution_time: datetime | None = None
    status: MarketStatus = MarketStatus.ACTIVE

    # Real-time prices (from WebSocket)
    up_best_bid: float = 0.0
    up_best_ask: float = 0.0
    up_bid_size: float = 0.0
    up_ask_size: float = 0.0

    down_best_bid: float = 0.0
    down_best_ask: float = 0.0
    down_bid_size: float = 0.0
    down_ask_size: float = 0.0

    # Timestamps
    last_update: datetime | None = None
    last_up_update: datetime | None = None
    last_down_update: datetime | None = None

    @property
    def combined_ask(self) -> float:
        """Total cost to buy both sides"""
        return self.up_best_ask + self.down_best_ask

    @property
    def combined_bid(self) -> float:
        """Total value if selling both sides"""
        return self.up_best_bid + self.down_best_bid

    @property
    def potential_profit(self) -> float:
        """Gross profit if combined_ask < 1.0"""
        return 1.0 - self.combined_ask

    @property
    def spread_up(self) -> float:
        """Spread on UP side"""
        if self.up_best_bid == 0:
            return 1.0
        return (self.up_best_ask - self.up_best_bid) / self.up_best_bid

    @property
    def spread_down(self) -> float:
        """Spread on DOWN side"""
        if self.down_best_bid == 0:
            return 1.0
        return (self.down_best_ask - self.down_best_bid) / self.down_best_bid

    @property
    def time_to_resolution(self) -> float | None:
        """Seconds until resolution"""
        if not self.resolution_time:
            return None
        return (self.resolution_time - datetime.now()).total_seconds()

    @property
    def is_valid(self) -> bool:
        """Check if we have valid price data"""
        return (
            self.up_best_ask > 0
            and self.down_best_ask > 0
            and self.up_best_bid > 0
            and self.down_best_bid > 0
        )

    def update_up(self, best_bid: float, best_ask: float, bid_size: float = 0, ask_size: float = 0):
        """Update UP side prices"""
        self.up_best_bid = best_bid
        self.up_best_ask = best_ask
        self.up_bid_size = bid_size
        self.up_ask_size = ask_size
        self.last_up_update = datetime.now()
        self.last_update = self.last_up_update

    def update_down(
        self, best_bid: float, best_ask: float, bid_size: float = 0, ask_size: float = 0
    ):
        """Update DOWN side prices"""
        self.down_best_bid = best_bid
        self.down_best_ask = best_ask
        self.down_bid_size = bid_size
        self.down_ask_size = ask_size
        self.last_down_update = datetime.now()
        self.last_update = self.last_down_update


class MarketStateManager:
    """Manages collection of market states"""

    def __init__(self):
        self.markets: dict[str, MarketState] = {}
        self._token_to_market: dict[str, str] = {}  # token_id -> market_id
        self._token_is_up: dict[str, bool] = {}  # token_id -> is_up_side

    def add_market(self, state: MarketState):
        """Add or update a market"""
        self.markets[state.market_id] = state
        self._token_to_market[state.up_token_id] = state.market_id
        self._token_to_market[state.down_token_id] = state.market_id
        self._token_is_up[state.up_token_id] = True
        self._token_is_up[state.down_token_id] = False

    def get_market(self, market_id: str) -> MarketState | None:
        """Get market by ID"""
        return self.markets.get(market_id)

    def remove_market(self, market_id: str) -> bool:
        """Remove a market and its token mappings. Returns True if removed."""
        market = self.markets.get(market_id)
        if not market:
            return False

        # Remove token mappings
        self._token_to_market.pop(market.up_token_id, None)
        self._token_to_market.pop(market.down_token_id, None)
        self._token_is_up.pop(market.up_token_id, None)
        self._token_is_up.pop(market.down_token_id, None)

        # Remove market
        del self.markets[market_id]
        return True

    def get_market_by_token(self, token_id: str) -> MarketState | None:
        """Get market by token ID"""
        market_id = self._token_to_market.get(token_id)
        if market_id:
            return self.markets.get(market_id)
        return None

    def is_up_token(self, token_id: str) -> bool:
        """Check if token is UP side"""
        return self._token_is_up.get(token_id, False)

    def update_from_book(
        self,
        token_id: str,
        best_bid: float,
        best_ask: float,
        bid_size: float = 0,
        ask_size: float = 0,
    ):
        """Update market from order book data"""
        market = self.get_market_by_token(token_id)
        if not market:
            return

        if self.is_up_token(token_id):
            market.update_up(best_bid, best_ask, bid_size, ask_size)
        else:
            market.update_down(best_bid, best_ask, bid_size, ask_size)

    def get_all_token_ids(self) -> list[str]:
        """Get all token IDs for WebSocket subscription"""
        token_ids = []
        for market in self.markets.values():
            token_ids.append(market.up_token_id)
            token_ids.append(market.down_token_id)
        return token_ids

    def get_valid_markets(self) -> list[MarketState]:
        """Get markets with valid price data"""
        return [m for m in self.markets.values() if m.is_valid]

    def get_active_markets(self) -> list[MarketState]:
        """Get active markets only"""
        return [m for m in self.markets.values() if m.status == MarketStatus.ACTIVE]
