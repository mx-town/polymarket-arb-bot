"""Strategy tick loop — two-phase asymmetric hedge for complete-set arbitrage.

Per-window lifecycle:
1. No position: buy cheapest leg if ask < (1 - min_edge) / 2 (FOK)
2. One leg filled: hedge the other if first_vwap + second_ask < 1 - min_edge (FOK)
3. Both legs filled (hedged >= min_merge_shares): mark complete, merge
4. Buffer: stop new orders + sell unhedged legs when seconds_to_end < no_new_orders_sec
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal

from complete_set.config import CompleteSetConfig
from complete_set.inventory import InventoryTracker
from complete_set.market_data import discover_markets, get_top_of_book
from complete_set.models import (
    Direction,
    GabagoolMarket,
    PendingRedemption,
)
from complete_set.order_mgr import OrderManager
from py_clob_client.clob_types import OrderType
from complete_set.quote_calc import (
    calculate_balanced_shares,
    calculate_dynamic_edge,
    calculate_exposure,
    calculate_exposure_breakdown,
)
from complete_set.redeem import CTF_DECIMALS, get_ctf_balances, get_usdc_balance, merge_positions, redeem_positions

log = logging.getLogger("cs.engine")

ZERO = Decimal("0")
ONE = Decimal("1")
TICK_SIZE = Decimal("0.01")  # Default Polymarket tick size

# ANSI colors for log highlights
C_GREEN = "\033[32m"
C_RED = "\033[31m"
C_YELLOW = "\033[33m"
C_RESET = "\033[0m"


class Engine:
    def __init__(
        self, client, cfg: CompleteSetConfig,
        w3=None, account=None, rpc_url: str = "", funder_address: str = "",
    ):
        self._client = client
        self._cfg = cfg
        self._w3 = w3
        self._account = account
        self._rpc_url = rpc_url
        self._funder_address = funder_address
        self._order_mgr = OrderManager(dry_run=cfg.dry_run)
        self._inventory = InventoryTracker(dry_run=cfg.dry_run)
        self._active_markets: list[GabagoolMarket] = []
        self._last_discovery: float = 0.0
        self._prev_quotable_slugs: set[str] = set()
        self._completed_markets: set[str] = set()
        self._pending_redemptions: dict[str, PendingRedemption] = {}
        self._merge_failures: dict[str, int] = {}  # slug -> consecutive failures
        self._merge_last_attempt: dict[str, float] = {}  # slug -> timestamp
        self._pending_merge_task: dict[str, asyncio.Task] = {}   # slug -> Task
        self._pending_redeem_task: dict[str, asyncio.Task] = {}  # slug -> Task
        self._start_time: float = time.time()
        self._last_session_log: float = 0.0
        self._bg_discovery: asyncio.Task | None = None
        self._bg_refresh: asyncio.Task | None = None
        self._cached_wallet_bal: str = "n/a"

    async def run(self) -> None:
        """Main event loop."""
        mode = "DRY RUN" if self._cfg.dry_run else "LIVE"
        log.info("=" * 56)
        log.info("  Complete-Set Arb Engine v0.3.0 TWO-PHASE  [%s]", mode)
        log.info("=" * 56)
        log.info("  Assets          : %s", ", ".join(self._cfg.assets))
        log.info("  Tick interval   : %dms", self._cfg.refresh_millis)
        log.info("  Min edge        : %s", self._cfg.min_edge)
        log.info("  Bankroll        : $%s", self._cfg.bankroll_usd)
        log.info("  Time window     : %d-%ds", self._cfg.min_seconds_to_end, self._cfg.max_seconds_to_end)
        log.info("  No new orders   : %ds", self._cfg.no_new_orders_sec)
        log.info("  Min merge shares: %s", self._cfg.min_merge_shares)
        if not self._cfg.dry_run and self._w3 and self._account:
            redeem_mode = "enabled (on-chain)"
        elif self._cfg.dry_run:
            redeem_mode = "disabled (dry-run)"
        else:
            redeem_mode = "disabled (no w3/account)"
        log.info("  Auto-redeem     : %s", redeem_mode)
        log.info("=" * 56)

        if not self._cfg.dry_run:
            self._cancel_orphaned_orders()

        # Initial position sync — detect existing chain positions before first tick
        self._active_markets = discover_markets(self._cfg.assets)
        self._last_discovery = time.time()
        self._inventory.refresh_if_stale(self._client, self._active_markets)
        self._inventory.sync_inventory(self._active_markets, get_mid_price=self._get_mid_price)
        self._log_summary(time.time())

        tick_interval = max(0.1, self._cfg.refresh_millis / 1000.0)

        try:
            while True:
                await self._tick()
                await asyncio.sleep(tick_interval)
        except asyncio.CancelledError:
            log.info("Engine cancelled, shutting down")
        finally:
            self._order_mgr.cancel_all(self._client, "SHUTDOWN", self._handle_fill)

    async def _tick(self) -> None:
        """Single tick: harvest bg, launch bg, evaluate+settle."""
        now = time.time()

        # -- Harvest background results (fast, no I/O) --
        if self._bg_discovery is not None and self._bg_discovery.done():
            try:
                new_markets = self._bg_discovery.result()
                self._apply_discovery(new_markets, now)
            except Exception as e:
                log.warning("Discovery failed: %s", e)
            self._bg_discovery = None

        if self._bg_refresh is not None and self._bg_refresh.done():
            try:
                self._bg_refresh.result()
            except Exception:
                pass
            self._bg_refresh = None

        # -- Launch background I/O (non-blocking) --
        if now - self._last_discovery > 30.0 and self._bg_discovery is None:
            self._last_discovery = now
            self._bg_discovery = asyncio.ensure_future(
                asyncio.to_thread(discover_markets, self._cfg.assets)
            )

        if (
            self._bg_refresh is None
            and not self._cfg.dry_run
            and now - self._inventory._last_refresh >= 5.0
        ):
            self._bg_refresh = asyncio.ensure_future(
                asyncio.to_thread(
                    self._inventory.refresh_if_stale,
                    self._client, self._active_markets,
                )
            )

        # -- Sync + evaluate in thread pool (blocks thread, not event loop) --
        await asyncio.to_thread(self._tick_core, now)

        # -- Settlements (needs asyncio for task management) --
        self._check_settlements(now)

    def _tick_core(self, now: float) -> None:
        """Synchronous evaluate phase - runs in thread pool."""
        self._inventory.sync_inventory(
            self._active_markets, get_mid_price=self._get_mid_price,
        )
        for market in self._active_markets:
            try:
                self._evaluate_market(market, now)
            except Exception as e:
                log.error("%sError evaluating %s: %s%s", C_RED, market.slug, e, C_RESET)
        self._order_mgr.check_pending_orders(self._client, self._handle_fill)

    def _apply_discovery(self, new_markets: list[GabagoolMarket], now: float) -> None:
        """Apply results from background discovery."""
        old_market_lookup = {m.slug: m for m in self._active_markets}
        self._active_markets = new_markets

        active_slugs = {m.slug for m in self._active_markets}
        self._completed_markets &= active_slugs
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
                    log.info("%sREDEEM_QUEUED %s U%s/D%s%s", C_YELLOW, slug, inv.up_shares, inv.down_shares, C_RESET)
                self._inventory.clear_market(slug)
        for token_id in list(self._order_mgr.get_open_orders()):
            order = self._order_mgr.get_order(token_id)
            if order and order.market and order.market.slug not in active_slugs:
                self._order_mgr.cancel_order(self._client, token_id, "MARKET_EXPIRED", self._handle_fill)
        self._log_market_transitions(now)
        self._log_summary(now)

    def _handle_fill(self, state, filled_shares: Decimal) -> None:
        if state.market is None or state.direction is None:
            return
        is_up = state.direction == Direction.UP

        if state.side == "SELL":
            self._inventory.record_sell_fill(state.market.slug, is_up, filled_shares, state.price)
            log.info(
                "%sSELL_FILL %s %s -%s shares @ %s%s",
                C_YELLOW,
                state.market.slug,
                state.direction.value,
                filled_shares,
                state.price,
                C_RESET,
            )
            return

        self._inventory.record_fill(state.market.slug, is_up, filled_shares, state.price)
        log.info(
            "%sFILL %s %s +%s shares @ %s%s",
            C_GREEN,
            state.market.slug,
            state.direction.value,
            filled_shares,
            state.price,
            C_RESET,
        )
        # Check if hedge is complete (both legs filled above min_merge_shares)
        inv = self._inventory.get_inventory(state.market.slug)
        hedged = min(inv.up_shares, inv.down_shares)
        if hedged >= self._cfg.min_merge_shares:
            self._completed_markets.add(state.market.slug)
            edge = ONE - (inv.up_vwap + inv.down_vwap) if inv.up_vwap and inv.down_vwap else ZERO
            log.info(
                "%sHEDGE_COMPLETE %s │ hedged=%s │ edge=%s%s",
                C_GREEN, state.market.slug, hedged, edge, C_RESET,
            )

    def _check_settlements(self, now: float) -> None:
        """Merge hedged pairs on active markets, then redeem resolved positions."""
        # ── Merge hedged pairs back to USDC on active markets ──
        if not self._cfg.dry_run and self._w3 and self._account:
            # Phase A — Harvest completed merge tasks
            for slug in list(self._pending_merge_task):
                task = self._pending_merge_task[slug]
                if not task.done():
                    continue
                del self._pending_merge_task[slug]
                try:
                    result = task.result()
                    if result is None:
                        # Balance too low, skip
                        continue
                    tx_hash, merged_display = result
                    self._inventory.reduce_merged(slug, merged_display)
                    self._merge_failures.pop(slug, None)
                    self._completed_markets.discard(slug)
                    log.info(
                        "%sMERGE_POSITION %s │ merged=%s shares │ tx=%s%s",
                        C_GREEN, slug, merged_display, tx_hash, C_RESET,
                    )
                except Exception as e:
                    failures = self._merge_failures.get(slug, 0) + 1
                    self._merge_failures[slug] = failures
                    log.warning(
                        "%sMERGE_FAILED %s │ attempt %d/5 │ %s%s",
                        C_YELLOW, slug, failures, e, C_RESET,
                    )

            # Phase B — Launch new merges (one per tick, non-blocking)
            for market in self._active_markets:
                slug = market.slug
                if slug in self._pending_merge_task:
                    continue
                inv = self._inventory.get_inventory(slug)
                hedged = min(inv.up_shares, inv.down_shares)
                if hedged < self._cfg.min_merge_shares:
                    continue
                if not market.condition_id:
                    continue
                if self._merge_failures.get(slug, 0) >= 5:
                    continue
                last_attempt = self._merge_last_attempt.get(slug, 0.0)
                if now - last_attempt < 15:
                    continue
                seconds_to_end = int(market.end_time - now)
                if seconds_to_end < self._cfg.no_new_orders_sec:
                    continue

                self._merge_last_attempt[slug] = now

                min_base = int(self._cfg.min_merge_shares * (10 ** CTF_DECIMALS))
                task = asyncio.ensure_future(asyncio.to_thread(
                    self._do_merge_io, slug, market, min_base,
                ))
                self._pending_merge_task[slug] = task
                log.info("MERGE_LAUNCHED %s", slug)
                break
        elif self._cfg.dry_run:
            for market in self._active_markets:
                slug = market.slug
                inv = self._inventory.get_inventory(slug)
                hedged = min(inv.up_shares, inv.down_shares)
                if hedged < self._cfg.min_merge_shares:
                    continue
                if not market.condition_id:
                    continue
                # Cooldown: 15s between merge attempts per market
                last_attempt = self._merge_last_attempt.get(slug, 0.0)
                if now - last_attempt < 15:
                    continue
                # Don't merge too close to resolution
                seconds_to_end = int(market.end_time - now)
                if seconds_to_end < self._cfg.no_new_orders_sec:
                    continue

                self._merge_last_attempt[slug] = now
                self._inventory.reduce_merged(slug, hedged)
                # Allow re-entry on this market for another cycle
                self._completed_markets.discard(slug)
                log.info(
                    "DRY_MERGE %s │ merged=%s shares → freed $%s",
                    slug, hedged, hedged,
                )
                # Only one merge per tick (mirror live behavior)
                break

        # ── Redeem resolved positions ──
        # Phase A — Harvest completed redeem tasks
        for slug in list(self._pending_redeem_task):
            task = self._pending_redeem_task[slug]
            if not task.done():
                continue
            del self._pending_redeem_task[slug]
            try:
                tx_hash = task.result()
                log.info("%sREDEEMED %s tx=%s%s", C_GREEN, slug, tx_hash, C_RESET)
                self._pending_redemptions.pop(slug, None)
            except Exception as e:
                pr = self._pending_redemptions.get(slug)
                if pr:
                    pr.attempts += 1
                    pr.last_attempt_at = now
                log.warning("%sREDEEM_FAILED %s │ %s%s", C_YELLOW, slug, e, C_RESET)

        # Phase B — Launch new redeems
        for slug in list(self._pending_redemptions):
            pr = self._pending_redemptions[slug]
            if slug in self._pending_redeem_task:
                continue
            if now < pr.eligible_at:
                continue
            if pr.attempts >= 3:
                log.error("%sREDEEM_FAILED %s after 3 attempts, dropping%s", C_RED, slug, C_RESET)
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

            if not self._w3 or not self._account:
                log.warning("%sREDEEM_SKIP %s no w3/account configured%s", C_YELLOW, slug, C_RESET)
                self._pending_redemptions.pop(slug)
                continue

            redeem_amount = 0
            if pr.market.neg_risk:
                redeem_shares = max(pr.inventory.up_shares, pr.inventory.down_shares)
                redeem_amount = int(redeem_shares * (10 ** CTF_DECIMALS))

            task = asyncio.ensure_future(asyncio.to_thread(
                redeem_positions, self._w3, self._account, self._funder_address,
                pr.market.condition_id, neg_risk=pr.market.neg_risk, amount=redeem_amount,
            ))
            self._pending_redeem_task[slug] = task
            log.info("REDEEM_LAUNCHED %s", slug)

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
            log.warning("%sSTARTUP orphan cleanup failed: %s%s", C_YELLOW, e, C_RESET)

    def _do_merge_io(
        self, slug: str, market: GabagoolMarket, min_base: int,
    ) -> tuple[str, Decimal] | None:
        """Run balance check + merge in thread pool. Returns (tx_hash, merged_shares) or None."""
        actual_up, actual_down = get_ctf_balances(
            self._rpc_url, self._funder_address,
            market.up_token_id, market.down_token_id,
        )
        amount_base = min(actual_up, actual_down)
        if amount_base < min_base:
            log.debug("MERGE_SKIP %s │ on-chain balance too low (up=%d, down=%d)", slug, actual_up, actual_down)
            return None
        merged_display = Decimal(amount_base) / Decimal(10 ** CTF_DECIMALS)
        tx_hash = merge_positions(
            self._w3, self._account, self._funder_address,
            market.condition_id, amount_base, neg_risk=market.neg_risk,
        )
        return (tx_hash, merged_display)

    def _refresh_wallet_balance(self) -> None:
        """Launch background wallet balance refresh."""
        def _fetch():
            try:
                bal = get_usdc_balance(self._rpc_url, self._funder_address)
                self._cached_wallet_bal = f"${bal.quantize(Decimal('0.01'))}"
            except Exception:
                self._cached_wallet_bal = "err"
        asyncio.ensure_future(asyncio.to_thread(_fetch))

    def _get_mid_price(self, token_id: str) -> Decimal | None:
        """Return mid-market price for a token, or None if book is unavailable."""
        tob = get_top_of_book(self._client, token_id)
        if tob and tob.best_bid is not None and tob.best_ask is not None:
            return (tob.best_bid + tob.best_ask) / 2
        return None

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
            log.info("%sENTER window │ %s%s", C_GREEN, slug, C_RESET)
        for slug in sorted(exited):
            log.info("%sEXIT  window │ %s%s", C_YELLOW, slug, C_RESET)

        self._prev_quotable_slugs = quotable_now

    def _log_summary(self, now: float) -> None:
        """Periodic summary: P&L dashboard with inventory, exposure, entry prices vs book."""
        open_orders = self._order_mgr.get_open_orders()
        all_inv = self._inventory.get_all_inventories()
        exposure = calculate_exposure(open_orders, all_inv)
        ord_notional, unhedged_exp, hedged_locked, total_exp = calculate_exposure_breakdown(
            open_orders, all_inv,
        )
        open_count = len(open_orders)

        bankroll = self._cfg.bankroll_usd
        total_cap = bankroll * self._cfg.max_total_bankroll_fraction if bankroll > ZERO and self._cfg.max_total_bankroll_fraction > ZERO else bankroll
        remaining = max(ZERO, total_cap - exposure) if total_cap > ZERO else ZERO
        deployed = self._inventory.session_total_deployed
        pct_used = (deployed / bankroll * 100).quantize(Decimal("0.1")) if bankroll > ZERO else ZERO

        # Compute total unrealized PnL across all inventories
        total_unrealized = ZERO
        for _slug, inv in all_inv.items():
            hedged = min(inv.up_shares, inv.down_shares)
            if hedged > ZERO and inv.up_vwap is not None and inv.down_vwap is not None:
                hedged_value = hedged * ONE
                hedged_cost = hedged * (inv.up_vwap + inv.down_vwap)
                total_unrealized += hedged_value - hedged_cost

        realized = self._inventory.session_realized_pnl.quantize(Decimal("0.01"))
        unrealized = total_unrealized.quantize(Decimal("0.01"))
        total_pnl = (self._inventory.session_realized_pnl + total_unrealized).quantize(Decimal("0.01"))
        pnl_color = C_GREEN if total_pnl >= ZERO else C_RED

        # ── SESSION summary every 300s ──
        if now - self._last_session_log >= 300:
            self._last_session_log = now
            runtime_s = int(now - self._start_time)
            if runtime_s >= 3600:
                runtime_str = f"{runtime_s // 3600}h {(runtime_s % 3600) // 60}m"
            else:
                runtime_str = f"{runtime_s // 60}m"
            roi = (total_pnl / bankroll * 100).quantize(Decimal("0.01")) if bankroll > ZERO else ZERO
            log.info(
                "%s═══ SESSION ═══ runtime=%s │ realized=$%s │ unrealized=$%s │ "
                "total=$%s │ ROI=%s%%%s",
                pnl_color, runtime_str, realized, unrealized, total_pnl, roi, C_RESET,
            )

        # ── Wallet balance (cached, refreshed in background) ──
        wallet_str = self._cached_wallet_bal
        if self._rpc_url and self._funder_address:
            self._refresh_wallet_balance()

        # ── SUMMARY header ──
        log.info(
            "── SUMMARY ── markets=%d │ open_orders=%d │ completed=%d │ exposure=$%s │ "
            "bankroll=$%s (%s%% used) │ wallet=%s │ %srealized=$%s │ unrealized=$%s │ total=$%s%s",
            len(self._active_markets), open_count, len(self._completed_markets),
            exposure.quantize(Decimal("0.01")),
            bankroll, pct_used, wallet_str,
            pnl_color, realized, unrealized, total_pnl, C_RESET,
        )
        log.info(
            "  EXPOSURE orders=$%s │ unhedged=$%s │ hedged_locked=$%s │ total=$%s │ remaining=$%s",
            ord_notional.quantize(Decimal("0.01")),
            unhedged_exp.quantize(Decimal("0.01")),
            hedged_locked.quantize(Decimal("0.01")),
            exposure.quantize(Decimal("0.01")),
            remaining.quantize(Decimal("0.01")),
        )

        for market in self._active_markets:
            ste = int(market.end_time - now)
            inv = self._inventory.get_inventory(market.slug)
            hedged = min(inv.up_shares, inv.down_shares)

            # POSITION + UNREALIZED lines for markets with inventory
            if inv.up_shares > ZERO or inv.down_shares > ZERO:
                cost = (inv.up_cost + inv.down_cost).quantize(Decimal("0.01"))
                abs_imbalance = abs(inv.imbalance)
                if abs_imbalance > ZERO:
                    if inv.imbalance > ZERO:
                        vwap = inv.up_vwap or Decimal("0.50")
                    else:
                        vwap = inv.down_vwap or Decimal("0.50")
                    at_risk = (abs_imbalance * vwap).quantize(Decimal("0.01"))
                else:
                    at_risk = Decimal("0.00")
                completed_str = " [DONE]" if market.slug in self._completed_markets else ""
                log.info(
                    "  POSITION %s │ U%s/D%s (h%s) │ cost=$%s │ at_risk=$%s%s",
                    market.slug[-40:],
                    inv.up_shares, inv.down_shares, hedged,
                    cost, at_risk, completed_str,
                )

                # UNREALIZED line for hedged positions
                if hedged > ZERO and inv.up_vwap is not None and inv.down_vwap is not None:
                    h_value = (hedged * ONE).quantize(Decimal("0.01"))
                    h_cost = (hedged * (inv.up_vwap + inv.down_vwap)).quantize(Decimal("0.01"))
                    h_pnl = (hedged * ONE - hedged * (inv.up_vwap + inv.down_vwap)).quantize(Decimal("0.01"))
                    h_pct = (h_pnl / h_cost * 100).quantize(Decimal("0.1")) if h_cost > ZERO else ZERO
                    color = C_GREEN if h_pnl >= ZERO else C_RED
                    log.info(
                        "  %sUNREALIZED %s │ value=$%s │ cost=$%s │ pnl=$%s (%s%%)%s",
                        color, market.slug[-40:],
                        h_value, h_cost, h_pnl, h_pct, C_RESET,
                    )

            # MARKET line: book state + edge (always shown)
            up_book = get_top_of_book(self._client, market.up_token_id)
            down_book = get_top_of_book(self._client, market.down_token_id)

            up_bid = up_book.best_bid if up_book else None
            up_ask = up_book.best_ask if up_book else None
            dn_bid = down_book.best_bid if down_book else None
            dn_ask = down_book.best_ask if down_book else None

            edge_str = "?"
            if up_ask and dn_ask:
                edge = ONE - (up_ask + dn_ask)
                edge_str = f"{edge:.3f}"

            log.debug(
                "  MARKET %s │ %ds │ book=U[%s/%s] D[%s/%s] │ ask_edge=%s",
                market.slug[-30:], ste,
                up_bid, up_ask, dn_bid, dn_ask, edge_str,
            )

    def _evaluate_market(self, market: GabagoolMarket, now: float) -> None:
        """Two-phase hedge: buy cheap leg first, then hedge the other when profitable."""
        slug = market.slug

        # Already hedged this window — skip
        if slug in self._completed_markets:
            return

        seconds_to_end = int(market.end_time - now)
        max_lifetime = 900 if market.market_type == "updown-15m" else 3600

        # Pre-resolution buffer: cancel pending orders and sell unhedged legs
        if 0 <= seconds_to_end < self._cfg.no_new_orders_sec:
            self._order_mgr.cancel_market_orders(self._client, market, "PRE_RESOLUTION_BUFFER", self._handle_fill)

            # Sell unhedged single legs at bid (FOK) to recover capital
            inv = self._inventory.get_inventory(slug)
            if inv.up_shares > ZERO and inv.down_shares == ZERO:
                up_book = get_top_of_book(self._client, market.up_token_id)
                if up_book and up_book.best_bid and up_book.best_bid > ZERO:
                    if not self._order_mgr.has_order(market.up_token_id):
                        log.info(
                            "%sCLEANUP_SELL %s │ UP %s shares @ bid %s │ %ds left%s",
                            C_YELLOW, slug, inv.up_shares, up_book.best_bid,
                            seconds_to_end, C_RESET,
                        )
                        self._order_mgr.place_order(
                            self._client, market, market.up_token_id, Direction.UP,
                            up_book.best_bid, inv.up_shares, seconds_to_end,
                            "CLEANUP_SELL", on_fill=self._handle_fill,
                            order_type=OrderType.FOK, side="SELL",
                        )
            elif inv.down_shares > ZERO and inv.up_shares == ZERO:
                down_book = get_top_of_book(self._client, market.down_token_id)
                if down_book and down_book.best_bid and down_book.best_bid > ZERO:
                    if not self._order_mgr.has_order(market.down_token_id):
                        log.info(
                            "%sCLEANUP_SELL %s │ DOWN %s shares @ bid %s │ %ds left%s",
                            C_YELLOW, slug, inv.down_shares, down_book.best_bid,
                            seconds_to_end, C_RESET,
                        )
                        self._order_mgr.place_order(
                            self._client, market, market.down_token_id, Direction.DOWN,
                            down_book.best_bid, inv.down_shares, seconds_to_end,
                            "CLEANUP_SELL", on_fill=self._handle_fill,
                            order_type=OrderType.FOK, side="SELL",
                        )
            return

        # Outside lifetime
        if seconds_to_end < 0 or seconds_to_end > max_lifetime:
            return

        # Outside configured time window
        min_ste = max(0, self._cfg.min_seconds_to_end)
        max_ste = min(max_lifetime, max(min_ste, self._cfg.max_seconds_to_end))
        if seconds_to_end < min_ste or seconds_to_end > max_ste:
            return

        # Fetch TOB for both legs
        up_book = get_top_of_book(self._client, market.up_token_id)
        down_book = get_top_of_book(self._client, market.down_token_id)

        if not up_book or not down_book:
            return
        if up_book.best_ask is None or down_book.best_ask is None:
            return

        up_ask = up_book.best_ask
        down_ask = down_book.best_ask

        # Dynamic edge based on worst spread
        worst_spread = max(
            (up_book.best_ask - up_book.best_bid) if up_book.best_bid is not None else Decimal("0.10"),
            (down_book.best_ask - down_book.best_bid) if down_book.best_bid is not None else Decimal("0.10"),
        )
        dynamic_edge = calculate_dynamic_edge(worst_spread, self._cfg.min_edge)

        # Current inventory state
        inv = self._inventory.get_inventory(slug)
        has_up = inv.filled_up_shares >= self._cfg.min_merge_shares
        has_down = inv.filled_down_shares >= self._cfg.min_merge_shares

        exposure = calculate_exposure(
            self._order_mgr.get_open_orders(),
            self._inventory.get_all_inventories(),
        )

        # ── Phase 1: No position — buy cheapest leg if ask < (1 - edge) / 2 ──
        if not has_up and not has_down:
            max_first_leg = (ONE - dynamic_edge) / 2

            # Determine which side to buy
            buy_up = up_ask <= max_first_leg
            buy_down = down_ask <= max_first_leg

            if not buy_up and not buy_down:
                log.debug(
                    "FIRST_LEG_SKIP %s │ U_ask=%s D_ask=%s > max_first=%.3f",
                    slug, up_ask, down_ask, max_first_leg,
                )
                return

            # Pick the cheaper side (if both qualify)
            if buy_up and (up_ask <= down_ask or not buy_down):
                target_ask = up_ask
                target_dir = Direction.UP
                target_token = market.up_token_id
                side_label = "UP"
            else:
                target_ask = down_ask
                target_dir = Direction.DOWN
                target_token = market.down_token_id
                side_label = "DOWN"

            # Size using balanced calculation (both asks) for bankroll-appropriate size
            shares = calculate_balanced_shares(
                slug, up_ask, down_ask, self._cfg, seconds_to_end, exposure,
            )
            if shares is None:
                log.debug("FIRST_LEG_SKIP %s │ insufficient bankroll", slug)
                return

            # Skip if we already have a pending order for this token
            if self._order_mgr.has_order(target_token):
                log.debug("FIRST_LEG_SKIP %s │ pending order for %s", slug, side_label)
                return

            log.info(
                "%sFIRST_LEG %s │ %s ask=%s │ max_first=%.3f │ shares=%s │ %ds left%s",
                C_GREEN, slug, side_label, target_ask, max_first_leg,
                shares, seconds_to_end, C_RESET,
            )

            self._order_mgr.place_order(
                self._client, market, target_token, target_dir,
                target_ask, shares, seconds_to_end, "FIRST_LEG",
                on_fill=self._handle_fill,
                order_type=OrderType.FOK,
            )
            return

        # ── Phase 2: One leg filled — hedge the other if edge is sufficient ──
        if has_up and not has_down:
            # Need: up_vwap + down_ask < 1.0 - dynamic_edge
            if inv.up_vwap is None:
                return
            combined = inv.up_vwap + down_ask
            edge = ONE - combined
            if edge < dynamic_edge:
                log.debug(
                    "HEDGE_SKIP %s │ UP_vwap=%s + D_ask=%s = %.3f │ edge=%.3f < %.3f",
                    slug, inv.up_vwap, down_ask, combined, edge, dynamic_edge,
                )
                return

            # Match first leg's filled share count; check bankroll
            hedge_shares = inv.filled_up_shares
            hedge_notional = hedge_shares * down_ask
            bankroll = self._cfg.bankroll_usd
            if bankroll > ZERO and self._cfg.max_total_bankroll_fraction > ZERO:
                total_cap = bankroll * self._cfg.max_total_bankroll_fraction
                remaining = total_cap - exposure
                if hedge_notional > remaining:
                    log.debug("HEDGE_SKIP %s │ bankroll exhausted (need $%s, remaining $%s)",
                              slug, hedge_notional.quantize(Decimal("0.01")), remaining.quantize(Decimal("0.01")))
                    return

            if self._order_mgr.has_order(market.down_token_id):
                log.debug("HEDGE_SKIP %s │ pending order for DOWN", slug)
                return

            log.info(
                "%sHEDGE_LEG %s │ DOWN ask=%s │ UP_vwap=%s │ edge=%.3f │ shares=%s │ %ds left%s",
                C_GREEN, slug, down_ask, inv.up_vwap, edge,
                hedge_shares, seconds_to_end, C_RESET,
            )

            self._order_mgr.place_order(
                self._client, market, market.down_token_id, Direction.DOWN,
                down_ask, hedge_shares, seconds_to_end, "HEDGE_LEG",
                on_fill=self._handle_fill,
                order_type=OrderType.FOK,
            )
            return

        if has_down and not has_up:
            # Need: down_vwap + up_ask < 1.0 - dynamic_edge
            if inv.down_vwap is None:
                return
            combined = inv.down_vwap + up_ask
            edge = ONE - combined
            if edge < dynamic_edge:
                log.debug(
                    "HEDGE_SKIP %s │ D_vwap=%s + U_ask=%s = %.3f │ edge=%.3f < %.3f",
                    slug, inv.down_vwap, up_ask, combined, edge, dynamic_edge,
                )
                return

            hedge_shares = inv.filled_down_shares
            hedge_notional = hedge_shares * up_ask
            bankroll = self._cfg.bankroll_usd
            if bankroll > ZERO and self._cfg.max_total_bankroll_fraction > ZERO:
                total_cap = bankroll * self._cfg.max_total_bankroll_fraction
                remaining = total_cap - exposure
                if hedge_notional > remaining:
                    log.debug("HEDGE_SKIP %s │ bankroll exhausted (need $%s, remaining $%s)",
                              slug, hedge_notional.quantize(Decimal("0.01")), remaining.quantize(Decimal("0.01")))
                    return

            if self._order_mgr.has_order(market.up_token_id):
                log.debug("HEDGE_SKIP %s │ pending order for UP", slug)
                return

            log.info(
                "%sHEDGE_LEG %s │ UP ask=%s │ DOWN_vwap=%s │ edge=%.3f │ shares=%s │ %ds left%s",
                C_GREEN, slug, up_ask, inv.down_vwap, edge,
                hedge_shares, seconds_to_end, C_RESET,
            )

            self._order_mgr.place_order(
                self._client, market, market.up_token_id, Direction.UP,
                up_ask, hedge_shares, seconds_to_end, "HEDGE_LEG",
                on_fill=self._handle_fill,
                order_type=OrderType.FOK,
            )
