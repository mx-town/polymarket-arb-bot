"""Data models for the observer bot."""

from __future__ import annotations

from dataclasses import dataclass, field

# ANSI colors for log highlights
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_DIM = "\033[2m"
C_BOLD = "\033[1m"
C_RESET = "\033[0m"


@dataclass(frozen=True)
class ObservedTrade:
    timestamp: str  # ISO timestamp from Activity API
    side: str  # "BUY" or "SELL"
    price: float
    size: float
    usdc_size: float
    outcome: str  # "Up" or "Down"
    outcome_index: int  # 0 or 1
    tx_hash: str
    slug: str  # market slug
    event_slug: str
    condition_id: str
    asset: str  # token ID
    title: str
    role: str = ""  # "MAKER" or "TAKER", filled later by onchain decoder


@dataclass(frozen=True)
class ObservedMerge:
    timestamp: int  # unix timestamp from Etherscan
    tx_hash: str
    token_id: str
    shares: float  # tokenValue burned
    block_number: int


@dataclass(frozen=True)
class ObservedPosition:
    asset: str
    size: float
    avg_price: float
    cash_pnl: float
    current_value: float
    cur_price: float
    redeemable: bool
    mergeable: bool
    slug: str
    outcome: str
    outcome_index: int
    opposite_asset: str
    end_date: str


@dataclass
class MarketWindow:
    slug: str
    event_slug: str = ""
    title: str = ""
    trades: list[ObservedTrade] = field(default_factory=list)
    merges: list[ObservedMerge] = field(default_factory=list)
    up_vwap: float = 0.0
    down_vwap: float = 0.0
    up_shares: float = 0.0
    down_shares: float = 0.0
    up_cost: float = 0.0
    down_cost: float = 0.0
    combined_cost: float = 0.0
    estimated_edge: float = 0.0
    first_trade_at: str = ""
    last_trade_at: str = ""
    hedge_delay_sec: float = 0.0  # seconds between first UP and first DOWN trade
    merged_shares: float = 0.0
    status: str = "OPEN"  # "OPEN", "HEDGED", "MERGED", "CLOSED"
