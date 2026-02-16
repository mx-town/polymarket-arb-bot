"""Configuration loading for the rebate-maker strategy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

ZERO = Decimal("0")


@dataclass(frozen=True)
class RebateMakerConfig:
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

    # Grid
    grid_levels: int = 10
    grid_step: Decimal = Decimal("0.01")

    # Merge
    min_merge_shares: Decimal = Decimal("10")
    min_merge_profit_usd: Decimal = Decimal("0.02")
    merge_cooldown_sec: int = 15
    post_merge_lockout: bool = True

    # Gas
    max_gas_price_gwei: int = 200
    dry_merge_gas_cost_usd: Decimal = Decimal("0.003")
    matic_price_usd: Decimal = Decimal("0.40")

    # Entry price bounds
    max_entry_price: Decimal = Decimal("0.45")
    min_entry_price: Decimal = Decimal("0.10")


def validate_config(cfg: RebateMakerConfig) -> None:
    """Validate config values. Raises ValueError with all issues found."""
    errors: list[str] = []

    if cfg.bankroll_usd <= 0:
        errors.append(f"bankroll_usd must be > 0, got {cfg.bankroll_usd}")
    if not (Decimal("-0.05") <= cfg.min_edge <= Decimal("0.50")):
        errors.append(f"min_edge must be in [-0.05, 0.50], got {cfg.min_edge}")
    if cfg.min_seconds_to_end < 0:
        errors.append(f"min_seconds_to_end must be >= 0, got {cfg.min_seconds_to_end}")
    if cfg.max_seconds_to_end <= cfg.min_seconds_to_end:
        errors.append(
            f"max_seconds_to_end ({cfg.max_seconds_to_end}) must be > "
            f"min_seconds_to_end ({cfg.min_seconds_to_end})"
        )
    if cfg.no_new_orders_sec <= 0:
        errors.append(f"no_new_orders_sec must be > 0, got {cfg.no_new_orders_sec}")
    if cfg.min_merge_shares <= 0:
        errors.append(f"min_merge_shares must be > 0, got {cfg.min_merge_shares}")
    if cfg.min_merge_profit_usd < Decimal("-1.0"):
        errors.append(f"min_merge_profit_usd must be >= -1.0, got {cfg.min_merge_profit_usd}")
    if cfg.max_gas_price_gwei <= 0:
        errors.append(f"max_gas_price_gwei must be > 0, got {cfg.max_gas_price_gwei}")
    if cfg.refresh_millis < 100:
        errors.append(f"refresh_millis must be >= 100, got {cfg.refresh_millis}")
    if not (Decimal("0.05") <= cfg.min_entry_price < cfg.max_entry_price <= Decimal("0.60")):
        errors.append(
            f"entry price bounds must satisfy 0.05 <= min ({cfg.min_entry_price}) "
            f"< max ({cfg.max_entry_price}) <= 0.60"
        )

    if errors:
        raise ValueError("Config validation failed:\n  " + "\n  ".join(errors))


def load_rebate_maker_config(raw: dict[str, Any]) -> RebateMakerConfig:
    """Load RebateMakerConfig from config.yaml's rebate_maker section."""
    cs = raw.get("rebate_maker", {})
    if not cs:
        return RebateMakerConfig()

    assets = cs.get("assets", ["bitcoin", "ethereum"])

    cfg = RebateMakerConfig(
        enabled=cs.get("enabled", True),
        dry_run=cs.get("dry_run", True),
        refresh_millis=cs.get("refresh_millis", 2000),
        assets=tuple(assets),
        min_seconds_to_end=cs.get("min_seconds_to_end", 0),
        max_seconds_to_end=cs.get("max_seconds_to_end", 3600),
        no_new_orders_sec=cs.get("no_new_orders_sec", 45),
        min_edge=Decimal(str(cs.get("min_edge", "0.01"))),
        bankroll_usd=Decimal(str(cs.get("bankroll_usd", "100"))),
        # Grid
        grid_levels=int(cs.get("grid_levels", 10)),
        grid_step=Decimal(str(cs.get("grid_step", "0.01"))),
        # Merge
        min_merge_shares=Decimal(str(cs.get("min_merge_shares", "10"))),
        min_merge_profit_usd=Decimal(str(cs.get("min_merge_profit_usd", "0.02"))),
        merge_cooldown_sec=int(cs.get("merge_cooldown_sec", 15)),
        post_merge_lockout=cs.get("post_merge_lockout", True),
        max_gas_price_gwei=int(cs.get("max_gas_price_gwei", 200)),
        dry_merge_gas_cost_usd=Decimal(str(cs.get("dry_merge_gas_cost_usd", "0.003"))),
        matic_price_usd=Decimal(str(cs.get("matic_price_usd", "0.40"))),
        # Entry price bounds
        max_entry_price=Decimal(str(cs.get("max_entry_price", "0.45"))),
        min_entry_price=Decimal(str(cs.get("min_entry_price", "0.10"))),
    )
    validate_config(cfg)
    return cfg
