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

    # Volatility filter
    volatility_filter_enabled: bool = True
    vol_lookback_seconds: float = 120.0
    vol_min_samples: int = 20
    vol_min_swing: Decimal = Decimal("0.05")
    vol_max_efficiency: Decimal = Decimal("0.60")
    vol_min_reversals: int = 2

    # Momentum check
    momentum_check_enabled: bool = True
    momentum_lookback_samples: int = 6
    momentum_bounce_threshold: Decimal = Decimal("0.01")

    # Stop-loss
    stop_loss_enabled: bool = True
    stop_loss_cents: Decimal = Decimal("0.10")


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
        # Volatility filter
        volatility_filter_enabled=cs.get("volatility_filter_enabled", True),
        vol_lookback_seconds=float(cs.get("vol_lookback_seconds", 120.0)),
        vol_min_samples=int(cs.get("vol_min_samples", 20)),
        vol_min_swing=Decimal(str(cs.get("vol_min_swing", "0.05"))),
        vol_max_efficiency=Decimal(str(cs.get("vol_max_efficiency", "0.60"))),
        vol_min_reversals=int(cs.get("vol_min_reversals", 2)),
        # Momentum check
        momentum_check_enabled=cs.get("momentum_check_enabled", True),
        momentum_lookback_samples=int(cs.get("momentum_lookback_samples", 6)),
        momentum_bounce_threshold=Decimal(str(cs.get("momentum_bounce_threshold", "0.01"))),
        # Stop-loss
        stop_loss_enabled=cs.get("stop_loss_enabled", True),
        stop_loss_cents=Decimal(str(cs.get("stop_loss_cents", "0.10"))),
    )
