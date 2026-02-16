"""Configuration for the grid-maker strategy."""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

ZERO = Decimal("0")

# Default gabagool sizing table (asset -> timeframe -> shares)
_DEFAULT_GRID_SIZES: dict[str, dict[str, int]] = {
    "bitcoin": {"5m": 20, "15m": 15, "1h": 26},
    "ethereum": {"15m": 10, "1h": 16},
}


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

    # Grid parameters (static only — gabagool clone)
    grid_step: Decimal = Decimal("0.01")
    grid_sizes: dict[str, dict[str, int]] = field(default_factory=lambda: dict(_DEFAULT_GRID_SIZES))

    # Timing
    min_seconds_to_end: int = 30
    entry_delay_sec: int = 5

    # Merge (batch only — gabagool merges every ~60 min)
    min_merge_shares: Decimal = Decimal("10")
    merge_batch_interval_sec: int = 3600

    # Gas
    max_gas_price_gwei: int = 200
    matic_price_usd: Decimal = Decimal("0.40")

    # Redemption
    redeem_delay_sec: int = 60
    redeem_max_attempts: int = 3

    # Compounding
    compound: bool = True
    compound_interval_sec: int = 3600

    # Entry price bounds
    max_entry_price: Decimal = Decimal("0.99")
    min_entry_price: Decimal = Decimal("0.01")

    def get_size_for(self, asset: str, timeframe: str) -> Optional[int]:
        """Return target shares for an asset×timeframe combo, or None if not traded."""
        return self.grid_sizes.get(asset, {}).get(timeframe)


def validate_config(cfg: GridMakerConfig) -> None:
    """Validate GridMakerConfig. Raises ValueError with all issues found."""
    errors: list[str] = []

    if cfg.bankroll_usd <= 0:
        errors.append(f"bankroll_usd must be > 0, got {cfg.bankroll_usd}")
    if cfg.max_markets <= 0:
        errors.append(f"max_markets must be > 0, got {cfg.max_markets}")
    if cfg.grid_step <= ZERO:
        errors.append(f"grid_step must be > 0, got {cfg.grid_step}")
    if not cfg.grid_sizes:
        errors.append("grid_sizes must not be empty")
    for asset, tf_map in cfg.grid_sizes.items():
        for tf, sz in tf_map.items():
            if sz <= 0:
                errors.append(f"grid_sizes[{asset}][{tf}] must be > 0, got {sz}")
    if cfg.min_seconds_to_end < 0:
        errors.append(f"min_seconds_to_end must be >= 0, got {cfg.min_seconds_to_end}")
    if cfg.entry_delay_sec < 0:
        errors.append(f"entry_delay_sec must be >= 0, got {cfg.entry_delay_sec}")
    if cfg.min_merge_shares <= ZERO:
        errors.append(f"min_merge_shares must be > 0, got {cfg.min_merge_shares}")
    if cfg.merge_batch_interval_sec <= 0:
        errors.append(f"merge_batch_interval_sec must be > 0, got {cfg.merge_batch_interval_sec}")
    if cfg.max_gas_price_gwei <= 0:
        errors.append(f"max_gas_price_gwei must be > 0, got {cfg.max_gas_price_gwei}")
    if cfg.refresh_millis < 100:
        errors.append(f"refresh_millis must be >= 100, got {cfg.refresh_millis}")
    if not (ZERO < cfg.min_entry_price < cfg.max_entry_price <= Decimal("1")):
        errors.append(
            f"entry price bounds invalid: 0 < {cfg.min_entry_price} < {cfg.max_entry_price} <= 1"
        )
    if cfg.redeem_delay_sec < 0:
        errors.append(f"redeem_delay_sec must be >= 0, got {cfg.redeem_delay_sec}")
    if cfg.redeem_max_attempts <= 0:
        errors.append(f"redeem_max_attempts must be > 0, got {cfg.redeem_max_attempts}")

    if errors:
        raise ValueError("GridMakerConfig validation failed:\n  " + "\n  ".join(errors))


def load_grid_maker_config(raw: dict[str, Any]) -> GridMakerConfig:
    """Load GridMakerConfig from config.yaml's grid_maker section."""
    gm = raw.get("grid_maker", {})
    if not gm:
        return GridMakerConfig()

    assets = gm.get("assets", ["bitcoin", "ethereum"])
    timeframes = gm.get("timeframes", ["5m", "15m"])

    # Parse grid_sizes from YAML (nested dict: asset -> timeframe -> int)
    raw_sizes = gm.get("grid_sizes")
    if raw_sizes and isinstance(raw_sizes, dict):
        grid_sizes = {
            asset: {tf: int(sz) for tf, sz in tf_map.items()}
            for asset, tf_map in raw_sizes.items()
            if isinstance(tf_map, dict)
        }
    else:
        grid_sizes = dict(_DEFAULT_GRID_SIZES)

    cfg = GridMakerConfig(
        enabled=gm.get("enabled", True),
        dry_run=gm.get("dry_run", True),
        refresh_millis=gm.get("refresh_millis", 500),
        bankroll_usd=Decimal(str(gm.get("bankroll_usd", "500"))),
        max_markets=int(gm.get("max_markets", 20)),
        assets=tuple(assets),
        timeframes=tuple(timeframes),
        grid_step=Decimal(str(gm.get("grid_step", "0.01"))),
        grid_sizes=grid_sizes,
        min_seconds_to_end=int(gm.get("min_seconds_to_end", 30)),
        entry_delay_sec=int(gm.get("entry_delay_sec", 5)),
        min_merge_shares=Decimal(str(gm.get("min_merge_shares", "10"))),
        merge_batch_interval_sec=int(gm.get("merge_batch_interval_sec", 3600)),
        max_gas_price_gwei=int(gm.get("max_gas_price_gwei", 200)),
        matic_price_usd=Decimal(str(gm.get("matic_price_usd", "0.40"))),
        redeem_delay_sec=int(gm.get("redeem_delay_sec", 60)),
        redeem_max_attempts=int(gm.get("redeem_max_attempts", 3)),
        compound=gm.get("compound", True),
        compound_interval_sec=int(gm.get("compound_interval_sec", 3600)),
        max_entry_price=Decimal(str(gm.get("max_entry_price", "0.99"))),
        min_entry_price=Decimal(str(gm.get("min_entry_price", "0.01"))),
    )
    validate_config(cfg)
    return cfg
