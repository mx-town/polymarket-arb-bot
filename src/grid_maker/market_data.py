"""Market discovery for grid-maker strategy — 5m, 15m, 1h timeframes.

Reuses shared market_data for 5m/15m discovery, adds 1h slug generation.
"""

from __future__ import annotations

import logging
import time

import requests

from shared.market_data import (
    GAMMA_HOST,
    _ASSET_PREFIXES_5M,
    _ASSET_PREFIXES_15M,
    _candidate_5m_slugs,
    _candidate_15m_slugs,
    _fetch_market_by_slug,
)
from shared.models import GabagoolMarket

log = logging.getLogger("gm.market_data")

# 1h markets use a different slug pattern — need to search Gamma API
_ASSET_PREFIXES_1H = {
    "bitcoin": "btc",
    "ethereum": "eth",
}


def _candidate_1h_slugs(asset_prefix: str, now_epoch: float) -> list[str]:
    """Generate candidate slugs for 1h updown markets.

    Format: {asset}-updown-1h-{epoch} where epoch aligns to 3600s boundaries.
    """
    now_sec = int(now_epoch)
    start = (now_sec // 3600) * 3600
    return [
        f"{asset_prefix}-updown-1h-{epoch}"
        for epoch in range(start - 3600, start + 7200 + 1, 3600)
    ]


def _search_1h_markets(asset: str) -> list[GabagoolMarket]:
    """Search Gamma API for active 1h Up/Down markets by tag/category.

    Fallback for 1h markets whose slugs don't follow the epoch pattern.
    """
    now = time.time()
    markets: list[GabagoolMarket] = []

    try:
        resp = requests.get(
            f"{GAMMA_HOST}/events",
            params={
                "tag": f"{asset}-1h",
                "closed": "false",
                "limit": 10,
            },
            timeout=10,
        )
        if resp.status_code != 200:
            return []

        events = resp.json()
        for event in events:
            slug = event.get("slug", "")
            if "up" not in slug.lower() and "down" not in slug.lower():
                continue
            market = _fetch_market_by_slug(slug)
            if market and market.end_time > now:
                markets.append(market)
    except Exception as e:
        log.debug("1h market search failed for %s: %s", asset, e)

    return markets


def discover_markets(
    assets: tuple[str, ...],
    timeframes: tuple[str, ...],
    max_markets: int = 20,
) -> list[GabagoolMarket]:
    """Discover active Up/Down markets for given assets and timeframes."""
    now = time.time()
    markets: list[GabagoolMarket] = []
    seen_slugs: set[str] = set()

    for asset in assets:
        # 5m markets
        if "5m" in timeframes:
            prefix = _ASSET_PREFIXES_5M.get(asset)
            if prefix:
                for slug in _candidate_5m_slugs(prefix, now):
                    if slug in seen_slugs:
                        continue
                    seen_slugs.add(slug)
                    market = _fetch_market_by_slug(slug)
                    if market and market.end_time > now:
                        markets.append(market)

        # 15m markets
        if "15m" in timeframes:
            prefix = _ASSET_PREFIXES_15M.get(asset)
            if prefix:
                for slug in _candidate_15m_slugs(prefix, now):
                    if slug in seen_slugs:
                        continue
                    seen_slugs.add(slug)
                    market = _fetch_market_by_slug(slug)
                    if market and market.end_time > now:
                        markets.append(market)

        # 1h markets
        if "1h" in timeframes:
            prefix = _ASSET_PREFIXES_1H.get(asset)
            if prefix:
                # Try epoch-based slugs first
                for slug in _candidate_1h_slugs(prefix, now):
                    if slug in seen_slugs:
                        continue
                    seen_slugs.add(slug)
                    market = _fetch_market_by_slug(slug)
                    if market and market.end_time > now:
                        markets.append(market)

                # Fallback: search by tag
                for market in _search_1h_markets(asset):
                    if market.slug not in seen_slugs:
                        seen_slugs.add(market.slug)
                        markets.append(market)

    # Cap at max_markets
    markets = markets[:max_markets]

    if markets:
        log.info("Discovered %d active markets", len(markets))
        for m in markets:
            secs = int(m.end_time - now)
            mins, secs_r = divmod(secs, 60)
            log.info("  %s │ %s │ %dm%02ds", m.market_type, m.slug[:50], mins, secs_r)

    return markets
