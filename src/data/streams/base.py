"""
Base data structures for price and order book updates.

Thread-safe dataclasses for passing between stream threads and synchronizer.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class StreamSource(Enum):
    """Source of a price update."""

    BINANCE_DIRECT = "binance_direct"
    RTDS_BINANCE = "rtds_binance"
    RTDS_CHAINLINK = "rtds_chainlink"
    CHAINLINK_RPC = "chainlink_rpc"
    CLOB = "clob"


@dataclass(frozen=True, slots=True)
class PriceUpdate:
    """
    Immutable price update from any source.

    Attributes:
        source: Which feed this came from
        symbol: Trading pair (e.g., "BTCUSDT")
        price: Current price
        timestamp_ms: Unix timestamp in milliseconds
        sequence: Optional sequence number for ordering
    """

    source: StreamSource
    symbol: str
    price: float
    timestamp_ms: int
    sequence: int | None = None

    @property
    def timestamp_sec(self) -> float:
        """Timestamp in seconds."""
        return self.timestamp_ms / 1000.0


@dataclass(frozen=True, slots=True)
class OrderBookUpdate:
    """
    Immutable order book update from CLOB.

    Attributes:
        token_id: Polymarket token ID
        best_bid: Best bid price
        best_ask: Best ask price
        bid_size: Size at best bid
        ask_size: Size at best ask
        timestamp_ms: Unix timestamp in milliseconds
    """

    token_id: str
    best_bid: float
    best_ask: float
    bid_size: float
    ask_size: float
    timestamp_ms: int

    @property
    def mid_price(self) -> float:
        """Mid-market price."""
        if self.best_bid > 0 and self.best_ask > 0:
            return (self.best_bid + self.best_ask) / 2
        return self.best_ask if self.best_ask > 0 else self.best_bid

    @property
    def spread(self) -> float:
        """Bid-ask spread."""
        if self.best_bid > 0 and self.best_ask > 0:
            return self.best_ask - self.best_bid
        return 0.0

    @property
    def timestamp_sec(self) -> float:
        """Timestamp in seconds."""
        return self.timestamp_ms / 1000.0


@dataclass
class SynchronizedSnapshot:
    """
    Aligned snapshot of all data sources at a point in time.

    Attributes:
        timestamp_ms: Snapshot timestamp
        binance_direct: Latest Binance direct price
        rtds_binance: Latest RTDS Binance price
        rtds_chainlink: Latest RTDS Chainlink price
        chainlink_rpc: Latest Chainlink RPC price
        clob_books: Dict of token_id -> OrderBookUpdate
        lag_binance_to_chainlink_ms: Calculated lag
    """

    timestamp_ms: int
    binance_direct: PriceUpdate | None = None
    rtds_binance: PriceUpdate | None = None
    rtds_chainlink: PriceUpdate | None = None
    chainlink_rpc: PriceUpdate | None = None
    clob_books: dict[str, OrderBookUpdate] = field(default_factory=dict)

    @property
    def binance_price(self) -> float | None:
        """Best available Binance price."""
        if self.binance_direct:
            return self.binance_direct.price
        if self.rtds_binance:
            return self.rtds_binance.price
        return None

    @property
    def chainlink_price(self) -> float | None:
        """Best available Chainlink price."""
        if self.rtds_chainlink:
            return self.rtds_chainlink.price
        if self.chainlink_rpc:
            return self.chainlink_rpc.price
        return None

    @property
    def lag_binance_to_chainlink_ms(self) -> int | None:
        """Lag between Binance and Chainlink updates."""
        binance_ts = None
        chainlink_ts = None

        if self.binance_direct:
            binance_ts = self.binance_direct.timestamp_ms
        elif self.rtds_binance:
            binance_ts = self.rtds_binance.timestamp_ms

        if self.rtds_chainlink:
            chainlink_ts = self.rtds_chainlink.timestamp_ms
        elif self.chainlink_rpc:
            chainlink_ts = self.chainlink_rpc.timestamp_ms

        if binance_ts and chainlink_ts:
            return binance_ts - chainlink_ts
        return None

    @property
    def price_divergence_pct(self) -> float | None:
        """Percentage divergence between Binance and Chainlink."""
        binance = self.binance_price
        chainlink = self.chainlink_price
        if binance and chainlink and chainlink > 0:
            return (binance - chainlink) / chainlink * 100
        return None


@dataclass
class StreamStats:
    """Statistics for a single stream."""

    source: StreamSource
    update_count: int = 0
    first_update_ms: int | None = None
    last_update_ms: int | None = None
    min_price: float | None = None
    max_price: float | None = None

    def record(self, update: PriceUpdate) -> None:
        """Record an update."""
        self.update_count += 1
        if self.first_update_ms is None:
            self.first_update_ms = update.timestamp_ms
        self.last_update_ms = update.timestamp_ms

        if self.min_price is None or update.price < self.min_price:
            self.min_price = update.price
        if self.max_price is None or update.price > self.max_price:
            self.max_price = update.price

    @property
    def duration_sec(self) -> float | None:
        """Duration of data collection."""
        if self.first_update_ms and self.last_update_ms:
            return (self.last_update_ms - self.first_update_ms) / 1000.0
        return None

    @property
    def updates_per_sec(self) -> float | None:
        """Average updates per second."""
        duration = self.duration_sec
        if duration and duration > 0:
            return self.update_count / duration
        return None
