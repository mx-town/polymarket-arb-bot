"""Strategy tick loop — two-phase asymmetric hedge for complete-set arbitrage.

Per-window lifecycle:
1. No position: buy cheapest leg at bid+0.01 (GTC maker, 0% fee)
2. One leg filled: hedge the other at bid+0.01 if first_vwap + maker_price < 1 - min_edge (GTC maker)
3. Both legs filled (hedged >= min_merge_shares): mark complete, merge
4. Buffer: stop new orders when seconds_to_end < no_new_orders_sec, hold unhedged through settlement
5. Repricing: every tick, if best_bid changed → cancel + repost at new bid+0.01
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal

from py_clob_client.clob_types import OrderType

from complete_set.binance_ws import get_candle_state, get_last_btc_move, set_market_window, start_binance_ws
from complete_set.config import CompleteSetConfig
from complete_set.inventory import InventoryTracker
from complete_set.market_data import discover_markets, get_top_of_book, prefetch_order_books
from complete_set.mean_reversion import (
    MRDirection,
    evaluate_mean_reversion,
    evaluate_stop_hunt,
)
from complete_set.models import (
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
from complete_set.order_mgr import OrderManager
from complete_set.quote_calc import (
    calculate_balanced_shares,
    calculate_dynamic_edge,
    calculate_exposure,
    calculate_exposure_breakdown,
    total_bankroll_cap,
)
from complete_set.redeem import (
    CTF_DECIMALS,
    get_ctf_balances,
    get_usdc_balance,
    merge_positions,
    redeem_positions,
)
from complete_set.volatility import clear_market_history, opposite_was_cheap, record_prices
from complete_set.volume_imbalance import configure_windows, get_volume_state, start_volume_ws

log = logging.getLogger("cs.engine")

TICK_SIZE = Decimal("0.01")  # Default Polymarket tick size

# Lag tracking: previous asks per market for real reprice lag measurement
_prev_asks: dict[str, tuple[Decimal, Decimal]] = {}  # slug -> (prev_up_ask, prev_down_ask)


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
        self._last_summary_log: float = 0.0
        self._last_wallet_refresh: float = 0.0
        self._binance_ws_task: asyncio.Task | None = None
        self._volume_ws_task: asyncio.Task | None = None
        self._tick_count: int = 0
        self._tick_total_ms: float = 0.0
        self._tick_max_ms: float = 0.0
        self._last_reconcile: float = 0.0

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
        log.info("  Mean reversion  : %s (dev≥%s, range≤%s, window=%ds)",
                 "ON" if self._cfg.mean_reversion_enabled else "OFF",
                 self._cfg.mr_deviation_threshold, self._cfg.mr_max_range_pct,
                 self._cfg.mr_entry_window_sec)
        log.info("  Stop hunt       : %s (window=%d-%ds left)",
                 "ON" if self._cfg.stop_hunt_enabled else "OFF",
                 self._cfg.sh_entry_start_sec, self._cfg.sh_entry_end_sec)
        log.info("  Range filter    : %s (max=%s)",
                 "ON" if self._cfg.mr_range_filter_enabled else "OFF",
                 self._cfg.mr_max_range_pct)
        log.info("  Volume imbalance: %s (thresh=%s, min_btc=%s, windows=%d/%ds)",
                 "ON" if self._cfg.volume_imbalance_enabled else "OFF",
                 self._cfg.volume_imbalance_threshold, self._cfg.volume_min_btc,
                 self._cfg.volume_short_window_sec, self._cfg.volume_medium_window_sec)
        log.info("  Post-merge lock : %s", "ON" if self._cfg.post_merge_lockout else "OFF")
        log.info("  Swing filter    : %s (lookback=%ds, max_ask=%s)",
                 "ON" if self._cfg.swing_filter_enabled else "OFF",
                 self._cfg.swing_lookback_sec, self._cfg.swing_max_ask)
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

        tick_interval = max(0.1, self._cfg.refresh_millis / 1000.0)

        # Start Binance WS for candle state (needed by SH range filter and MR)
        if self._cfg.stop_hunt_enabled or self._cfg.mean_reversion_enabled:
            self._binance_ws_task = asyncio.create_task(start_binance_ws())
            log.info("BINANCE_WS │ background task started")

        # Start volume imbalance WS for direction prediction
        if self._cfg.volume_imbalance_enabled:
            configure_windows(self._cfg.volume_short_window_sec, self._cfg.volume_medium_window_sec)
            self._volume_ws_task = asyncio.create_task(start_volume_ws())
            log.info("VOLUME_WS │ background task started")

        try:
            while True:
                await self._tick()
                await asyncio.sleep(tick_interval)
        except asyncio.CancelledError:
            log.info("Engine cancelled, shutting down")
        finally:
            if self._binance_ws_task is not None:
                self._binance_ws_task.cancel()
            if self._volume_ws_task is not None:
                self._volume_ws_task.cancel()
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

        # -- Sync + evaluate in thread pool (blocks thread, not event loop) --
        await asyncio.to_thread(self._tick_core, now)

        # -- Settlements (needs asyncio for task management) --
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
        # Batch-fetch all order books in one HTTP POST — cache feeds
        # get_top_of_book() calls in _evaluate_market and _log_summary.
        prefetch_order_books(self._client, self._active_markets)

        self._inventory.sync_inventory(
            self._active_markets, get_mid_price=self._get_mid_price,
        )

        # Fill detection BEFORE evaluate: when the book moves (e.g. ask
        # drops to our BUY price), we must detect the fill before repricing
        # cancels the order.  In real trading, fills arrive independently
        # and before you can react to reprice.
        self._order_mgr.check_pending_orders(self._client, self._handle_fill)

        for market in self._active_markets:
            try:
                self._evaluate_market(market, now)
            except Exception as e:
                log.error("%sError evaluating %s: %s%s", C_RED, market.slug, e, C_RESET)

        # Periodic order reconciliation — upgrade sentinels, detect orphans
        if not self._cfg.dry_run and now - self._last_reconcile >= 30.0:
            self._last_reconcile = now
            self._order_mgr.reconcile_orders(self._client)

        # Periodic summary — runs in thread pool with cached TOB
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
                self._inventory.clear_market(slug)
                clear_market_history(slug)
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
        # Store dynamic edge from first leg entry
        if state.entry_dynamic_edge > ZERO:
            self._inventory.set_entry_dynamic_edge(state.market.slug, state.entry_dynamic_edge)
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

    def _find_merge_candidate(self, now: float) -> tuple[GabagoolMarket, Decimal] | None:
        """Find the first market eligible for merge. Returns (market, hedged_shares) or None."""
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
                    tx_hash, merged_display = result
                    self._inventory.reduce_merged(slug, merged_display)
                    self._merge_failures.pop(slug, None)
                    if not self._cfg.post_merge_lockout:
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
            max_gas_price_gwei=self._cfg.max_gas_price_gwei,
        )
        return (tx_hash, merged_display)

    def _refresh_wallet_balance(self) -> None:
        """Refresh wallet balance synchronously (called from thread pool)."""
        try:
            bal = get_usdc_balance(self._rpc_url, self._funder_address)
            self._cached_wallet_bal = f"${bal.quantize(Decimal('0.01'))}"
        except Exception:
            self._cached_wallet_bal = "err"

    @staticmethod
    def _resolve_entry_side(
        direction: MRDirection,
        up_ask: Decimal, down_ask: Decimal,
        up_bid: Decimal | None, down_bid: Decimal | None,
        market,
    ) -> tuple[str, Decimal, Decimal | None, Direction, str, str]:
        """Map MRDirection to (label, ask, bid, Direction, token_id, side_label)."""
        if direction == MRDirection.BUY_UP:
            return ("UP", up_ask, up_bid, Direction.UP, market.up_token_id, "UP")
        return ("DOWN", down_ask, down_bid, Direction.DOWN, market.down_token_id, "DOWN")

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
        ord_notional, unhedged_exp, hedged_locked, _ = calculate_exposure_breakdown(
            open_orders, all_inv,
        )
        open_count = len(open_orders)

        bankroll = self._cfg.bankroll_usd
        total_cap = total_bankroll_cap(bankroll) if bankroll > ZERO else bankroll
        remaining = max(ZERO, total_cap - exposure) if total_cap > ZERO else ZERO
        pct_used = (exposure / bankroll * 100).quantize(Decimal("0.1")) if bankroll > ZERO else ZERO

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

        # ── Wallet balance (cached, refreshed in background every 60s) ──
        wallet_str = self._cached_wallet_bal
        if self._rpc_url and self._funder_address and now - self._last_wallet_refresh >= 60:
            self._last_wallet_refresh = now
            self._refresh_wallet_balance()

        # ── SUMMARY header ──
        # Volume imbalance snapshot
        vol_str = ""
        if self._cfg.volume_imbalance_enabled:
            vs = get_volume_state()
            if not vs.is_stale:
                vol_str = f" │ vol_imb={vs.short_imbalance:+.3f}/{vs.medium_imbalance:+.3f} ({vs.short_volume_btc:.0f}BTC)"

        log.info(
            "── SUMMARY ── markets=%d │ open_orders=%d │ completed=%d │ exposure=$%s │ "
            "bankroll=$%s (%s%% used) │ wallet=%s │ %srealized=$%s │ unrealized=$%s │ total=$%s%s%s",
            len(self._active_markets), open_count, len(self._completed_markets),
            exposure.quantize(Decimal("0.01")),
            bankroll, pct_used, wallet_str,
            pnl_color, realized, unrealized, total_pnl, C_RESET,
            vol_str,
        )
        if self._tick_count > 0:
            avg_ms = self._tick_total_ms / self._tick_count
            log.info(
                "  TICK_STATS count=%d │ avg=%.0fms │ max=%.0fms",
                self._tick_count, avg_ms, self._tick_max_ms,
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

    def _place_first_leg(
        self,
        direction: MRDirection,
        market: GabagoolMarket,
        slug: str,
        up_ask: Decimal, down_ask: Decimal,
        up_bid: Decimal | None, down_bid: Decimal | None,
        max_first_leg: Decimal,
        dynamic_edge: Decimal,
        seconds_to_end: int,
        exposure: Decimal,
        reason: str,
        extra_log: str = "",
    ) -> None:
        """Place or reprice a first-leg maker order (shared by SH_ENTRY and MR_ENTRY)."""
        _, target_ask, target_bid, target_dir, target_token, side_label = (
            self._resolve_entry_side(direction, up_ask, down_ask, up_bid, down_bid, market)
        )

        if target_bid is None:
            log.debug("%s_SKIP %s │ no bid for %s", reason.split("_")[0], slug, side_label)
            return

        maker_price = min(target_bid + TICK_SIZE, target_ask - TICK_SIZE)

        if maker_price > max_first_leg:
            log.debug("%s_SKIP %s │ %s maker=%s > max_first=%.3f",
                      reason.split("_")[0], slug, side_label, maker_price, max_first_leg)
            return

        shares = calculate_balanced_shares(
            slug, up_ask, down_ask, self._cfg, seconds_to_end, exposure,
        )
        if shares is None:
            log.debug("%s_SKIP %s │ insufficient bankroll", reason.split("_")[0], slug)
            return

        # Reprice if book moved, or skip if price unchanged
        existing = self._order_mgr.get_order(target_token)
        if existing:
            if existing.price != maker_price:
                self._order_mgr.cancel_order(
                    self._client, target_token, "REPRICE", self._handle_fill)
                remaining = shares - (existing.matched_size or ZERO)
                if remaining >= self._cfg.min_merge_shares:
                    log.info("REPRICE %s │ %s %s→%s │ %s shares │ %ds left",
                             reason, slug, existing.price, maker_price, remaining, seconds_to_end)
                    rhr = remaining * max(ZERO, ONE - dynamic_edge - maker_price)
                    self._order_mgr.place_order(
                        self._client, market, target_token, target_dir,
                        maker_price, remaining, seconds_to_end, reason,
                        on_fill=self._handle_fill, order_type=OrderType.GTC,
                        reserved_hedge_notional=rhr,
                        entry_dynamic_edge=dynamic_edge)
            return

        # Swing filter: only enter if opposite side was recently cheap
        if self._cfg.swing_filter_enabled:
            buying_up = (direction == MRDirection.BUY_UP)
            if not opposite_was_cheap(
                slug, buying_up,
                self._cfg.swing_lookback_sec, self._cfg.swing_max_ask,
            ):
                opp = "DOWN" if buying_up else "UP"
                log.info(
                    "SWING_SKIP %s │ %s not cheap in last %ds (threshold=%s)",
                    slug, opp, self._cfg.swing_lookback_sec, self._cfg.swing_max_ask,
                )
                return

        hedge_reserve = shares * max(ZERO, ONE - dynamic_edge - maker_price)
        log.info(
            "%s%s %s │ %s maker=%s (bid=%s) │ %s │ shares=%s │ %ds left%s",
            C_GREEN, reason, slug, side_label, maker_price, target_bid, extra_log,
            shares, seconds_to_end, C_RESET,
        )

        self._order_mgr.place_order(
            self._client, market, target_token, target_dir,
            maker_price, shares, seconds_to_end, reason,
            on_fill=self._handle_fill,
            order_type=OrderType.GTC,
            reserved_hedge_notional=hedge_reserve,
            entry_dynamic_edge=dynamic_edge,
        )

    def _place_hedge_leg(
        self,
        market: GabagoolMarket,
        slug: str,
        inv,
        dynamic_edge: Decimal,
        seconds_to_end: int,
        exposure: Decimal,
        *,
        first_side: str,
        hedge_direction: Direction,
        first_vwap: Decimal | None,
        first_filled: Decimal,
        bootstrapped: bool,
        hedge_token: str,
        hedge_bid: Decimal | None,
        hedge_ask: Decimal,
    ) -> None:
        """Place or reprice a hedge-leg maker order (shared by UP-first and DOWN-first)."""
        hedge_side = hedge_direction.value  # "UP" or "DOWN"

        if bootstrapped:
            log.warning(
                "HEDGE_SKIP_BOOTSTRAP %s │ %s leg is bootstrapped (estimated VWAP), waiting for real fill or settlement",
                slug, first_side,
            )
            return

        if hedge_bid is None:
            log.debug("HEDGE_SKIP %s │ no bid for %s", slug, hedge_side)
            return

        maker_price = min(hedge_bid + TICK_SIZE, hedge_ask - TICK_SIZE)

        # Need: first_vwap + maker_price < 1.0 - hedge_edge - hedge_edge_buffer
        hedge_edge = max(dynamic_edge, inv.entry_dynamic_edge) + self._cfg.hedge_edge_buffer
        if first_vwap is None:
            return
        combined = first_vwap + maker_price
        edge = ONE - combined
        if edge < hedge_edge:
            log.debug(
                "HEDGE_SKIP %s │ %s_vwap=%s + %s_bid+1c=%s = %.3f │ edge=%.3f < %.3f",
                slug, first_side, first_vwap, hedge_side, maker_price, combined, edge, hedge_edge,
            )
            return

        hedge_shares = first_filled
        hedge_notional = hedge_shares * maker_price
        bankroll = self._cfg.bankroll_usd
        if bankroll > ZERO:
            cap = total_bankroll_cap(bankroll)
            remaining = cap - exposure
            if hedge_notional > remaining:
                log.debug("HEDGE_SKIP %s │ bankroll exhausted (need $%s, remaining $%s)",
                          slug, hedge_notional.quantize(Decimal("0.01")), remaining.quantize(Decimal("0.01")))
                return

        # Reprice if book moved, or skip if price unchanged
        existing = self._order_mgr.get_order(hedge_token)
        if existing:
            if existing.price != maker_price:
                self._order_mgr.cancel_order(
                    self._client, hedge_token, "REPRICE", self._handle_fill)
                remaining_shares = hedge_shares - (existing.matched_size or ZERO)
                if remaining_shares >= self._cfg.min_merge_shares:
                    log.info("REPRICE HEDGE_%s │ %s %s→%s │ %s shares │ %ds left",
                             hedge_side, slug, existing.price, maker_price, remaining_shares, seconds_to_end)
                    self._order_mgr.place_order(
                        self._client, market, hedge_token, hedge_direction,
                        maker_price, remaining_shares, seconds_to_end, "HEDGE_LEG",
                        on_fill=self._handle_fill, order_type=OrderType.GTC)
            return

        log.info(
            "%sHEDGE_LEG %s │ %s maker=%s (bid=%s) │ %s_vwap=%s │ edge=%.3f │ shares=%s │ %ds left%s",
            C_GREEN, slug, hedge_side, maker_price, hedge_bid, first_side, first_vwap, edge,
            hedge_shares, seconds_to_end, C_RESET,
        )

        self._order_mgr.place_order(
            self._client, market, hedge_token, hedge_direction,
            maker_price, hedge_shares, seconds_to_end, "HEDGE_LEG",
            on_fill=self._handle_fill,
            order_type=OrderType.GTC,
        )

    def _evaluate_market(self, market: GabagoolMarket, now: float) -> None:
        """Two-phase hedge: buy cheap leg first, then hedge the other when profitable."""
        slug = market.slug

        # Already hedged this window — skip
        if slug in self._completed_markets:
            return

        seconds_to_end = int(market.end_time - now)
        max_lifetime = 900 if market.market_type == "updown-15m" else 3600

        # Pre-resolution buffer: cancel pending orders, hold unhedged through settlement
        if 0 <= seconds_to_end < self._cfg.no_new_orders_sec:
            self._order_mgr.cancel_market_orders(self._client, market, "PRE_RESOLUTION_BUFFER", self._handle_fill)
            inv = self._inventory.get_inventory(slug)
            if inv.up_shares > ZERO or inv.down_shares > ZERO:
                log.info(
                    "BUFFER_HOLD %s │ U%s/D%s │ letting unhedged position resolve at settlement │ %ds left",
                    slug, inv.up_shares, inv.down_shares, seconds_to_end,
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
        up_bid = up_book.best_bid
        down_bid = down_book.best_bid

        # Lag trace: measure real reprice lag when book changes after BTC move
        # Only track when both asks are in meaningful range (0.20-0.80)
        candle_snap = get_candle_state()
        _LAG_MIN = Decimal("0.20")
        _LAG_MAX = Decimal("0.80")
        if (candle_snap.current_price > ZERO
                and _LAG_MIN <= up_ask <= _LAG_MAX and _LAG_MIN <= down_ask <= _LAG_MAX):
            tick_ts = time.time()
            move_ts, move_dir = get_last_btc_move()
            ask_sum = up_ask + down_ask
            prev = _prev_asks.get(slug)
            lag_str = ""
            if prev is not None and move_ts > 0:
                prev_up, prev_down = prev
                # BTC up → UP ask should increase, DOWN ask should decrease
                # BTC down → UP ask should decrease, DOWN ask should increase
                up_changed = up_ask != prev_up
                down_changed = down_ask != prev_down
                if up_changed or down_changed:
                    # Check if change is in expected direction
                    up_correct = (move_dir == 1 and up_ask > prev_up) or (move_dir == -1 and up_ask < prev_up)
                    down_correct = (move_dir == 1 and down_ask < prev_down) or (move_dir == -1 and down_ask > prev_down)
                    if up_correct or down_correct:
                        real_lag_ms = (tick_ts - move_ts) * 1000
                        if real_lag_ms < 15_000:
                            side = "U" if up_correct else "D"
                            lag_str = f" │ REPRICE={real_lag_ms:.0f}ms ({side})"
            _prev_asks[slug] = (up_ask, down_ask)
            bid_sum = (up_bid + down_bid) if up_bid is not None and down_bid is not None else None
            bid_str = f"{bid_sum:.3f}" if bid_sum is not None else "?"
            log.debug(
                "LAG_TRACE │ U=%.2f/%.2f D=%.2f/%.2f │ ask=%.3f bid=%s │ dev=%+.5f │ %s%s",
                up_bid or ZERO, up_ask, down_bid or ZERO, down_ask,
                ask_sum, bid_str, candle_snap.deviation, slug[:30], lag_str,
            )

        # Record prices for volatility tracking (always, even if we skip entry)
        record_prices(slug, up_ask, down_ask)

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

        # ── Phase 1: No position — try stop hunt (early), then mean reversion (late) ──
        if not has_up and not has_down:
            max_first_leg = (ONE - dynamic_edge) / 2

            # Set market window open price for Binance candle tracking
            window_start = market.end_time - max_lifetime
            set_market_window(window_start, rpc_url=self._rpc_url)
            candle = get_candle_state()

            # Volume state for direction prediction
            vol_state = get_volume_state() if self._cfg.volume_imbalance_enabled else None

            # ── Approach 1: Stop hunt (minutes 2-5) ──
            sh_signal = None
            if self._cfg.stop_hunt_enabled:
                sh_signal = evaluate_stop_hunt(
                    candle, up_ask, down_ask, seconds_to_end,
                    max_first_leg=max_first_leg,
                    max_range_pct=self._cfg.mr_max_range_pct,
                    sh_entry_start_sec=self._cfg.sh_entry_start_sec,
                    sh_entry_end_sec=self._cfg.sh_entry_end_sec,
                    no_new_orders_sec=self._cfg.no_new_orders_sec,
                    range_filter_enabled=self._cfg.mr_range_filter_enabled,
                    volume=vol_state,
                    volume_min_btc=self._cfg.volume_min_btc,
                    volume_imbalance_threshold=self._cfg.volume_imbalance_threshold,
                )

                if sh_signal.direction != MRDirection.SKIP:
                    self._place_first_leg(
                        sh_signal.direction, market, slug, up_ask, down_ask, up_bid, down_bid,
                        max_first_leg, dynamic_edge, seconds_to_end, exposure, "SH_ENTRY",
                        extra_log=f"range={sh_signal.range_pct:.5f}",
                    )
                    return

            # ── Approach 2: Mean reversion (last N minutes) ──
            if self._cfg.mean_reversion_enabled:
                mr_signal = evaluate_mean_reversion(
                    candle, seconds_to_end, up_ask, down_ask,
                    deviation_threshold=self._cfg.mr_deviation_threshold,
                    max_range_pct=self._cfg.mr_max_range_pct,
                    entry_window_sec=self._cfg.mr_entry_window_sec,
                    no_new_orders_sec=self._cfg.no_new_orders_sec,
                    range_filter_enabled=self._cfg.mr_range_filter_enabled,
                    volume=vol_state,
                    volume_min_btc=self._cfg.volume_min_btc,
                    volume_imbalance_threshold=self._cfg.volume_imbalance_threshold,
                )

                if mr_signal.direction != MRDirection.SKIP:
                    self._place_first_leg(
                        mr_signal.direction, market, slug, up_ask, down_ask, up_bid, down_bid,
                        max_first_leg, dynamic_edge, seconds_to_end, exposure, "MR_ENTRY",
                        extra_log=f"dev={mr_signal.deviation:+.5f}",
                    )
                    return

            # Log skip reasons for whichever signal was active
            _TIME_WINDOW_REASONS = {"before SH window", "past SH window", "outside entry window", "pre-resolution buffer"}
            if sh_signal is not None and sh_signal.reason not in _TIME_WINDOW_REASONS:
                log.debug(
                    "SH_SKIP %s │ range=%.5f │ %s │ %ds left",
                    slug, sh_signal.range_pct, sh_signal.reason, seconds_to_end,
                )
            return

        # ── Phase 2: One leg filled — hedge the other if edge is sufficient ──
        #    (same for both SH_ENTRY and MR_ENTRY first legs)
        if has_up and not has_down:
            self._place_hedge_leg(
                market, slug, inv, dynamic_edge, seconds_to_end, exposure,
                first_side="UP", hedge_direction=Direction.DOWN,
                first_vwap=inv.up_vwap, first_filled=inv.filled_up_shares,
                bootstrapped=inv.bootstrapped_up,
                hedge_token=market.down_token_id,
                hedge_bid=down_bid, hedge_ask=down_ask,
            )
            return

        if has_down and not has_up:
            self._place_hedge_leg(
                market, slug, inv, dynamic_edge, seconds_to_end, exposure,
                first_side="DOWN", hedge_direction=Direction.UP,
                first_vwap=inv.down_vwap, first_filled=inv.filled_down_shares,
                bootstrapped=inv.bootstrapped_down,
                hedge_token=market.up_token_id,
                hedge_bid=up_bid, hedge_ask=up_ask,
            )
