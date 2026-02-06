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


ONE = Decimal("1")


class InventoryTracker:
    def __init__(self, dry_run: bool = False):
        self._dry_run = dry_run
        self._shares_by_token: dict[str, Decimal] = {}
        self._last_refresh: float = 0.0
        self._inventory_by_market: dict[str, MarketInventory] = {}
        self.session_realized_pnl: Decimal = ZERO

    def refresh_if_stale(self, client) -> None:
        """Refresh positions from CLOB if cache is stale (>5s).

        In dry-run mode, skip entirely — inventory comes from record_fill.
        """
        if self._dry_run:
            return

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
        """Map token positions to per-market MarketInventory.

        In dry-run mode, only ensure market entries exist — never overwrite
        share counts since there's no on-chain data to merge.
        """
        for market in markets:
            if not market.up_token_id or not market.down_token_id:
                continue

            existing = self._inventory_by_market.get(market.slug)

            if self._dry_run:
                # Just ensure the entry exists; don't touch shares
                if existing is None:
                    self._inventory_by_market[market.slug] = MarketInventory()
                continue

            chain_up = self._shares_by_token.get(market.up_token_id, ZERO)
            chain_down = self._shares_by_token.get(market.down_token_id, ZERO)

            if existing is None:
                existing = MarketInventory()
            # Use max() to merge: never reduce shares below what record_fill
            # has accumulated, even if CLOB positions haven't settled yet.
            self._inventory_by_market[market.slug] = MarketInventory(
                up_shares=max(chain_up, existing.up_shares),
                down_shares=max(chain_down, existing.down_shares),
                up_cost=existing.up_cost,
                down_cost=existing.down_cost,
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

    def clear_market(self, slug: str) -> None:
        """Remove inventory for a resolved/expired market."""
        removed = self._inventory_by_market.pop(slug, None)
        if removed is None:
            return

        hedged = min(removed.up_shares, removed.down_shares)

        if hedged > ZERO and removed.up_vwap is not None and removed.down_vwap is not None:
            hedged_cost = hedged * (removed.up_vwap + removed.down_vwap)
            hedged_pnl = hedged * ONE - hedged_cost
            self.session_realized_pnl += hedged_pnl

            # Determine unhedged remainder
            if removed.up_shares > removed.down_shares:
                unhedged_str = f"U{removed.up_shares - removed.down_shares}"
            elif removed.down_shares > removed.up_shares:
                unhedged_str = f"D{removed.down_shares - removed.up_shares}"
            else:
                unhedged_str = "none"

            log.info(
                "CLEAR_INVENTORY %s (was U%s/D%s) │ hedged=%s │ cost=$%s │ "
                "hedged_pnl=$%s │ unhedged=%s",
                slug, removed.up_shares, removed.down_shares,
                hedged,
                hedged_cost.quantize(Decimal("0.01")),
                hedged_pnl.quantize(Decimal("0.01")),
                unhedged_str,
            )
        else:
            log.info(
                "CLEAR_INVENTORY %s (was U%s/D%s)",
                slug, removed.up_shares, removed.down_shares,
            )

    def get_all_inventories(self) -> dict[str, MarketInventory]:
        """Get all inventories for exposure calculation."""
        return dict(self._inventory_by_market)
