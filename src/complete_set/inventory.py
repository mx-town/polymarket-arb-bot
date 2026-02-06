"""Per-market UP/DOWN position tracking.

Translates PositionTracker.java. Maintains a cache of on-chain positions
and maps them to per-market inventory for complete-set coordination.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from complete_set.models import GabagoolMarket, MarketInventory

log = logging.getLogger("cs.inventory")

CACHE_TTL_SECONDS = 5.0
ZERO = Decimal("0")


class InventoryTracker:
    def __init__(self):
        self._shares_by_token: dict[str, Decimal] = {}
        self._last_refresh: float = 0.0
        self._inventory_by_market: dict[str, MarketInventory] = {}

    def refresh_if_stale(self, client) -> None:
        """Refresh positions from CLOB if cache is stale (>5s)."""
        now = time.time()
        if now - self._last_refresh < CACHE_TTL_SECONDS:
            return

        try:
            self._fetch_positions(client)
            self._last_refresh = now
        except Exception as e:
            # Keep stale data, update timestamp to avoid hammering
            self._last_refresh = now
            log.debug("positions refresh failed: %s", e)

    def _fetch_positions(self, client) -> None:
        """Fetch all positions and aggregate shares by token_id."""
        shares: dict[str, Decimal] = {}

        try:
            # py-clob-client may return positions differently
            # Try the get_balances or similar endpoint
            positions = client.get_balances()
            if positions:
                for p in positions:
                    if isinstance(p, dict):
                        asset = p.get("asset_id") or p.get("asset")
                        size = p.get("size") or p.get("balance", "0")
                    else:
                        asset = getattr(p, "asset_id", None) or getattr(p, "asset", None)
                        size = getattr(p, "size", None) or getattr(p, "balance", "0")

                    if asset and size:
                        size_dec = abs(Decimal(str(size)))
                        shares[asset] = shares.get(asset, ZERO) + size_dec
        except Exception:
            # Fallback: no position data available
            log.debug("Could not fetch positions, keeping existing data")
            return

        self._shares_by_token = shares

    def sync_inventory(self, markets: list[GabagoolMarket]) -> None:
        """Map token positions to per-market MarketInventory."""
        for market in markets:
            if not market.up_token_id or not market.down_token_id:
                continue

            up_shares = self._shares_by_token.get(market.up_token_id, ZERO)
            down_shares = self._shares_by_token.get(market.down_token_id, ZERO)

            existing = self._inventory_by_market.get(market.slug, MarketInventory())
            self._inventory_by_market[market.slug] = MarketInventory(
                up_shares=up_shares,
                down_shares=down_shares,
                last_up_fill_at=existing.last_up_fill_at,
                last_down_fill_at=existing.last_down_fill_at,
                last_up_fill_price=existing.last_up_fill_price,
                last_down_fill_price=existing.last_down_fill_price,
                last_top_up_at=existing.last_top_up_at,
            )

    def record_fill(
        self, slug: str, is_up: bool, shares: Decimal, price: Decimal
    ) -> None:
        """Update inventory after a fill."""
        now = time.time()
        current = self._inventory_by_market.get(slug, MarketInventory())
        if is_up:
            self._inventory_by_market[slug] = current.add_up(shares, now, price)
        else:
            self._inventory_by_market[slug] = current.add_down(shares, now, price)

    def mark_top_up(self, slug: str) -> None:
        """Mark a top-up attempt for cooldown tracking."""
        now = time.time()
        current = self._inventory_by_market.get(slug, MarketInventory())
        self._inventory_by_market[slug] = current.mark_top_up(now)

    def get_inventory(self, slug: str) -> MarketInventory:
        """Get inventory for a market, returns empty if not tracked."""
        return self._inventory_by_market.get(slug, MarketInventory())

    def get_all_inventories(self) -> dict[str, MarketInventory]:
        """Get all inventories for exposure calculation."""
        return dict(self._inventory_by_market)
