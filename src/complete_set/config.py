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
    hedge_edge_buffer: Decimal = Decimal("0.005")

    # Bankroll
    bankroll_usd: Decimal = Decimal("100")
    max_order_bankroll_fraction: Decimal = Decimal("0.05")
    max_total_bankroll_fraction: Decimal = Decimal("0.50")

    # Merge
    min_merge_shares: Decimal = Decimal("10")
    min_merge_profit_usd: Decimal = Decimal("0.02")
    merge_cooldown_sec: int = 15

    # Gas
    max_gas_price_gwei: int = 200
    dry_merge_gas_cost_usd: Decimal = Decimal("0.003")

    # Stop hunt (early entry, minutes 2-5)
    stop_hunt_enabled: bool = True
    sh_entry_start_sec: int = 780     # start looking at minute 2 (780s left)
    sh_entry_end_sec: int = 600       # stop at minute 5 (600s left)

    # Mean reversion (Binance BTC feed)
    mean_reversion_enabled: bool = False
    mr_deviation_threshold: Decimal = Decimal("0.0004")   # 0.04%
    mr_range_filter_enabled: bool = True
    mr_max_range_pct: Decimal = Decimal("0.0010")         # 0.10% — skip trending candles
    mr_entry_window_sec: int = 240                        # last 4 minutes

    # Volume imbalance (Binance aggTrade feed)
    volume_imbalance_enabled: bool = False
    volume_imbalance_threshold: Decimal = Decimal("0.15")  # +-15% imbalance
    volume_min_btc: Decimal = Decimal("50")                # min 50 BTC in window
    volume_short_window_sec: int = 30
    volume_medium_window_sec: int = 120


def validate_config(cfg: CompleteSetConfig) -> None:
    """Validate config values. Raises ValueError with all issues found."""
    errors: list[str] = []

    if cfg.bankroll_usd <= 0:
        errors.append(f"bankroll_usd must be > 0, got {cfg.bankroll_usd}")
    if not (0 <= cfg.min_edge <= Decimal("0.50")):
        errors.append(f"min_edge must be in [0, 0.50], got {cfg.min_edge}")
    if cfg.min_seconds_to_end < 0:
        errors.append(f"min_seconds_to_end must be >= 0, got {cfg.min_seconds_to_end}")
    if cfg.max_seconds_to_end <= cfg.min_seconds_to_end:
        errors.append(
            f"max_seconds_to_end ({cfg.max_seconds_to_end}) must be > "
            f"min_seconds_to_end ({cfg.min_seconds_to_end})"
        )
    if cfg.no_new_orders_sec <= 0:
        errors.append(f"no_new_orders_sec must be > 0, got {cfg.no_new_orders_sec}")
    if not (0 < cfg.max_order_bankroll_fraction <= 1):
        errors.append(
            f"max_order_bankroll_fraction must be in (0, 1], got {cfg.max_order_bankroll_fraction}"
        )
    if not (0 < cfg.max_total_bankroll_fraction <= 1):
        errors.append(
            f"max_total_bankroll_fraction must be in (0, 1], got {cfg.max_total_bankroll_fraction}"
        )
    if cfg.min_merge_shares <= 0:
        errors.append(f"min_merge_shares must be > 0, got {cfg.min_merge_shares}")
    if cfg.min_merge_profit_usd < 0:
        errors.append(f"min_merge_profit_usd must be >= 0, got {cfg.min_merge_profit_usd}")
    if cfg.max_gas_price_gwei <= 0:
        errors.append(f"max_gas_price_gwei must be > 0, got {cfg.max_gas_price_gwei}")
    if cfg.refresh_millis < 100:
        errors.append(f"refresh_millis must be >= 100, got {cfg.refresh_millis}")
    if cfg.stop_hunt_enabled:
        if cfg.sh_entry_start_sec <= cfg.sh_entry_end_sec:
            errors.append(
                f"sh_entry_start_sec ({cfg.sh_entry_start_sec}) must be > "
                f"sh_entry_end_sec ({cfg.sh_entry_end_sec})"
            )
    if cfg.mean_reversion_enabled:
        if cfg.mr_deviation_threshold <= 0:
            errors.append(
                f"mr_deviation_threshold must be > 0 when MR enabled, "
                f"got {cfg.mr_deviation_threshold}"
            )
        if cfg.mr_range_filter_enabled and cfg.mr_max_range_pct <= 0:
            errors.append(
                f"mr_max_range_pct must be > 0 when range filter enabled, got {cfg.mr_max_range_pct}"
            )

    if errors:
        raise ValueError("Config validation failed:\n  " + "\n  ".join(errors))


def load_complete_set_config(raw: dict[str, Any]) -> CompleteSetConfig:
    """Load CompleteSetConfig from config.yaml's complete_set section."""
    cs = raw.get("complete_set", {})
    if not cs:
        return CompleteSetConfig()

    assets = cs.get("assets", ["bitcoin", "ethereum"])

    cfg = CompleteSetConfig(
        enabled=cs.get("enabled", True),
        dry_run=cs.get("dry_run", True),
        refresh_millis=cs.get("refresh_millis", 2000),
        assets=tuple(assets),
        min_seconds_to_end=cs.get("min_seconds_to_end", 0),
        max_seconds_to_end=cs.get("max_seconds_to_end", 3600),
        no_new_orders_sec=cs.get("no_new_orders_sec", 45),
        min_edge=Decimal(str(cs.get("min_edge", "0.01"))),
        hedge_edge_buffer=Decimal(str(cs.get("hedge_edge_buffer", "0.005"))),
        bankroll_usd=Decimal(str(cs.get("bankroll_usd", "100"))),
        max_order_bankroll_fraction=Decimal(str(cs.get("max_order_bankroll_fraction", "0.05"))),
        max_total_bankroll_fraction=Decimal(str(cs.get("max_total_bankroll_fraction", "0.50"))),
        min_merge_shares=Decimal(str(cs.get("min_merge_shares", "10"))),
        min_merge_profit_usd=Decimal(str(cs.get("min_merge_profit_usd", "0.02"))),
        merge_cooldown_sec=int(cs.get("merge_cooldown_sec", 15)),
        max_gas_price_gwei=int(cs.get("max_gas_price_gwei", 200)),
        dry_merge_gas_cost_usd=Decimal(str(cs.get("dry_merge_gas_cost_usd", "0.003"))),
        # Stop hunt
        stop_hunt_enabled=cs.get("stop_hunt_enabled", True),
        sh_entry_start_sec=int(cs.get("sh_entry_start_sec", 780)),
        sh_entry_end_sec=int(cs.get("sh_entry_end_sec", 600)),
        # Mean reversion
        mean_reversion_enabled=cs.get("mean_reversion_enabled", False),
        mr_deviation_threshold=Decimal(str(cs.get("mr_deviation_threshold", "0.0004"))),
        mr_range_filter_enabled=cs.get("mr_range_filter_enabled", True),
        mr_max_range_pct=Decimal(str(cs.get("mr_max_range_pct", "0.0010"))),
        mr_entry_window_sec=int(cs.get("mr_entry_window_sec", 240)),
        # Volume imbalance
        volume_imbalance_enabled=cs.get("volume_imbalance_enabled", False),
        volume_imbalance_threshold=Decimal(str(cs.get("volume_imbalance_threshold", "0.15"))),
        volume_min_btc=Decimal(str(cs.get("volume_min_btc", "50"))),
        volume_short_window_sec=int(cs.get("volume_short_window_sec", 30)),
        volume_medium_window_sec=int(cs.get("volume_medium_window_sec", 120)),
    )
    validate_config(cfg)
    return cfg
