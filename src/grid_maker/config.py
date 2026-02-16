"""Configuration for the grid-maker strategy."""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

ZERO = Decimal("0")


@dataclass(frozen=True)
class GridMakerConfig:
    enabled: bool = True
    dry_run: bool = True
    refresh_millis: int = 500

    # Bankroll
    bankroll_usd: Decimal = Decimal("500")

    # Markets
    max_markets: int = 20
    assets: tuple[str, ...] = ("bitcoin", "ethereum")
    timeframes: tuple[str, ...] = ("5m", "15m")

    # Grid parameters
    grid_mode: str = "dynamic"  # "dynamic" or "static"
    grid_levels_per_side: int = 30
    grid_step: Decimal = Decimal("0.01")
    base_size_shares: Decimal = Decimal("7")
    size_curve: str = "flat"  # "flat" or "bell"
    fixed_size_shares: Decimal = Decimal("26")  # shares per level in static mode

    # Time window
    min_seconds_to_end: int = 120
    max_seconds_to_end: int = 480
    entry_delay_sec: int = 15

    # Taker aggression
    taker_aggression_pct: Decimal = Decimal("0.10")
    taker_trigger_imbalance: Decimal = Decimal("0.30")
    use_fok: bool = True

    # Merge
    merge_mode: str = "eager"  # "eager" or "batch"
    min_merge_shares: Decimal = Decimal("10")
    merge_cooldown_sec: int = 15
    merge_batch_interval_sec: int = 3600  # seconds between batch merge sweeps

    # Gas
    max_gas_price_gwei: int = 200
    matic_price_usd: Decimal = Decimal("0.40")

    # Compounding
    compound: bool = True
    compound_interval_sec: int = 3600

    # Entry price bounds
    max_entry_price: Decimal = Decimal("0.60")
    min_entry_price: Decimal = Decimal("0.05")


def validate_config(cfg: GridMakerConfig) -> None:
    """Validate GridMakerConfig. Raises ValueError with all issues found."""
    errors: list[str] = []

    if cfg.bankroll_usd <= 0:
        errors.append(f"bankroll_usd must be > 0, got {cfg.bankroll_usd}")
    if cfg.max_markets <= 0:
        errors.append(f"max_markets must be > 0, got {cfg.max_markets}")
    if cfg.grid_levels_per_side <= 0:
        errors.append(f"grid_levels_per_side must be > 0, got {cfg.grid_levels_per_side}")
    if cfg.grid_step <= ZERO:
        errors.append(f"grid_step must be > 0, got {cfg.grid_step}")
    if cfg.base_size_shares <= ZERO:
        errors.append(f"base_size_shares must be > 0, got {cfg.base_size_shares}")
    if cfg.min_seconds_to_end < 0:
        errors.append(f"min_seconds_to_end must be >= 0, got {cfg.min_seconds_to_end}")
    if cfg.max_seconds_to_end <= cfg.min_seconds_to_end:
        errors.append(
            f"max_seconds_to_end ({cfg.max_seconds_to_end}) must be > "
            f"min_seconds_to_end ({cfg.min_seconds_to_end})"
        )
    if cfg.entry_delay_sec < 0:
        errors.append(f"entry_delay_sec must be >= 0, got {cfg.entry_delay_sec}")
    if not (ZERO <= cfg.taker_aggression_pct <= Decimal("1")):
        errors.append(f"taker_aggression_pct must be in [0, 1], got {cfg.taker_aggression_pct}")
    if not (ZERO < cfg.taker_trigger_imbalance <= Decimal("1")):
        errors.append(
            f"taker_trigger_imbalance must be in (0, 1], got {cfg.taker_trigger_imbalance}"
        )
    if cfg.min_merge_shares <= ZERO:
        errors.append(f"min_merge_shares must be > 0, got {cfg.min_merge_shares}")
    if cfg.max_gas_price_gwei <= 0:
        errors.append(f"max_gas_price_gwei must be > 0, got {cfg.max_gas_price_gwei}")
    if cfg.refresh_millis < 100:
        errors.append(f"refresh_millis must be >= 100, got {cfg.refresh_millis}")
    if not (ZERO < cfg.min_entry_price < cfg.max_entry_price <= Decimal("1")):
        errors.append(
            f"entry price bounds invalid: 0 < {cfg.min_entry_price} < {cfg.max_entry_price} <= 1"
        )
    if cfg.size_curve not in ("flat", "bell"):
        errors.append(f"size_curve must be 'flat' or 'bell', got {cfg.size_curve}")
    if cfg.grid_mode not in ("dynamic", "static"):
        errors.append(f"grid_mode must be 'dynamic' or 'static', got {cfg.grid_mode}")
    if cfg.fixed_size_shares <= ZERO:
        errors.append(f"fixed_size_shares must be > 0, got {cfg.fixed_size_shares}")
    if cfg.merge_mode not in ("eager", "batch"):
        errors.append(f"merge_mode must be 'eager' or 'batch', got {cfg.merge_mode}")
    if cfg.merge_batch_interval_sec <= 0:
        errors.append(f"merge_batch_interval_sec must be > 0, got {cfg.merge_batch_interval_sec}")

    if errors:
        raise ValueError("GridMakerConfig validation failed:\n  " + "\n  ".join(errors))


