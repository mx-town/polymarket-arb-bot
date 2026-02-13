"""Configuration loading for the complete-set strategy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class CompleteSetConfig:
    enabled: bool = True
    dry_run: bool = True
    refresh_millis: int = 2000
    assets: tuple[str, ...] = ("bitcoin", "ethereum")

    # Time window
    min_seconds_to_end: int = 0
    max_seconds_to_end: int = 3600
    no_new_orders_sec: int = 45

    # Edge
    min_edge: Decimal = Decimal("0.01")

    # Bankroll
    bankroll_usd: Decimal = Decimal("100")
    max_order_bankroll_fraction: Decimal = Decimal("0.05")
    max_total_bankroll_fraction: Decimal = Decimal("0.50")

    # Merge
    min_merge_shares: Decimal = Decimal("5")

    # Mean reversion (Binance BTC feed)
    mean_reversion_enabled: bool = False
    mr_deviation_threshold: Decimal = Decimal("0.0004")   # 0.04%
    mr_max_range_pct: Decimal = Decimal("0.0010")         # 0.10% — skip trending candles
    mr_entry_window_sec: int = 240                        # last 4 minutes

    # Stop hunt (early entry, minutes 2-5)
    sh_entry_start_sec: int = 780     # start looking at minute 2 (780s left)
    sh_entry_end_sec: int = 600       # stop at minute 5 (600s left)

    # Volume imbalance (Binance aggTrade feed)
    volume_imbalance_enabled: bool = False
    volume_imbalance_threshold: Decimal = Decimal("0.15")  # +-15% imbalance
    volume_min_btc: Decimal = Decimal("50")                # min 50 BTC in window
    volume_short_window_sec: int = 30
    volume_medium_window_sec: int = 120


def load_complete_set_config(raw: dict[str, Any]) -> CompleteSetConfig:
    """Load CompleteSetConfig from config.yaml's complete_set section."""
    cs = raw.get("complete_set", {})
    if not cs:
        return CompleteSetConfig()

    assets = cs.get("assets", ["bitcoin", "ethereum"])

    return CompleteSetConfig(
        enabled=cs.get("enabled", True),
        dry_run=cs.get("dry_run", True),
        refresh_millis=cs.get("refresh_millis", 2000),
        assets=tuple(assets),
        min_seconds_to_end=cs.get("min_seconds_to_end", 0),
        max_seconds_to_end=cs.get("max_seconds_to_end", 3600),
        no_new_orders_sec=cs.get("no_new_orders_sec", 45),
        min_edge=Decimal(str(cs.get("min_edge", "0.01"))),
        bankroll_usd=Decimal(str(cs.get("bankroll_usd", "100"))),
        max_order_bankroll_fraction=Decimal(str(cs.get("max_order_bankroll_fraction", "0.05"))),
        max_total_bankroll_fraction=Decimal(str(cs.get("max_total_bankroll_fraction", "0.50"))),
        min_merge_shares=Decimal(str(cs.get("min_merge_shares", "5"))),
        # Mean reversion
        mean_reversion_enabled=cs.get("mean_reversion_enabled", False),
        mr_deviation_threshold=Decimal(str(cs.get("mr_deviation_threshold", "0.0004"))),
        mr_max_range_pct=Decimal(str(cs.get("mr_max_range_pct", "0.0010"))),
        mr_entry_window_sec=int(cs.get("mr_entry_window_sec", 240)),
        # Stop hunt
        sh_entry_start_sec=int(cs.get("sh_entry_start_sec", 780)),
        sh_entry_end_sec=int(cs.get("sh_entry_end_sec", 600)),
        # Volume imbalance
        volume_imbalance_enabled=cs.get("volume_imbalance_enabled", False),
        volume_imbalance_threshold=Decimal(str(cs.get("volume_imbalance_threshold", "0.15"))),
        volume_min_btc=Decimal(str(cs.get("volume_min_btc", "50"))),
        volume_short_window_sec=int(cs.get("volume_short_window_sec", 30)),
        volume_medium_window_sec=int(cs.get("volume_medium_window_sec", 120)),
    )
