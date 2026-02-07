"""Configuration loading for the complete-set strategy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class CompleteSetConfig:
    enabled: bool = True
    dry_run: bool = True
    refresh_millis: int = 500
    min_replace_millis: int = 5000
    min_replace_ticks: int = 2
    improve_ticks: int = 2
    assets: tuple[str, ...] = ("bitcoin", "ethereum")

    # Time window
    min_seconds_to_end: int = 0
    max_seconds_to_end: int = 3600
    order_cancel_buffer_sec: int = 45

    # Edge & skew
    min_edge: Decimal = Decimal("0.01")
    max_skew_ticks: int = 1
    imbalance_for_max_skew: Decimal = Decimal("200")

    # Bankroll
    bankroll_usd: Decimal = Decimal("100")
    max_order_bankroll_fraction: Decimal = Decimal("0.05")
    max_total_bankroll_fraction: Decimal = Decimal("0.50")
    _max_shares_per_market: Decimal = Decimal("0")

    @property
    def max_shares_per_market(self) -> Decimal:
        if self._max_shares_per_market > Decimal("0"):
            return self._max_shares_per_market
        return Decimal(int(self.bankroll_usd * self.max_total_bankroll_fraction))

    # Top-up
    top_up_enabled: bool = True
    top_up_seconds_to_end: int = 60
    top_up_min_shares: Decimal = Decimal("10")
    fast_top_up_enabled: bool = True
    fast_top_up_min_seconds: int = 3
    fast_top_up_max_seconds: int = 120
    fast_top_up_cooldown_millis: int = 15000
    fast_top_up_min_edge: Decimal = Decimal("0.0")

    # Taker mode
    taker_enabled: bool = False
    taker_max_edge: Decimal = Decimal("0.015")
    taker_max_spread: Decimal = Decimal("0.02")


def load_complete_set_config(raw: dict[str, Any]) -> CompleteSetConfig:
    """Load CompleteSetConfig from config.yaml's complete_set section."""
    cs = raw.get("complete_set", {})
    if not cs:
        return CompleteSetConfig()

    assets = cs.get("assets", ["bitcoin", "ethereum"])

    return CompleteSetConfig(
        enabled=cs.get("enabled", True),
        dry_run=cs.get("dry_run", True),
        refresh_millis=cs.get("refresh_millis", 500),
        min_replace_millis=cs.get("min_replace_millis", 5000),
        min_replace_ticks=cs.get("min_replace_ticks", 2),
        improve_ticks=cs.get("improve_ticks", 2),
        assets=tuple(assets),
        min_seconds_to_end=cs.get("min_seconds_to_end", 0),
        max_seconds_to_end=cs.get("max_seconds_to_end", 3600),
        order_cancel_buffer_sec=cs.get("order_cancel_buffer_sec", 45),
        min_edge=Decimal(str(cs.get("min_edge", "0.01"))),
        max_skew_ticks=cs.get("max_skew_ticks", 1),
        imbalance_for_max_skew=Decimal(str(cs.get("imbalance_for_max_skew", "200"))),
        bankroll_usd=Decimal(str(cs.get("bankroll_usd", "100"))),
        max_order_bankroll_fraction=Decimal(str(cs.get("max_order_bankroll_fraction", "0.05"))),
        max_total_bankroll_fraction=Decimal(str(cs.get("max_total_bankroll_fraction", "0.50"))),
        _max_shares_per_market=Decimal(str(cs.get("max_shares_per_market", "0"))),
        top_up_enabled=cs.get("top_up_enabled", True),
        top_up_seconds_to_end=cs.get("top_up_seconds_to_end", 60),
        top_up_min_shares=Decimal(str(cs.get("top_up_min_shares", "10"))),
        fast_top_up_enabled=cs.get("fast_top_up_enabled", True),
        fast_top_up_min_seconds=cs.get("fast_top_up_min_seconds", 3),
        fast_top_up_max_seconds=cs.get("fast_top_up_max_seconds", 120),
        fast_top_up_cooldown_millis=cs.get("fast_top_up_cooldown_millis", 15000),
        fast_top_up_min_edge=Decimal(str(cs.get("fast_top_up_min_edge", "0.0"))),
        taker_enabled=cs.get("taker_enabled", False),
        taker_max_edge=Decimal(str(cs.get("taker_max_edge", "0.015"))),
        taker_max_spread=Decimal(str(cs.get("taker_max_spread", "0.02"))),
    )
