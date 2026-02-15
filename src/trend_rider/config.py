"""TrendRider configuration — YAML loader + validation."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal

log = logging.getLogger("tr.config")


@dataclass(frozen=True)
class TrendRiderConfig:
    enabled: bool = False
    dry_run: bool = True
    refresh_millis: int = 500

    bankroll_usd: Decimal = Decimal("100")

    # Time window — only enter between these bounds (seconds to resolution)
    min_seconds_to_end: int = 120
    max_seconds_to_end: int = 480

    # BTC momentum signal
    momentum_lookback_sec: int = 60
    momentum_threshold_usd: Decimal = Decimal("80")

    # Market conditions
    min_favorite_price: Decimal = Decimal("0.55")
    max_favorite_price: Decimal = Decimal("0.80")
    min_underdog_ask: Decimal = Decimal("0.20")
    min_combined_asks: Decimal = Decimal("0.98")

    # Risk
    max_positions: int = 2
    max_position_pct: Decimal = Decimal("0.25")
    stop_loss_drop: Decimal = Decimal("0.10")

    # Order type
    use_fok: bool = True


def validate_config(cfg: TrendRiderConfig) -> None:
    if cfg.bankroll_usd <= 0:
        raise ValueError(f"bankroll_usd must be > 0, got {cfg.bankroll_usd}")
    if cfg.min_seconds_to_end >= cfg.max_seconds_to_end:
        raise ValueError(
            f"min_seconds_to_end ({cfg.min_seconds_to_end}) "
            f"must be < max_seconds_to_end ({cfg.max_seconds_to_end})"
        )
    if not (0 < cfg.max_position_pct <= 1):
        raise ValueError(f"max_position_pct must be in (0, 1], got {cfg.max_position_pct}")
    if cfg.min_favorite_price >= cfg.max_favorite_price:
        raise ValueError(
            f"min_favorite_price ({cfg.min_favorite_price}) "
            f"must be < max_favorite_price ({cfg.max_favorite_price})"
        )
    if cfg.stop_loss_drop <= 0:
        raise ValueError(f"stop_loss_drop must be > 0, got {cfg.stop_loss_drop}")
    if cfg.momentum_threshold_usd <= 0:
        raise ValueError(f"momentum_threshold_usd must be > 0, got {cfg.momentum_threshold_usd}")


def load_trend_rider_config(raw: dict) -> TrendRiderConfig:
    """Load TrendRider config from raw YAML dict."""
    section = raw.get("trend_rider", {})
    if not section:
        log.info("No trend_rider section in config — using defaults (disabled)")
        return TrendRiderConfig()

    # DRY_RUN env var override (same as complete_set)
    import os
    dry_env = os.environ.get("DRY_RUN", "").lower()

    cfg = TrendRiderConfig(
        enabled=section.get("enabled", False),
        dry_run=dry_env == "true" if dry_env else section.get("dry_run", True),
        refresh_millis=section.get("refresh_millis", 500),
        bankroll_usd=Decimal(str(section.get("bankroll_usd", 100))),
        min_seconds_to_end=section.get("min_seconds_to_end", 120),
        max_seconds_to_end=section.get("max_seconds_to_end", 480),
        momentum_lookback_sec=section.get("momentum_lookback_sec", 60),
        momentum_threshold_usd=Decimal(str(section.get("momentum_threshold_usd", 80))),
        min_favorite_price=Decimal(str(section.get("min_favorite_price", "0.55"))),
        max_favorite_price=Decimal(str(section.get("max_favorite_price", "0.80"))),
        min_underdog_ask=Decimal(str(section.get("min_underdog_ask", "0.20"))),
        min_combined_asks=Decimal(str(section.get("min_combined_asks", "0.98"))),
        max_positions=section.get("max_positions", 2),
        max_position_pct=Decimal(str(section.get("max_position_pct", "0.25"))),
        stop_loss_drop=Decimal(str(section.get("stop_loss_drop", "0.10"))),
        use_fok=section.get("use_fok", True),
    )

    # DRY_RUN=false means live
    if dry_env == "false":
        cfg = TrendRiderConfig(**{**cfg.__dict__, "dry_run": False})

    validate_config(cfg)
    return cfg