def load_grid_maker_config(raw: dict[str, Any]) -> GridMakerConfig:
    """Load GridMakerConfig from config.yaml's grid_maker section."""
    gm = raw.get("grid_maker", {})
    if not gm:
        return GridMakerConfig()

    assets = gm.get("assets", ["bitcoin", "ethereum"])
    timeframes = gm.get("timeframes", ["5m", "15m"])

    cfg = GridMakerConfig(
        enabled=gm.get("enabled", True),
        dry_run=gm.get("dry_run", True),
        refresh_millis=gm.get("refresh_millis", 500),
        bankroll_usd=Decimal(str(gm.get("bankroll_usd", "500"))),
        max_markets=int(gm.get("max_markets", 20)),
        assets=tuple(assets),
        timeframes=tuple(timeframes),
        grid_mode=gm.get("grid_mode", "dynamic"),
        grid_levels_per_side=int(gm.get("grid_levels_per_side", 30)),
        grid_step=Decimal(str(gm.get("grid_step", "0.01"))),
        base_size_shares=Decimal(str(gm.get("base_size_shares", "7"))),
        size_curve=gm.get("size_curve", "flat"),
        fixed_size_shares=Decimal(str(gm.get("fixed_size_shares", "26"))),
        min_seconds_to_end=int(gm.get("min_seconds_to_end", 120)),
        max_seconds_to_end=int(gm.get("max_seconds_to_end", 480)),
        entry_delay_sec=int(gm.get("entry_delay_sec", 15)),
        taker_aggression_pct=Decimal(str(gm.get("taker_aggression_pct", "0.10"))),
        taker_trigger_imbalance=Decimal(str(gm.get("taker_trigger_imbalance", "0.30"))),
        use_fok=gm.get("use_fok", True),
        merge_mode=gm.get("merge_mode", "eager"),
        min_merge_shares=Decimal(str(gm.get("min_merge_shares", "10"))),
        merge_cooldown_sec=int(gm.get("merge_cooldown_sec", 15)),
        merge_batch_interval_sec=int(gm.get("merge_batch_interval_sec", 3600)),
        max_gas_price_gwei=int(gm.get("max_gas_price_gwei", 200)),
        matic_price_usd=Decimal(str(gm.get("matic_price_usd", "0.40"))),
        compound=gm.get("compound", True),
        compound_interval_sec=int(gm.get("compound_interval_sec", 3600)),
        max_entry_price=Decimal(str(gm.get("max_entry_price", "0.60"))),
        min_entry_price=Decimal(str(gm.get("min_entry_price", "0.05"))),
    )
    validate_config(cfg)
    return cfg
