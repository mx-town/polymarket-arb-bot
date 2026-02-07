"""Strategy tick loop — the brain of the complete-set arbitrage.

Translates GabagoolDirectionalEngine.java.
Runs a tick every refresh_millis (default 500ms), evaluating each active market.
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal

from complete_set.config import CompleteSetConfig
from complete_set.inventory import InventoryTracker
from complete_set.market_data import discover_markets, get_top_of_book
from complete_set.models import Direction, GabagoolMarket, PendingRedemption, ReplaceDecision, TopOfBook
from complete_set.redeem import redeem_positions
from complete_set.order_mgr import OrderManager
from complete_set.quote_calc import (
    calculate_balanced_shares,
    calculate_entry_price,
    calculate_exposure,
    calculate_exposure_breakdown,
    calculate_shares,
    calculate_skew_ticks,
    has_minimum_edge,
)

log = logging.getLogger("cs.engine")

ZERO = Decimal("0")
ONE = Decimal("1")
TICK_SIZE = Decimal("0.01")  # Default Polymarket tick size


class Engine:
    def __init__(self, client, cfg: CompleteSetConfig, private_key: str = "", rpc_url: str = ""):
        self._client = client
        self._cfg = cfg
        self._private_key = private_key
        self._rpc_url = rpc_url
        self._order_mgr = OrderManager(dry_run=cfg.dry_run)
        self._inventory = InventoryTracker(dry_run=cfg.dry_run)
        self._active_markets: list[GabagoolMarket] = []
        self._last_discovery: float = 0.0
        self._prev_quotable_slugs: set[str] = set()
        self._balance_failures: dict[str, int] = {}  # market slug -> consecutive failures
        self._pending_redemptions: dict[str, PendingRedemption] = {}

    async def run(self) -> None:
        """Main event loop."""
        mode = "DRY RUN" if self._cfg.dry_run else "LIVE"
        log.info("=" * 56)
        log.info("  Complete-Set Arb Engine v0.1.0  [%s]", mode)
        log.info("=" * 56)
        log.info("  Assets          : %s", ", ".join(self._cfg.assets))
        log.info("  Tick interval   : %dms", self._cfg.refresh_millis)
        log.info("  Min edge        : %s", self._cfg.min_edge)
        log.info("  Bankroll        : $%s", self._cfg.bankroll_usd)
        log.info("  Improve ticks   : %d", self._cfg.improve_ticks)
        log.info("  Min replace     : %dms / %d ticks", self._cfg.min_replace_millis, self._cfg.min_replace_ticks)
        log.info("  Time window     : %d-%ds", self._cfg.min_seconds_to_end, self._cfg.max_seconds_to_end)
        log.info("  Max shares/mkt  : %s", self._cfg.max_shares_per_market)
        log.info("  Top-up enabled  : %s", self._cfg.top_up_enabled)
        log.info("  Fast top-up     : %s", self._cfg.fast_top_up_enabled)
        log.info("  Taker mode      : %s", self._cfg.taker_enabled)
        log.info("  Cancel buffer   : %ds", self._cfg.order_cancel_buffer_sec)
        log.info("  Auto-redeem     : %s", "enabled" if not self._cfg.dry_run and self._rpc_url else "disabled (dry-run)" if self._cfg.dry_run else "disabled (no RPC URL)")
        log.info("=" * 56)

        if not self._cfg.dry_run:
            self._cancel_orphaned_orders()

        tick_interval = max(0.1, self._cfg.refresh_millis / 1000.0)

        try:
            while True:
                self._tick()
                await asyncio.sleep(tick_interval)
        except asyncio.CancelledError:
            log.info("Engine cancelled, shutting down")
        finally:
            self._order_mgr.cancel_all(self._client, "SHUTDOWN", self._handle_fill)

    def _tick(self) -> None:
        """Single tick: discover, refresh positions, evaluate markets, check fills."""
        now = time.time()

        # Discovery every 30s
        if now - self._last_discovery > 30.0:
            old_market_lookup = {m.slug: m for m in self._active_markets}
            self._active_markets = discover_markets(self._cfg.assets)
            self._last_discovery = now
            self._balance_failures.clear()
            # Prune inventory and cancel orphaned orders for expired markets
            active_slugs = {m.slug for m in self._active_markets}
            for slug in list(self._inventory.get_all_inventories()):
                if slug not in active_slugs:
                    inv = self._inventory.get_inventory(slug)
                    market = old_market_lookup.get(slug)
                    has_shares = inv.up_shares > ZERO or inv.down_shares > ZERO
                    if has_shares and market and market.condition_id:
                        self._pending_redemptions[slug] = PendingRedemption(
                            market=market,
                            inventory=inv,
                            eligible_at=market.end_time + 60,
                        )
                        log.info("REDEEM_QUEUED %s U%s/D%s", slug, inv.up_shares, inv.down_shares)
                    self._inventory.clear_market(slug)
            for token_id in list(self._order_mgr.get_open_orders()):
                order = self._order_mgr.get_order(token_id)
                if order and order.market and order.market.slug not in active_slugs:
                    self._order_mgr.cancel_order(self._client, token_id, "MARKET_EXPIRED", self._handle_fill)
            self._log_market_transitions(now)
            self._log_summary(now)

        # Refresh positions
        self._inventory.refresh_if_stale(self._client)
        self._inventory.sync_inventory(self._active_markets)

        # Evaluate each market
        for market in self._active_markets:
            try:
                self._evaluate_market(market, now)
            except Exception as e:
                log.error("Error evaluating %s: %s", market.slug, e)

        # Check pending orders for fills
        self._order_mgr.check_pending_orders(self._client, self._handle_fill)

        # Check pending redemptions
        self._check_redemptions(now)

    def _handle_fill(self, state, filled_shares: Decimal) -> None:
        if state.market is None or state.direction is None:
            return
        is_up = state.direction == Direction.UP
        self._inventory.record_fill(state.market.slug, is_up, filled_shares, state.price)
        log.info(
            "FILL %s %s +%s shares @ %s",
            state.market.slug,
            state.direction.value,
            filled_shares,
            state.price,
        )

    def _check_redemptions(self, now: float) -> None:
        """Attempt to redeem resolved positions that are past the settlement delay."""
        for slug in list(self._pending_redemptions):
            pr = self._pending_redemptions[slug]
            if now < pr.eligible_at:
                continue
            if pr.attempts >= 3:
                log.error("REDEEM_FAILED %s after 3 attempts, dropping", slug)
                self._pending_redemptions.pop(slug)
                continue
            if pr.last_attempt_at and now - pr.last_attempt_at < 30:
                continue

            if self._cfg.dry_run:
                hedged = min(pr.inventory.up_shares, pr.inventory.down_shares)
                log.info(
                    "DRY_REDEEM %s U%s/D%s → expected $%s",
                    slug, pr.inventory.up_shares, pr.inventory.down_shares, hedged,
                )
                self._pending_redemptions.pop(slug)
                continue

            if not self._private_key or not self._rpc_url:
                log.warning("REDEEM_SKIP %s no credentials configured", slug)
                self._pending_redemptions.pop(slug)
                continue

            try:
                tx_hash = redeem_positions(
                    self._private_key, self._rpc_url, pr.market.condition_id,
                )
                log.info("REDEEMED %s tx=%s", slug, tx_hash)
                self._pending_redemptions.pop(slug)
            except Exception as e:
                pr.attempts += 1
                pr.last_attempt_at = now
                log.warning("REDEEM_ATTEMPT %s failed (%d/3): %s", slug, pr.attempts, e)

    def _cancel_orphaned_orders(self) -> None:
        """Cancel all open orders on the CLOB from a previous session."""
        try:
            open_orders = self._client.get_orders()
            if not open_orders:
                log.info("STARTUP no orphaned orders found")
                return
            count = len(open_orders) if isinstance(open_orders, list) else 0
            log.info("STARTUP found %d orphaned orders, cancelling all", count)
            self._client.cancel_all()
            log.info("STARTUP cancelled all orphaned orders")
        except Exception as e:
            log.warning("STARTUP orphan cleanup failed: %s", e)

    def _log_market_transitions(self, now: float) -> None:
        """Log markets entering/leaving the quotable time window."""
        quotable_now: set[str] = set()
        for m in self._active_markets:
            ste = int(m.end_time - now)
            max_lt = 900 if m.market_type == "updown-15m" else 3600
            min_ste = max(0, self._cfg.min_seconds_to_end)
            max_ste = min(max_lt, max(min_ste, self._cfg.max_seconds_to_end))
            if min_ste <= ste <= max_ste:
                quotable_now.add(m.slug)

        entered = quotable_now - self._prev_quotable_slugs
        exited = self._prev_quotable_slugs - quotable_now

        for slug in sorted(entered):
            log.info("ENTER window │ %s", slug)
        for slug in sorted(exited):
            log.info("EXIT  window │ %s", slug)

        self._prev_quotable_slugs = quotable_now

    def _log_summary(self, now: float) -> None:
        """Periodic summary: inventory, exposure, entry prices vs book."""
        open_orders = self._order_mgr.get_open_orders()
        all_inv = self._inventory.get_all_inventories()
        exposure = calculate_exposure(open_orders, all_inv)
        ord_notional, unhedged_notional, hedged_locked = calculate_exposure_breakdown(
            open_orders, all_inv,
        )
        open_count = len(open_orders)

        bankroll = self._cfg.bankroll_usd
        pct_used = (exposure / bankroll * 100).quantize(Decimal("0.1")) if bankroll > ZERO else ZERO
        session_pnl = self._inventory.session_realized_pnl.quantize(Decimal("0.01"))

        log.info(
            "── SUMMARY ── markets=%d │ open_orders=%d │ exposure=$%s │ "
            "bankroll=$%s (%s%% used) │ session_pnl=$%s",
            len(self._active_markets), open_count, exposure.quantize(Decimal("0.01")),
            bankroll, pct_used, session_pnl,
        )
        log.info(
            "  EXPOSURE open_orders=$%s │ unhedged=$%s │ hedged=$%s (excluded) │ effective=$%s",
            ord_notional.quantize(Decimal("0.01")),
            unhedged_notional.quantize(Decimal("0.01")),
            hedged_locked.quantize(Decimal("0.01")),
            exposure.quantize(Decimal("0.01")),
        )

        for market in self._active_markets:
            ste = int(market.end_time - now)
            inv = self._inventory.get_inventory(market.slug)
            hedged = min(inv.up_shares, inv.down_shares)

            # Position logging for markets with inventory
            if inv.up_shares > ZERO or inv.down_shares > ZERO:
                total_cost = (inv.up_cost + inv.down_cost).quantize(Decimal("0.01"))
                hedged_cost = (hedged * ONE).quantize(Decimal("0.01"))
                unhedged_cost = (total_cost - hedged_cost).quantize(Decimal("0.01")) if total_cost > hedged_cost else Decimal("0.00")
                log.info(
                    "  POSITION %s │ U%s/D%s │ hedged=%s │ cost=$%s │ locked=$%s │ risk=$%s",
                    market.slug[-40:],
                    inv.up_shares, inv.down_shares, hedged,
                    total_cost, hedged_cost, unhedged_cost,
                )

            up_book = get_top_of_book(self._client, market.up_token_id)
            down_book = get_top_of_book(self._client, market.down_token_id)

            up_bid = up_book.best_bid if up_book else None
            up_ask = up_book.best_ask if up_book else None
            dn_bid = down_book.best_bid if down_book else None
            dn_ask = down_book.best_ask if down_book else None

            # Compute what entry prices would be (no skew for summary)
            up_entry = calculate_entry_price(
                up_book, TICK_SIZE, self._cfg.improve_ticks, 0
            ) if up_book and up_bid is not None and up_ask is not None else None
            dn_entry = calculate_entry_price(
                down_book, TICK_SIZE, self._cfg.improve_ticks, 0
            ) if down_book and dn_bid is not None and dn_ask is not None else None

            edge_str = "?"
            if up_entry and dn_entry:
                edge = ONE - (up_entry + dn_entry)
                edge_str = f"{edge:.3f}"

            up_order = self._order_mgr.get_order(market.up_token_id)
            dn_order = self._order_mgr.get_order(market.down_token_id)
            up_ord_str = f"ord@{up_order.price}" if up_order else "---"
            dn_ord_str = f"ord@{dn_order.price}" if dn_order else "---"

            # Cost/VWAP segment for markets with hedged inventory
            if hedged > ZERO and inv.up_vwap is not None and inv.down_vwap is not None:
                total_cost = (inv.up_cost + inv.down_cost).quantize(Decimal("0.01"))
                cost_seg = f"cost=${total_cost} vwap=U{inv.up_vwap:.2f}/D{inv.down_vwap:.2f} │ "
            else:
                cost_seg = ""

            log.info(
                "  %s │ %ds │ inv=U%s/D%s(h%s) │ %s"
                "book=U[%s/%s] D[%s/%s] │ entry=U%s D%s │ edge=%s │ %s %s",
                market.slug[-30:], ste,
                inv.up_shares, inv.down_shares, hedged,
                cost_seg,
                up_bid, up_ask, dn_bid, dn_ask,
                up_entry or "?", dn_entry or "?", edge_str,
                up_ord_str, dn_ord_str,
            )

    def _evaluate_market(self, market: GabagoolMarket, now: float) -> None:
        seconds_to_end = int(market.end_time - now)
        max_lifetime = 900 if market.market_type == "updown-15m" else 3600

        # Pre-resolution buffer: cancel all orders to avoid buying worthless shares
        if 0 <= seconds_to_end < self._cfg.order_cancel_buffer_sec:
            self._order_mgr.cancel_market_orders(self._client, market, "PRE_RESOLUTION_BUFFER", self._handle_fill)
            return

        # Outside lifetime
        if seconds_to_end < 0 or seconds_to_end > max_lifetime:
            self._order_mgr.cancel_market_orders(self._client, market, "OUTSIDE_LIFETIME", self._handle_fill)
            return

        # Outside configured time window
        min_ste = max(0, self._cfg.min_seconds_to_end)
        max_ste = min(max_lifetime, max(min_ste, self._cfg.max_seconds_to_end))
        if seconds_to_end < min_ste or seconds_to_end > max_ste:
            self._order_mgr.cancel_market_orders(self._client, market, "OUTSIDE_TIME_WINDOW", self._handle_fill)
            return

        # Fetch TOB for both legs
        up_book = get_top_of_book(self._client, market.up_token_id)
        down_book = get_top_of_book(self._client, market.down_token_id)

        if not up_book or not down_book:
            self._order_mgr.cancel_market_orders(self._client, market, "BOOK_STALE", self._handle_fill)
            return
        if up_book.best_bid is None or up_book.best_ask is None:
            self._order_mgr.cancel_order(self._client, market.up_token_id, "BOOK_STALE", self._handle_fill)
            return
        if down_book.best_bid is None or down_book.best_ask is None:
            self._order_mgr.cancel_order(self._client, market.down_token_id, "BOOK_STALE", self._handle_fill)
            return

        inv = self._inventory.get_inventory(market.slug)
        skew_up, skew_down = calculate_skew_ticks(
            inv, self._cfg.max_skew_ticks, self._cfg.imbalance_for_max_skew
        )

        # Fast top-up after recent fill
        self._maybe_fast_top_up(market, inv, up_book, down_book, seconds_to_end)

        # Near-end taker top-up
        if self._cfg.top_up_enabled and seconds_to_end <= self._cfg.top_up_seconds_to_end:
            abs_imbalance = abs(inv.imbalance)
            if abs_imbalance >= self._cfg.top_up_min_shares:
                if inv.imbalance > ZERO:
                    lagging = Direction.DOWN
                    lagging_book = down_book
                    lagging_token = market.down_token_id
                else:
                    lagging = Direction.UP
                    lagging_book = up_book
                    lagging_token = market.up_token_id
                self._maybe_top_up_lagging(
                    market, lagging_token, lagging, lagging_book, seconds_to_end,
                    abs_imbalance, "TOP_UP",
                )

        # Calculate entry prices
        up_entry = calculate_entry_price(up_book, TICK_SIZE, self._cfg.improve_ticks, skew_up)
        down_entry = calculate_entry_price(down_book, TICK_SIZE, self._cfg.improve_ticks, skew_down)
        if up_entry is None or down_entry is None:
            self._order_mgr.cancel_market_orders(self._client, market, "BOOK_STALE", self._handle_fill)
            return

        # Edge check — don't cancel existing orders, just skip new quotes.
        # Existing orders were placed when edge was sufficient; let them ride
        # until stale timeout or a valid replacement comes along.
        if not has_minimum_edge(up_entry, down_entry, self._cfg.min_edge):
            log.debug("Skipping %s - insufficient edge (%.3f)", market.slug,
                       ONE - (up_entry + down_entry))
            return

        # Optional taker mode
        planned_edge = ONE - (up_entry + down_entry)
        if self._should_take(planned_edge, up_book, down_book):
            take_leg = self._decide_taker_leg(inv, up_book, down_book)
            if take_leg == Direction.UP:
                self._maybe_take_token(market, market.up_token_id, Direction.UP, up_book, seconds_to_end)
                self._maybe_quote_token(market, market.down_token_id, Direction.DOWN, down_book, seconds_to_end, skew_down)
                return
            elif take_leg == Direction.DOWN:
                self._maybe_take_token(market, market.down_token_id, Direction.DOWN, down_book, seconds_to_end)
                self._maybe_quote_token(market, market.up_token_id, Direction.UP, up_book, seconds_to_end, skew_up)
                return

        # Maker mode: quote both legs with balanced share count
        exposure = calculate_exposure(
            self._order_mgr.get_open_orders(),
            self._inventory.get_all_inventories(),
        )
        balanced = calculate_balanced_shares(
            market.slug, up_entry, down_entry, self._cfg, seconds_to_end, exposure,
        )
        self._maybe_quote_token(market, market.up_token_id, Direction.UP, up_book, seconds_to_end, skew_up, pre_shares=balanced)
        self._maybe_quote_token(market, market.down_token_id, Direction.DOWN, down_book, seconds_to_end, skew_down, pre_shares=balanced)

    def _maybe_quote_token(
        self,
        market: GabagoolMarket,
        token_id: str,
        direction: Direction,
        book: TopOfBook,
        seconds_to_end: int,
        skew_ticks: int,
        pre_shares: Decimal | None = None,
    ) -> None:
        if self._balance_failures.get(market.slug, 0) >= 3:
            return

        entry_price = calculate_entry_price(book, TICK_SIZE, self._cfg.improve_ticks, skew_ticks)
        if entry_price is None:
            return

        # Hard cap: skip quoting if hedged inventory already at limit
        if self._cfg.max_shares_per_market > ZERO:
            inv = self._inventory.get_inventory(market.slug)
            hedged = min(inv.up_shares, inv.down_shares)
            if hedged >= self._cfg.max_shares_per_market:
                log.debug(
                    "Skipping %s %s - at max_shares_per_market (%s hedged)",
                    market.slug, direction.value, hedged,
                )
                return

        if pre_shares is not None:
            shares = pre_shares
        else:
            exposure = calculate_exposure(
                self._order_mgr.get_open_orders(),
                self._inventory.get_all_inventories(),
            )
            shares = calculate_shares(market.slug, entry_price, self._cfg, seconds_to_end, exposure)
        if shares is None:
            return

        min_price_change = TICK_SIZE * self._cfg.min_replace_ticks
        decision = self._order_mgr.maybe_replace(
            token_id, entry_price, shares, self._cfg.min_replace_millis,
            min_price_change=min_price_change,
        )
        if decision == ReplaceDecision.SKIP:
            return

        if decision == ReplaceDecision.REPLACE:
            self._order_mgr.cancel_order(self._client, token_id, "REPLACE_PRICE", self._handle_fill)

        reason = "REPLACE" if decision == ReplaceDecision.REPLACE else "QUOTE"
        success = self._order_mgr.place_order(
            self._client, market, token_id, direction,
            entry_price, shares, seconds_to_end, reason,
            on_fill=self._handle_fill,
        )
        if not success:
            self._balance_failures[market.slug] = self._balance_failures.get(market.slug, 0) + 1
        else:
            self._balance_failures.pop(market.slug, None)

    def _maybe_take_token(
        self,
        market: GabagoolMarket,
        token_id: str,
        direction: Direction,
        book: TopOfBook,
        seconds_to_end: int,
    ) -> None:
        if self._balance_failures.get(market.slug, 0) >= 3:
            return

        if book.best_ask is None or book.best_ask > Decimal("0.99"):
            return

        exposure = calculate_exposure(
            self._order_mgr.get_open_orders(),
            self._inventory.get_all_inventories(),
        )
        shares = calculate_shares(market.slug, book.best_ask, self._cfg, seconds_to_end, exposure)
        if shares is None:
            return

        existing = self._order_mgr.get_order(token_id)
        if existing:
            age_ms = (time.time() - existing.placed_at) * 1000
            if age_ms < self._cfg.min_replace_millis:
                return
            self._order_mgr.cancel_order(self._client, token_id, "REPLACE_TAKER", self._handle_fill)

        log.info(
            "TAKER %s on %s at ask %s (size=%s, %ds left)",
            direction.value, market.slug, book.best_ask, shares, seconds_to_end,
        )
        success = self._order_mgr.place_order(
            self._client, market, token_id, direction,
            book.best_ask, shares, seconds_to_end, "TAKER",
            on_fill=self._handle_fill,
        )
        if not success:
            self._balance_failures[market.slug] = self._balance_failures.get(market.slug, 0) + 1
        else:
            self._balance_failures.pop(market.slug, None)

    def _maybe_fast_top_up(
        self,
        market: GabagoolMarket,
        inv,
        up_book: TopOfBook,
        down_book: TopOfBook,
        seconds_to_end: int,
    ) -> None:
        if not self._cfg.fast_top_up_enabled:
            return

        imbalance = inv.imbalance
        abs_imbalance = abs(imbalance)
        if abs_imbalance < self._cfg.top_up_min_shares:
            return

        now = time.time()
        if (
            inv.last_top_up_at is not None
            and (now - inv.last_top_up_at) * 1000 < self._cfg.fast_top_up_cooldown_millis
        ):
            return

        # Determine lagging leg
        if imbalance > ZERO:
            lagging = Direction.DOWN
            lead_fill_at = inv.last_up_fill_at
            lag_fill_at = inv.last_down_fill_at
            lagging_book = down_book
            lagging_token = market.down_token_id
            lead_fill_price = inv.up_vwap  # VWAP instead of last fill
        else:
            lagging = Direction.UP
            lead_fill_at = inv.last_down_fill_at
            lag_fill_at = inv.last_up_fill_at
            lagging_book = up_book
            lagging_token = market.up_token_id
            lead_fill_price = inv.down_vwap  # VWAP instead of last fill

        if lead_fill_at is None:
            log.debug("FAST_TOP_UP_SKIP %s no lead fill timestamp", market.slug)
            return

        since_lead_fill = now - lead_fill_at
        log.debug(
            "FAST_TOP_UP_CHECK %s imbalance=%s lagging=%s lead_fill=%.1fs ago "
            "lag_fill=%s spread=%s",
            market.slug, imbalance, lagging.value, since_lead_fill,
            f"{now - lag_fill_at:.1f}s ago" if lag_fill_at else "none",
            f"{lagging_book.best_ask - lagging_book.best_bid}"
            if lagging_book.best_bid is not None and lagging_book.best_ask is not None
            else "?",
        )
        if (
            since_lead_fill < self._cfg.fast_top_up_min_seconds
            or since_lead_fill > self._cfg.fast_top_up_max_seconds
        ):
            log.debug(
                "FAST_TOP_UP_SKIP %s since_lead=%.1fs outside [%s, %s]",
                market.slug, since_lead_fill,
                self._cfg.fast_top_up_min_seconds, self._cfg.fast_top_up_max_seconds,
            )
            return

        # Lag fill must be before lead fill (or absent), but ignore fills
        # that resulted from our own top-up (lag_fill_at >= last_top_up_at).
        if lag_fill_at is not None and lag_fill_at >= lead_fill_at:
            if inv.last_top_up_at is None or lag_fill_at < inv.last_top_up_at:
                log.debug("FAST_TOP_UP_SKIP %s lag fill after lead fill", market.slug)
                return

        if lagging_book.best_bid is None or lagging_book.best_ask is None:
            log.debug("FAST_TOP_UP_SKIP %s no book for lagging side", market.slug)
            return
        spread = lagging_book.best_ask - lagging_book.best_bid
        if spread > self._cfg.taker_max_spread:
            log.debug(
                "FAST_TOP_UP_SKIP %s spread %s > max %s",
                market.slug, spread, self._cfg.taker_max_spread,
            )
            return

        # Check hedged edge (use 0.0 for breakeven-or-better hedging)
        if lead_fill_price is None:
            if lagging == Direction.DOWN:
                lead_fill_price = up_book.best_bid
            else:
                lead_fill_price = down_book.best_bid
        if lead_fill_price is not None:
            hedged_edge = ONE - (lead_fill_price + lagging_book.best_ask)
            if hedged_edge < self._cfg.fast_top_up_min_edge:
                log.debug(
                    "FAST_TOP_UP_SKIP %s hedged_edge=%s < min_edge=%s",
                    market.slug, hedged_edge, self._cfg.fast_top_up_min_edge,
                )
                return

        self._inventory.mark_top_up(market.slug)
        self._maybe_top_up_lagging(
            market, lagging_token, lagging, lagging_book, seconds_to_end,
            abs_imbalance, "FAST_TOP_UP",
        )

    def _maybe_top_up_lagging(
        self,
        market: GabagoolMarket,
        token_id: str,
        direction: Direction,
        book: TopOfBook,
        seconds_to_end: int,
        imbalance_shares: Decimal,
        reason: str,
    ) -> None:
        if self._balance_failures.get(market.slug, 0) >= 3:
            log.debug("TOP_UP_SKIP %s too many balance failures", market.slug)
            return
        if imbalance_shares < Decimal("0.01"):
            log.debug("TOP_UP_SKIP %s imbalance too small (%s)", market.slug, imbalance_shares)
            return
        if book.best_ask is None or book.best_ask > Decimal("0.99"):
            log.debug("TOP_UP_SKIP %s bad ask (%s)", market.slug, book.best_ask)
            return

        # Check spread
        if book.best_bid is not None:
            spread = book.best_ask - book.best_bid
            if spread > self._cfg.taker_max_spread:
                log.debug(
                    "TOP_UP_SKIP %s spread %s > max %s",
                    market.slug, spread, self._cfg.taker_max_spread,
                )
                return

        top_up_shares = imbalance_shares
        bankroll = self._cfg.bankroll_usd

        # Per-order cap
        if bankroll > ZERO and self._cfg.max_order_bankroll_fraction > ZERO:
            per_order_cap = bankroll * self._cfg.max_order_bankroll_fraction
            cap = (per_order_cap / book.best_ask).quantize(Decimal("0.01"))
            top_up_shares = min(top_up_shares, cap)

        # NOTE: total bankroll cap intentionally skipped for top-ups.
        # Top-ups hedge an existing imbalance — they reduce risk, not add it.
        # The per-order cap above still limits individual top-up size.

        top_up_shares = top_up_shares.quantize(Decimal("0.01"))
        if top_up_shares < Decimal("0.01"):
            log.debug("TOP_UP_SKIP %s capped shares too small", market.slug)
            return

        # Cancel existing order if any
        existing = self._order_mgr.get_order(token_id)
        if existing:
            age_ms = (time.time() - existing.placed_at) * 1000
            if age_ms < self._cfg.min_replace_millis:
                log.debug(
                    "TOP_UP_SKIP %s existing order too young (%dms < %dms)",
                    market.slug, age_ms, self._cfg.min_replace_millis,
                )
                return
            self._order_mgr.cancel_order(self._client, token_id, "REPLACE_TOP_UP", self._handle_fill)

        log.info(
            "TOP-UP %s on %s at ask %s (imbalance=%s, shares=%s, %ds left) [%s]",
            direction.value, market.slug, book.best_ask,
            imbalance_shares, top_up_shares, seconds_to_end, reason,
        )
        success = self._order_mgr.place_order(
            self._client, market, token_id, direction,
            book.best_ask, top_up_shares, seconds_to_end, reason,
            on_fill=self._handle_fill,
        )
        if not success:
            self._balance_failures[market.slug] = self._balance_failures.get(market.slug, 0) + 1
        else:
            self._balance_failures.pop(market.slug, None)

    def _should_take(
        self, edge: Decimal, up_book: TopOfBook, down_book: TopOfBook
    ) -> bool:
        if not self._cfg.taker_enabled:
            return False
        if edge > self._cfg.taker_max_edge:
            return False

        up_spread = up_book.best_ask - up_book.best_bid
        down_spread = down_book.best_ask - down_book.best_bid

        if up_spread > self._cfg.taker_max_spread or down_spread > self._cfg.taker_max_spread:
            return False

        log.debug(
            "Taker mode triggered - edge=%s, upSpread=%s, downSpread=%s",
            edge, up_spread, down_spread,
        )
        return True

    def _decide_taker_leg(self, inv, up_book: TopOfBook, down_book: TopOfBook):
        bid_up = up_book.best_bid
        ask_up = up_book.best_ask
        bid_down = down_book.best_bid
        ask_down = down_book.best_ask

        if None in (bid_up, ask_up, bid_down, ask_down):
            return None

        edge_take_up = ONE - (ask_up + bid_down)
        edge_take_down = ONE - (bid_up + ask_down)
        min_edge = self._cfg.fast_top_up_min_edge

        up_ok = edge_take_up >= min_edge
        down_ok = edge_take_down >= min_edge

        if not up_ok and not down_ok:
            return None
        if up_ok and not down_ok:
            return Direction.UP
        if down_ok and not up_ok:
            return Direction.DOWN

        if edge_take_up > edge_take_down:
            return Direction.UP
        if edge_take_down > edge_take_up:
            return Direction.DOWN

        imbalance = inv.imbalance
        if imbalance > ZERO:
            return Direction.DOWN
        if imbalance < ZERO:
            return Direction.UP
        return Direction.UP
