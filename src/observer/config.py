"""Configuration for the observer bot."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ObserverConfig:
    enabled: bool = True
    proxy_address: str = "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d"
    poll_interval_sec: int = 10
    activity_limit: int = 50
    positions_limit: int = 100
    etherscan_page_size: int = 50
    backfill_on_start: bool = True
    log_level: str = "INFO"


def load_observer_config(raw: dict[str, Any]) -> ObserverConfig:
    obs = raw.get("observer", {})
    if not obs:
        return ObserverConfig()
    return ObserverConfig(
        enabled=obs.get("enabled", True),
        proxy_address=obs.get("proxy_address", "0x6031b6eed1c97e853c6e0f03ad3ce3529351f96d"),
        poll_interval_sec=int(obs.get("poll_interval_sec", 10)),
        activity_limit=int(obs.get("activity_limit", 50)),
        positions_limit=int(obs.get("positions_limit", 100)),
        etherscan_page_size=int(obs.get("etherscan_page_size", 50)),
        backfill_on_start=obs.get("backfill_on_start", True),
        log_level=obs.get("log_level", "INFO"),
    )
