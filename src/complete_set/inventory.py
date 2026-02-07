"""Per-market UP/DOWN position tracking.

Translates PositionTracker.java. Maintains a cache of on-chain positions
and maps them to per-market inventory for complete-set coordination.
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal

from py_clob_client.clob_types import AssetType, BalanceAllowanceParams

from complete_set.models import GabagoolMarket, MarketInventory

log = logging.getLogger("cs.inventory")

CACHE_TTL_SECONDS = 5.0
ZERO = Decimal("0")
ONE = Decimal("1")

# ANSI colors for log highlights
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_RESET = "\033[0m"


class InventoryTracker:
    def __init__(self, dry_run: bool = False):
        self._dry_run = dry_run
        self._shares_by_token: dict[str, Decimal] = {}
        self._last_refresh: float = 0.0
        self._inventory_by_market: dict[str, MarketInventory] = {}
        self.session_realized_pnl: Decimal = ZERO
        self.session_total_deployed: Decimal = ZERO

    def refresh_if_stale(self, client, markets: list[GabagoolMarket] | None = None) -> None:
        """Refresh positions from CLOB if cache is stale (>5s).

        In dry-run mode, skip entirely — inventory comes from record_fill.
        """
        if self._dry_run:
            return

        now = time.time()
        if now - self._last_refresh < CACHE_TTL_SECONDS:
            return

        token_ids: set[str] = set()
        if markets:
            for m in markets:
                if m.up_token_id:
                    token_ids.add(m.up_token_id)
                if m.down_token_id:
                    token_ids.add(m.down_token_id)

        if not token_ids:
            return

        try:
            self._fetch_positions(client, token_ids)
            self._last_refresh = now
        except Exception as e:
            self._last_refresh = now
            log.debug("positions refresh failed: %s", e)

    def _fetch_positions(self, client, token_ids: set[str]) -> None:
        """Fetch balances for each token_id via get_balance_allowance."""
        shares: dict[str, Decimal] = {}

        for tid in token_ids:
            try:
                resp = client.get_balance_allowance(
                    params=BalanceAllowanceParams(
                        asset_type=AssetType.CONDITIONAL,
                        token_id=tid,
                    )
                )
                bal_str = resp.get("balance", "0") if isinstance(resp, dict) else getattr(resp, "balance", "0")
                bal_raw = Decimal(str(bal_str))
                bal = bal_raw / Decimal("1000000")  # CTF tokens use 6 decimals
                if bal > ZERO:
                    shares[tid] = bal
            except Exception as e:
                log.debug("balance fetch failed for %s: %s", tid[:16], e)

        self._shares_by_token = shares

    def sync_inventory(
        self, markets: list[GabagoolMarket], get_mid_price=None,
    ) -> None:
        """Map token positions to per-market MarketInventory.

        In dry-run mode, only ensure market entries exist — never overwrite
        share counts since there's no on-chain data to merge.

        When get_mid_price is provided and a chain position has zero cost
        (newly discovered, no prior fills), estimate cost using mid-market
        price so exposure calculations account for deployed capital.
        """
        DEFAULT_PRICE = Decimal("0.50")

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

            # Bootstrap cost for newly discovered chain positions.
            # Only fires when chain shows shares but existing cost is zero
            # (first startup with pre-existing positions). Once fills
            # accumulate real cost data, existing cost is preserved.
            up_cost = existing.up_cost
            down_cost = existing.down_cost
            if chain_up > ZERO and up_cost == ZERO and existing.up_shares == ZERO:
                mid = None
                if get_mid_price is not None:
                    try:
                        mid = get_mid_price(market.up_token_id)
                    except Exception:
                        mid = None
                up_cost = chain_up * (mid if mid is not None else DEFAULT_PRICE)
            if chain_down > ZERO and down_cost == ZERO and existing.down_shares == ZERO:
                mid = None
                if get_mid_price is not None:
                    try:
                        mid = get_mid_price(market.down_token_id)
                    except Exception:
                        mid = None
                down_cost = chain_down * (mid if mid is not None else DEFAULT_PRICE)

            merged_up = max(chain_up, existing.up_shares)
            merged_down = max(chain_down, existing.down_shares)

            # Log when chain positions are loaded
            if (up_cost != existing.up_cost or down_cost != existing.down_cost):
                est_cost = (up_cost + down_cost).quantize(Decimal("0.01"))
                log.info(
                    "SYNC_POSITION %s U%s/D%s (est_cost=$%s)",
                    market.slug, merged_up, merged_down, est_cost,
                )

            # Use max() to merge: never reduce shares below what record_fill
            # has accumulated, even if CLOB positions haven't settled yet.
            self._inventory_by_market[market.slug] = MarketInventory(
                up_shares=merged_up,
                down_shares=merged_down,
                up_cost=up_cost,
                down_cost=down_cost,
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
        self.session_total_deployed += shares * price
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

            color = C_GREEN if hedged_pnl >= ZERO else C_RED
            log.info(
                "%sCLEAR_INVENTORY %s (was U%s/D%s) │ hedged=%s │ cost=$%s │ "
                "hedged_pnl=$%s │ unhedged=%s%s",
                color, slug, removed.up_shares, removed.down_shares,
                hedged,
                hedged_cost.quantize(Decimal("0.01")),
                hedged_pnl.quantize(Decimal("0.01")),
                unhedged_str, C_RESET,
            )
        else:
            log.info(
                "CLEAR_INVENTORY %s (was U%s/D%s)",
                slug, removed.up_shares, removed.down_shares,
            )

    def reduce_merged(self, slug: str, merged_shares: Decimal) -> None:
        """Reduce inventory after a successful merge.

        Removes merged_shares from both legs and reduces cost proportionally.
        """
        inv = self._inventory_by_market.get(slug)
        if inv is None:
            return

        # Record realized PnL from merged hedged pairs
        if merged_shares > ZERO and inv.up_vwap is not None and inv.down_vwap is not None:
            merged_cost = merged_shares * (inv.up_vwap + inv.down_vwap)
            merged_pnl = merged_shares * ONE - merged_cost
            self.session_realized_pnl += merged_pnl
            self.session_total_deployed = max(ZERO, self.session_total_deployed - merged_cost)

        new_up = max(ZERO, inv.up_shares - merged_shares)
        new_down = max(ZERO, inv.down_shares - merged_shares)

        # Reduce cost proportionally to shares removed
        if inv.up_shares > ZERO:
            up_cost = inv.up_cost * (new_up / inv.up_shares)
        else:
            up_cost = ZERO
        if inv.down_shares > ZERO:
            down_cost = inv.down_cost * (new_down / inv.down_shares)
        else:
            down_cost = ZERO

        self._inventory_by_market[slug] = MarketInventory(
            up_shares=new_up,
            down_shares=new_down,
            up_cost=up_cost,
            down_cost=down_cost,
            last_up_fill_at=inv.last_up_fill_at,
            last_down_fill_at=inv.last_down_fill_at,
            last_up_fill_price=inv.last_up_fill_price,
            last_down_fill_price=inv.last_down_fill_price,
            last_top_up_at=inv.last_top_up_at,
        )

    def get_all_inventories(self) -> dict[str, MarketInventory]:
        """Get all inventories for exposure calculation."""
        return dict(self._inventory_by_market)
