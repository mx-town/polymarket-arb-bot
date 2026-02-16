"""Rebate-maker tick loop — post grids on both sides, collect maker fills, merge.

Per-window lifecycle:
1. Post grid of GTC BUY orders on both UP and DOWN sides
2. Maintain grid: reprice levels tracking the book
3. Merge hedged pairs when min_merge_shares reached
4. Buffer: stop new orders when seconds_to_end < no_new_orders_sec
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal

from py_clob_client.clob_types import OrderType

from shared.events import EventType, emit
from shared.market_data import discover_markets, get_top_of_book, prefetch_order_books
from shared.order_mgr import OrderManager
from shared.redeem import (
    CTF_DECIMALS,
    TxResult,
    get_ctf_balances,
    get_usdc_balance,
    merge_positions,
    redeem_positions,
)

from rebate_maker.config import RebateMakerConfig
from rebate_maker.models import (
    C_BOLD,
    C_DIM,
    C_GREEN,
    C_RED,
    C_RESET,
    C_YELLOW,
    ONE,
    ZERO,
    Direction,
    GabagoolMarket,
    PendingRedemption,
)
from rebate_maker.quote_calc import (
    calculate_exposure,
    calculate_exposure_breakdown,
    calculate_grid_sizes,
    total_bankroll_cap,
)

log = logging.getLogger("rm.engine")

TICK_SIZE = Decimal("0.01")


class Engine:
    def __init__(
        self, client, cfg: RebateMakerConfig,
        w3=None, account=None, rpc_url: str = "", funder_address: str = "",
    ):
        self._client = client
        self._cfg = cfg
        self._w3 = w3
        self._account = account
        self._rpc_url = rpc_url
        self._funder_address = funder_address
        self._order_mgr = OrderManager(dry_run=cfg.dry_run)
        from rebate_maker.inventory import InventoryTracker
        self._inventory = InventoryTracker(dry_run=cfg.dry_run)
        self._active_markets: list[GabagoolMarket] = []
        self._last_discovery: float = 0.0
        self._prev_quotable_slugs: set[str] = set()
        self._completed_markets: set[str] = set()
        self._pending_redemptions: dict[str, PendingRedemption] = {}
        self._merge_failures: dict[str, int] = {}
        self._merge_last_attempt: dict[str, float] = {}
        self._pending_merge_task: dict[str, asyncio.Task] = {}
        self._pending_redeem_task: dict[str, asyncio.Task] = {}
        self._start_time: float = time.time()
        self._last_session_log: float = 0.0
        self._bg_discovery: asyncio.Task | None = None
        self._bg_refresh: asyncio.Task | None = None
        self._cached_wallet_bal: str = "n/a"
        self._last_summary_log: float = 0.0
        self._last_wallet_refresh: float = 0.0
        self._tick_count: int = 0
        self._tick_total_ms: float = 0.0
        self._tick_max_ms: float = 0.0
        self._last_reconcile: float = 0.0
        self._market_exit_data: dict[str, dict] = {}

    async def run(self) -> None:
        """Main event loop."""
        mode = "DRY RUN" if self._cfg.dry_run else "LIVE"
        log.info("=" * 56)
        log.info("  Rebate-Maker Engine v1.0.0  [%s]", mode)
        log.info("=" * 56)
        log.info("  Assets          : %s", ", ".join(self._cfg.assets))
        log.info("  Tick interval   : %dms", self._cfg.refresh_millis)
        log.info("  Min edge        : %s", self._cfg.min_edge)
        log.info("  Bankroll        : $%s", self._cfg.bankroll_usd)
        log.info("  Time window     : %d-%ds", self._cfg.min_seconds_to_end, self._cfg.max_seconds_to_end)
        log.info("  No new orders   : %ds", self._cfg.no_new_orders_sec)
        log.info("  Grid levels     : %d (step=%s)", self._cfg.grid_levels, self._cfg.grid_step)
        log.info("  Min merge shares: %s", self._cfg.min_merge_shares)
        log.info("  Post-merge lock : %s", "ON" if self._cfg.post_merge_lockout else "OFF")
        log.info("  Entry prices    : %s-%s", self._cfg.min_entry_price, self._cfg.max_entry_price)
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

        # Initial position sync
        self._active_markets = discover_markets(self._cfg.assets)
        self._last_discovery = time.time()
        self._inventory.refresh_if_stale(self._client, self._active_markets)
        self._inventory.sync_inventory(self._active_markets, get_mid_price=self._get_mid_price)

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
        tick_start = time.monotonic()
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

        # -- Sync + evaluate in thread pool --
        await asyncio.to_thread(self._tick_core, now)

        # -- Settlements --
        self._check_settlements(now)

        # -- Tick timing --
        tick_ms = (time.monotonic() - tick_start) * 1000
        self._tick_count += 1
        self._tick_total_ms += tick_ms
        if tick_ms > self._tick_max_ms:
            self._tick_max_ms = tick_ms
        budget_ms = self._cfg.refresh_millis
        if tick_ms > budget_ms * 0.8:
            log.warning(
                "TICK_SLOW %.0fms (budget=%dms, %.0f%%)",
                tick_ms, budget_ms, tick_ms / budget_ms * 100,
            )

    def _tick_core(self, now: float) -> None:
        """Synchronous evaluate phase - runs in thread pool."""
        prefetch_order_books(self._client, self._active_markets)

        self._inventory.sync_inventory(
            self._active_markets, get_mid_price=self._get_mid_price,
        )

        self._order_mgr.check_pending_orders(self._client, self._handle_fill)

        for market in self._active_markets:
            try:
                self._evaluate_market(market, now)
            except Exception as e:
                log.error("%sError evaluating %s: %s%s", C_RED, market.slug, e, C_RESET)

        # Periodic order reconciliation
        if not self._cfg.dry_run and now - self._last_reconcile >= 30.0:
            self._last_reconcile = now
            self._order_mgr.reconcile_orders(self._client)

        # Periodic summary
        if now - self._last_summary_log >= 30:
            self._last_summary_log = now
            self._log_summary(now)

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
                final_up_bid = final_dn_bid = None
                if market:
                    up_book = get_top_of_book(self._client, market.up_token_id)
                    dn_book = get_top_of_book(self._client, market.down_token_id)
                    final_up_bid = up_book.best_bid if up_book else None
                    final_dn_bid = dn_book.best_bid if dn_book else None
                exit_data = self._inventory.clear_market(slug, up_bid=final_up_bid, down_bid=final_dn_bid)
                if exit_data is not None:
                    self._market_exit_data[slug] = exit_data

        for token_id in list(self._order_mgr.get_open_orders()):
            order = self._order_mgr.get_order(token_id)
            if order and order.market and order.market.slug not in active_slugs:
                self._order_mgr.cancel_order(self._client, token_id, "MARKET_EXPIRED", self._handle_fill)
        self._log_market_transitions(now)

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
        emit(EventType.ORDER_FILLED, {
            "direction": state.direction.value,
            "side": state.side,
            "price": float(state.price),
            "shares": float(filled_shares),
            "order_id": state.order_id,
            "strategy": "rebate_maker",
        }, market_slug=state.market.slug)

        log.info(
            "%sFILL %s %s +%s shares @ %s%s",
            C_GREEN,
            state.market.slug,
            state.direction.value,
            filled_shares,
            state.price,
            C_RESET,
        )
        # Check if hedge is complete
        inv = self._inventory.get_inventory(state.market.slug)
        hedged = min(inv.up_shares, inv.down_shares)
        remaining_imbalance = abs(inv.imbalance)
        if hedged >= self._cfg.min_merge_shares:
            if remaining_imbalance < self._cfg.min_merge_shares:
                self._completed_markets.add(state.market.slug)
                edge = ONE - (inv.up_vwap + inv.down_vwap) if inv.up_vwap and inv.down_vwap else ZERO
                log.info(
                    "%sHEDGE_COMPLETE %s │ hedged=%s │ edge=%s%s",
                    C_GREEN, state.market.slug, hedged, edge, C_RESET,
                )
                emit(EventType.HEDGE_COMPLETE, {
                    "hedged_shares": float(hedged),
                    "edge": float(edge),
                    "direction": state.direction.value,
                    "strategy": "rebate_maker",
                }, market_slug=state.market.slug)
                self._order_mgr.cancel_market_orders(
                    self._client, state.market, "HEDGE_COMPLETE_CLEANUP", self._handle_fill,
                )
                log.info("HEDGE_COMPLETE_CLEANUP %s │ cancelled remaining orders", state.market.slug)
            else:
                edge = ONE - (inv.up_vwap + inv.down_vwap) if inv.up_vwap and inv.down_vwap else ZERO
                log.info(
                    "%sHEDGE_PARTIAL %s │ hedged=%s │ remaining=%s │ edge=%s%s",
                    C_YELLOW, state.market.slug, hedged, remaining_imbalance, edge, C_RESET,
                )

    def _find_merge_candidate(self, now: float) -> tuple[GabagoolMarket, Decimal] | None:
        """Find the first market eligible for merge."""
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
            if now - last_attempt < self._cfg.merge_cooldown_sec:
                continue
            seconds_to_end = int(market.end_time - now)
            if seconds_to_end < self._cfg.no_new_orders_sec:
                continue

            gross = hedged * (ONE - (inv.up_vwap or ZERO) - (inv.down_vwap or ZERO))
            if gross < self._cfg.min_merge_profit_usd:
                log.info(
                    "MERGE_SKIP_PROFIT %s │ gross=$%s < min=$%s",
                    slug, gross.quantize(Decimal("0.0001")), self._cfg.min_merge_profit_usd,
                )
                continue

            return market, hedged
        return None

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
                        continue
                    tx_hash, merged_display, gas_cost_wei = result
                    self._inventory.reduce_merged(slug, merged_display)
                    self._merge_failures.pop(slug, None)
                    if not self._cfg.post_merge_lockout:
                        self._completed_markets.discard(slug)
                    gas_matic = Decimal(gas_cost_wei) / Decimal(10**18)
                    gas_usd = gas_matic * self._cfg.matic_price_usd
                    self._inventory.session_realized_pnl -= gas_usd
                    self._inventory.session_gas_spent += gas_usd
                    log.info(
                        "%sMERGE_POSITION %s │ merged=%s shares │ gas=$%s │ tx=%s%s",
                        C_GREEN, slug, merged_display,
                        gas_usd.quantize(Decimal("0.0001")), tx_hash, C_RESET,
                    )
                    emit(EventType.MERGE_COMPLETE, {
                        "merged_shares": float(merged_display),
                        "tx_hash": tx_hash,
                        "gas_cost_usd": float(gas_usd),
                        "strategy": "rebate_maker",
                    }, market_slug=slug)
                except Exception as e:
                    failures = self._merge_failures.get(slug, 0) + 1
                    self._merge_failures[slug] = failures
                    log.warning(
                        "%sMERGE_FAILED %s │ attempt %d/5 │ %s%s",
                        C_YELLOW, slug, failures, e, C_RESET,
                    )

            # Phase B — Launch new merge (one per tick, non-blocking)
            candidate = self._find_merge_candidate(now)
            if candidate is not None:
                market, hedged = candidate
                self._merge_last_attempt[market.slug] = now
                min_base = int(self._cfg.min_merge_shares * (10 ** CTF_DECIMALS))
                task = asyncio.ensure_future(asyncio.to_thread(
                    self._do_merge_io, market.slug, market, min_base,
                ))
                self._pending_merge_task[market.slug] = task
                log.info("MERGE_LAUNCHED %s", market.slug)

        elif self._cfg.dry_run:
            candidate = self._find_merge_candidate(now)
            if candidate is not None:
                market, hedged = candidate
                self._merge_last_attempt[market.slug] = now
                self._inventory.reduce_merged(market.slug, hedged)
                gas_cost = self._cfg.dry_merge_gas_cost_usd
                self._inventory.session_realized_pnl -= gas_cost
                if not self._cfg.post_merge_lockout:
                    self._completed_markets.discard(market.slug)
                log.info(
                    "DRY_MERGE %s │ merged=%s shares → freed $%s │ gas=-$%s",
                    market.slug, hedged, hedged, gas_cost,
                )
                emit(EventType.MERGE_COMPLETE, {
                    "merged_shares": float(hedged),
                    "tx_hash": "dry_run",
                    "strategy": "rebate_maker",
                }, market_slug=market.slug)
                self._order_mgr.cancel_market_orders(
                    self._client, market, "HEDGE_COMPLETE_CLEANUP", self._handle_fill,
                )

        # ── Redeem resolved positions ──
        # Phase A — Harvest completed redeem tasks
        for slug in list(self._pending_redeem_task):
            task = self._pending_redeem_task[slug]
            if not task.done():
                continue
            del self._pending_redeem_task[slug]
            try:
                redeem_result: TxResult = task.result()
                gas_matic = Decimal(redeem_result.gas_cost_wei) / Decimal(10**18)
                gas_usd = gas_matic * self._cfg.matic_price_usd
                self._inventory.session_realized_pnl -= gas_usd
                self._inventory.session_gas_spent += gas_usd
                log.info(
                    "%sREDEEMED %s │ gas=$%s │ tx=%s%s",
                    C_GREEN, slug, gas_usd.quantize(Decimal("0.0001")),
                    redeem_result.tx_hash, C_RESET,
                )
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
                max_gas_price_gwei=self._cfg.max_gas_price_gwei,
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
    ) -> tuple[str, Decimal, int] | None:
        """Run balance check + merge in thread pool."""
        actual_up, actual_down = get_ctf_balances(
            self._rpc_url, self._funder_address,
            market.up_token_id, market.down_token_id,
        )
        amount_base = min(actual_up, actual_down)
        if amount_base < min_base:
            log.debug("MERGE_SKIP %s │ on-chain balance too low (up=%d, down=%d)", slug, actual_up, actual_down)
            return None
        merged_display = Decimal(amount_base) / Decimal(10 ** CTF_DECIMALS)
        result = merge_positions(
            self._w3, self._account, self._funder_address,
            market.condition_id, amount_base, neg_risk=market.neg_risk,
            max_gas_price_gwei=self._cfg.max_gas_price_gwei,
        )
        return (result.tx_hash, merged_display, result.gas_cost_wei)

    def _refresh_wallet_balance(self) -> None:
        """Refresh wallet balance synchronously."""
        try:
            bal = get_usdc_balance(self._rpc_url, self._funder_address)
            self._cached_wallet_bal = f"${bal.quantize(Decimal('0.01'))}"
        except Exception:
            self._cached_wallet_bal = "err"

    def _get_mid_price(self, token_id: str) -> Decimal | None:
        """Return mid-market price for a token."""
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

        market_by_slug = {m.slug: m for m in self._active_markets}
        for slug in sorted(entered):
            log.info("%sENTER window │ %s%s", C_GREEN, slug, C_RESET)
            m = market_by_slug.get(slug)
            if m:
                emit(EventType.MARKET_ENTERED, {
                    "market_type": m.market_type,
                    "end_time": m.end_time,
                    "up_token_id": m.up_token_id,
                    "down_token_id": m.down_token_id,
                    "strategy": "rebate_maker",
                }, market_slug=slug)
        for slug in sorted(exited):
            log.info("%sEXIT  window │ %s%s", C_YELLOW, slug, C_RESET)
            exit_data = self._market_exit_data.pop(slug, {})
            emit(EventType.MARKET_EXITED, {
                "strategy": "rebate_maker",
                "outcome": exit_data.get("outcome"),
                "total_pnl": exit_data.get("total_pnl"),
            }, market_slug=slug)

        self._prev_quotable_slugs = quotable_now

    def _log_summary(self, now: float) -> None:
        """Periodic summary: P&L dashboard with inventory, exposure, entry prices vs book."""
        open_orders = self._order_mgr.get_open_orders()
        all_inv = self._inventory.get_all_inventories()
        exposure = calculate_exposure(open_orders, all_inv)
        ord_notional, unhedged_exp, hedged_locked, _ = calculate_exposure_breakdown(
            open_orders, all_inv,
        )
        open_count = len(open_orders)

        bankroll = self._cfg.bankroll_usd
        total_cap = total_bankroll_cap(bankroll) if bankroll > ZERO else bankroll
        remaining = max(ZERO, total_cap - exposure) if total_cap > ZERO else ZERO
        pct_used = (exposure / bankroll * 100).quantize(Decimal("0.1")) if bankroll > ZERO else ZERO

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

        # Wallet balance
        wallet_str = self._cached_wallet_bal
        if self._rpc_url and self._funder_address and now - self._last_wallet_refresh >= 60:
            self._last_wallet_refresh = now
            self._refresh_wallet_balance()

        # Session banner (every 300s)
        session_str = ""
        if now - self._last_session_log >= 300:
            self._last_session_log = now
            runtime_s = int(now - self._start_time)
            if runtime_s >= 3600:
                runtime_str = f"{runtime_s // 3600}h {(runtime_s % 3600) // 60}m"
            else:
                runtime_str = f"{runtime_s // 60}m"
            roi = (total_pnl / bankroll * 100).quantize(Decimal("0.01")) if bankroll > ZERO else ZERO
            session_str = f"  runtime={runtime_str}  ROI={roi}%"

        emit(EventType.PNL_SNAPSHOT, {
            "realized": float(realized),
            "unrealized": float(unrealized),
            "total": float(total_pnl),
            "exposure": float(exposure),
            "exposure_pct": float(pct_used),
            "gas_spent": float(self._inventory.session_gas_spent),
        })

        # Box top
        log.info("%s┌─ SUMMARY ─────────────────────────────────────────%s%s", C_BOLD, session_str, C_RESET)

        tick_str = ""
        if self._tick_count > 0:
            avg_ms = self._tick_total_ms / self._tick_count
            tick_str = f"  ticks={self._tick_count} (avg {avg_ms:.0f}ms)"
        log.info(
            "│ markets=%d  orders=%d  completed=%d%s",
            len(self._active_markets), open_count, len(self._completed_markets),
            tick_str,
        )

        log.info(
            "│ %sPnL: realized=$%s  unrealized=$%s  total=$%s%s",
            pnl_color, realized, unrealized, total_pnl, C_RESET,
        )

        log.info(
            "│ bankroll=$%s (%s%% used)  wallet=%s  remaining=$%s",
            bankroll, pct_used, wallet_str, remaining.quantize(Decimal("0.01")),
        )

        if exposure > ZERO:
            log.info(
                "│ exposure: orders=$%s  unhedged=$%s  hedged=$%s  total=$%s",
                ord_notional.quantize(Decimal("0.01")),
                unhedged_exp.quantize(Decimal("0.01")),
                hedged_locked.quantize(Decimal("0.01")),
                exposure.quantize(Decimal("0.01")),
            )

        for market in self._active_markets:
            ste = int(market.end_time - now)
            inv = self._inventory.get_inventory(market.slug)
            hedged = min(inv.up_shares, inv.down_shares)

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
                    "│ POSITION %s │ U%s/D%s (h%s) │ cost=$%s │ at_risk=$%s%s",
                    market.slug[-40:],
                    inv.up_shares, inv.down_shares, hedged,
                    cost, at_risk, completed_str,
                )

                if hedged > ZERO and inv.up_vwap is not None and inv.down_vwap is not None:
                    h_value = (hedged * ONE).quantize(Decimal("0.01"))
                    h_cost = (hedged * (inv.up_vwap + inv.down_vwap)).quantize(Decimal("0.01"))
                    h_pnl = (hedged * ONE - hedged * (inv.up_vwap + inv.down_vwap)).quantize(Decimal("0.01"))
                    h_pct = (h_pnl / h_cost * 100).quantize(Decimal("0.1")) if h_cost > ZERO else ZERO
                    color = C_GREEN if h_pnl >= ZERO else C_RED
                    log.info(
                        "│ %sUNREALIZED %s │ value=$%s │ cost=$%s │ pnl=$%s (%s%%)%s",
                        color, market.slug[-40:],
                        h_value, h_cost, h_pnl, h_pct, C_RESET,
                    )

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
                "│ MARKET %s │ %ds │ U[%s/%s] D[%s/%s] │ edge=%s",
                market.slug[-30:], ste,
                up_bid, up_ask, dn_bid, dn_ask, edge_str,
            )

        log.info("└───────────────────────────────────────────────────")

    def _place_grid(self, market: GabagoolMarket, now: float) -> None:
        """Post grid of GTC BUY orders on both sides."""
        slug = market.slug
        seconds_to_end = int(market.end_time - now)

        up_book = get_top_of_book(self._client, market.up_token_id)
        down_book = get_top_of_book(self._client, market.down_token_id)

        if not up_book or not down_book:
            return
        if up_book.best_bid is None or up_book.best_ask is None:
            return
        if down_book.best_bid is None or down_book.best_ask is None:
            return

        up_bid = up_book.best_bid
        up_ask = up_book.best_ask
        down_bid = down_book.best_bid
        down_ask = down_book.best_ask

        num_active = len([m for m in self._active_markets
                         if int(m.end_time - now) > self._cfg.no_new_orders_sec])

        n_up_posted = 0
        n_down_posted = 0

        # Post UP grid
        up_prices = []
        for i in range(1, self._cfg.grid_levels + 1):
            price = up_bid + (TICK_SIZE * i * self._cfg.grid_step / Decimal("0.01"))
            if price >= up_ask:
                break
            if price > self._cfg.max_entry_price:
                break
            if price < self._cfg.min_entry_price:
                continue
            up_prices.append(price)

        grid_sizes_up = calculate_grid_sizes(
            self._cfg.bankroll_usd, num_active, self._cfg.grid_levels, up_prices
        )

        for price, size in grid_sizes_up:
            self._order_mgr.place_order(
                self._client, market, market.up_token_id, Direction.UP,
                price, size, seconds_to_end, "GRID_UP",
                on_fill=self._handle_fill, order_type=OrderType.GTC,
            )
            n_up_posted += 1

        # Post DOWN grid
        down_prices = []
        for i in range(1, self._cfg.grid_levels + 1):
            price = down_bid + (TICK_SIZE * i * self._cfg.grid_step / Decimal("0.01"))
            if price >= down_ask:
                break
            if price > self._cfg.max_entry_price:
                break
            if price < self._cfg.min_entry_price:
                continue
            down_prices.append(price)

        grid_sizes_down = calculate_grid_sizes(
            self._cfg.bankroll_usd, num_active, self._cfg.grid_levels, down_prices
        )

        for price, size in grid_sizes_down:
            self._order_mgr.place_order(
                self._client, market, market.down_token_id, Direction.DOWN,
                price, size, seconds_to_end, "GRID_DOWN",
                on_fill=self._handle_fill, order_type=OrderType.GTC,
            )
            n_down_posted += 1

        if n_up_posted > 0 or n_down_posted > 0:
            log.info(
                "%sGRID_POST %s │ %dup + %ddown levels%s",
                C_GREEN, slug, n_up_posted, n_down_posted, C_RESET,
            )

    def _maintain_grid(self, market: GabagoolMarket, now: float) -> None:
        """Reprice grid levels tracking the book."""
        slug = market.slug
        seconds_to_end = int(market.end_time - now)

        up_book = get_top_of_book(self._client, market.up_token_id)
        down_book = get_top_of_book(self._client, market.down_token_id)

        if not up_book or not down_book:
            return
        if up_book.best_bid is None or up_book.best_ask is None:
            return
        if down_book.best_bid is None or down_book.best_ask is None:
            return

        up_bid = up_book.best_bid
        up_ask = up_book.best_ask
        down_bid = down_book.best_bid
        down_ask = down_book.best_ask

        num_active = len([m for m in self._active_markets
                         if int(m.end_time - now) > self._cfg.no_new_orders_sec])

        # Compute desired UP prices
        desired_up_prices = set()
        for i in range(1, self._cfg.grid_levels + 1):
            price = up_bid + (TICK_SIZE * i * self._cfg.grid_step / Decimal("0.01"))
            if price >= up_ask:
                break
            if price > self._cfg.max_entry_price:
                break
            if price < self._cfg.min_entry_price:
                continue
            desired_up_prices.add(price)

        existing_up_orders = self._order_mgr.get_all_orders_for_token(market.up_token_id)
        existing_up_prices = {order.price for order in existing_up_orders}

        stale_up_prices = existing_up_prices - desired_up_prices
        if stale_up_prices:
            self._order_mgr.cancel_all_for_token(
                self._client, market.up_token_id, "GRID_REPRICE", self._handle_fill
            )
            existing_up_prices.clear()

        new_up_prices = [p for p in desired_up_prices if p not in existing_up_prices]
        if new_up_prices:
            grid_sizes_up = calculate_grid_sizes(
                self._cfg.bankroll_usd, num_active, self._cfg.grid_levels, new_up_prices
            )
            for price, size in grid_sizes_up:
                self._order_mgr.place_order(
                    self._client, market, market.up_token_id, Direction.UP,
                    price, size, seconds_to_end, "GRID_UP",
                    on_fill=self._handle_fill, order_type=OrderType.GTC,
                )

        # Compute desired DOWN prices
        desired_down_prices = set()
        for i in range(1, self._cfg.grid_levels + 1):
            price = down_bid + (TICK_SIZE * i * self._cfg.grid_step / Decimal("0.01"))
            if price >= down_ask:
                break
            if price > self._cfg.max_entry_price:
                break
            if price < self._cfg.min_entry_price:
                continue
            desired_down_prices.add(price)

        existing_down_orders = self._order_mgr.get_all_orders_for_token(market.down_token_id)
        existing_down_prices = {order.price for order in existing_down_orders}

        stale_down_prices = existing_down_prices - desired_down_prices
        if stale_down_prices:
            self._order_mgr.cancel_all_for_token(
                self._client, market.down_token_id, "GRID_REPRICE", self._handle_fill
            )
            existing_down_prices.clear()

        new_down_prices = [p for p in desired_down_prices if p not in existing_down_prices]
        if new_down_prices:
            grid_sizes_down = calculate_grid_sizes(
                self._cfg.bankroll_usd, num_active, self._cfg.grid_levels, new_down_prices
            )
            for price, size in grid_sizes_down:
                self._order_mgr.place_order(
                    self._client, market, market.down_token_id, Direction.DOWN,
                    price, size, seconds_to_end, "GRID_DOWN",
                    on_fill=self._handle_fill, order_type=OrderType.GTC,
                )

    def _evaluate_market(self, market: GabagoolMarket, now: float) -> None:
        """Post grid, maintain it, merge when ready."""
        slug = market.slug

        if slug in self._completed_markets:
            return

        seconds_to_end = int(market.end_time - now)
        max_lifetime = 900 if market.market_type == "updown-15m" else 3600

        # Pre-resolution buffer
        if 0 <= seconds_to_end < self._cfg.no_new_orders_sec:
            self._order_mgr.cancel_market_orders(self._client, market, "PRE_RESOLUTION_BUFFER", self._handle_fill)
            inv = self._inventory.get_inventory(slug)
            if inv.up_shares > ZERO or inv.down_shares > ZERO:
                log.info(
                    "BUFFER_HOLD %s │ U%s/D%s │ letting position resolve at settlement │ %ds left",
                    slug, inv.up_shares, inv.down_shares, seconds_to_end,
                )
            return

        if seconds_to_end < 0 or seconds_to_end > max_lifetime:
            return

        min_ste = max(0, self._cfg.min_seconds_to_end)
        max_ste = min(max_lifetime, max(min_ste, self._cfg.max_seconds_to_end))
        if seconds_to_end < min_ste or seconds_to_end > max_ste:
            return

        # Grid mode: post or maintain
        inv = self._inventory.get_inventory(slug)
        has_any_orders = (
            self._order_mgr.has_order(market.up_token_id) or
            self._order_mgr.has_order(market.down_token_id)
        )
        if not has_any_orders and inv.up_shares == ZERO and inv.down_shares == ZERO:
            self._place_grid(market, now)
        else:
            self._maintain_grid(market, now)
