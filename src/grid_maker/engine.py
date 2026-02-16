"""Grid-maker engine — dense penny-grid market making (Gabagool clone).

Posts GTC BUY grids on both Up and Down simultaneously, collects fills,
merges balanced pairs, and uses TAKER aggression to hedge imbalances.
Revenue comes from maker rebates, not edge.

Supports two grid modes:
  - "dynamic": builds grids from best_bid, reprices on drift (original)
  - "static": full-range $0.01-$0.99 grid, fire-and-forget (gabagool clone)

Supports two merge modes:
  - "eager": per-market merge when balanced (original)
  - "batch": sweep all markets every merge_batch_interval_sec
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal

from py_clob_client.clob_types import OrderType

from grid_maker.capital import (
    calculate_grid_allocation,
    calculate_per_market_budget,
    calculate_static_grid,
    compound_bankroll,
    scale_grid_params,
)
from grid_maker.config import GridMakerConfig
from grid_maker.market_data import discover_markets
from shared.market_data import get_top_of_book, prefetch_order_books
from shared.models import (
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
)
from shared.order_mgr import OrderManager
from shared.redeem import merge_positions

log = logging.getLogger("gm.engine")


class GridMakerEngine:
    def __init__(self, client, cfg: GridMakerConfig, w3=None, account=None,
                 rpc_url: str = "", funder_address: str = ""):
        self._client = client
        self._cfg = cfg
        self._w3 = w3
        self._account = account
        self._rpc_url = rpc_url
        self._funder = funder_address
        self._order_mgr = OrderManager(dry_run=cfg.dry_run)

        # Per-market state
        self._markets: list[GabagoolMarket] = []
        self._last_discovery: float = 0.0
        self._discovery_interval: float = 10.0

        # Per-token filled shares tracking (only from fills, not chain sync)
        self._filled_shares: dict[str, Decimal] = {}  # token_id -> shares filled

        # Merge tracking
        self._last_merge_at: dict[str, float] = {}  # slug -> epoch
        self._last_batch_merge_at: float = 0.0
        self._completed_markets: set[str] = set()

        # Compounding
        self._session_pnl = ZERO
        self._last_compound_at: float = 0.0
        self._effective_bankroll = cfg.bankroll_usd

        # Static grid state
        self._grid_spec: dict[str, list[tuple[Decimal, Decimal]]] = {}  # token_id -> intended grid
        self._active_grid_levels: dict[str, set[Decimal]] = {}  # token -> live prices

    async def run(self) -> None:
        """Main loop — discover markets and tick."""
        interval = self._cfg.refresh_millis / 1000.0

        log.info(
            "%s╔══════════════════════════════════════╗%s", C_BOLD, C_RESET,
        )
        log.info(
            "%s║   GRID MAKER — Gabagool Clone        ║%s", C_BOLD, C_RESET,
        )
        log.info(
            "%s╚══════════════════════════════════════╝%s", C_BOLD, C_RESET,
        )
        log.info(
            "bankroll=$%s │ mode=%s │ step=%s │ dry=%s │ merge=%s │ assets=%s │ tf=%s",
            self._cfg.bankroll_usd,
            self._cfg.grid_mode,
            self._cfg.grid_step,
            self._cfg.dry_run,
            self._cfg.merge_mode,
            ",".join(self._cfg.assets),
            ",".join(self._cfg.timeframes),
        )
        if self._cfg.grid_mode == "static":
            log.info(
                "static grid │ range=$%s-$%s │ fixed_size=%s shares/level",
                self._cfg.min_entry_price, self._cfg.max_entry_price,
                self._cfg.fixed_size_shares,
            )

        # Restore grid state from existing CLOB orders on restart
        if self._cfg.grid_mode == "static":
            self._restore_grid_state()

        while True:
            try:
                await asyncio.to_thread(self._tick)
            except Exception as e:
                log.error("TICK_ERROR │ %s", e, exc_info=True)
            await asyncio.sleep(interval)

    def _tick(self) -> None:
        """Single tick: discover, prefetch books, evaluate each market."""
        now = time.time()

        # Periodic discovery
        if now - self._last_discovery > self._discovery_interval:
            self._discover(now)

        if not self._markets:
            return

        # Prefetch all order books in one batch
        prefetch_order_books(self._client, self._markets)

        # Check pending orders for fills — use bulk when static mode
        if self._cfg.grid_mode == "static":
            self._order_mgr.check_pending_orders_bulk(self._client, on_fill=self._on_fill)
        else:
            self._order_mgr.check_pending_orders(self._client, on_fill=self._on_fill)

        # Evaluate each market
        for market in list(self._markets):
            if market.slug in self._completed_markets:
                continue
            self._evaluate_market(market, now)

        # Batch merge (if configured)
        if self._cfg.merge_mode == "batch":
            self._batch_merge(now)

        # Periodic compounding
        if self._cfg.compound and now - self._last_compound_at > self._cfg.compound_interval_sec:
            self._compound(now)

    def _discover(self, now: float) -> None:
        """Discover active markets."""
        new_markets = discover_markets(
            self._cfg.assets,
            self._cfg.timeframes,
            self._cfg.max_markets,
        )
        if new_markets:
            active_slugs = {m.slug for m in new_markets}
            self._completed_markets &= active_slugs
            self._markets = new_markets
            log.info("DISCOVERY │ %d markets active", len(new_markets))
        self._last_discovery = now

    def _evaluate_market(self, market: GabagoolMarket, now: float) -> None:
        """Evaluate a single market: post grid, maintain, hedge, merge."""
        seconds_to_end = int(market.end_time - now)

        # Market expired
        if seconds_to_end <= 0:
            self._cleanup_market(market, "EXPIRED")
            return

        # Outside time window
        if seconds_to_end > self._cfg.max_seconds_to_end:
            return
        if seconds_to_end < self._cfg.min_seconds_to_end:
            self._cleanup_market(market, "TIME_UP")
            return

        # Entry delay — don't post grid too early in the window
        window_elapsed = self._cfg.max_seconds_to_end - seconds_to_end
        if window_elapsed < self._cfg.entry_delay_sec:
            return

        # Get TOB for both sides
        up_tob = get_top_of_book(self._client, market.up_token_id)
        down_tob = get_top_of_book(self._client, market.down_token_id)

        if up_tob is None or down_tob is None:
            return

        # Check if we have existing orders
        has_up_orders = self._order_mgr.has_order(market.up_token_id)
        has_down_orders = self._order_mgr.has_order(market.down_token_id)

        if self._cfg.grid_mode == "static":
            if not has_up_orders and not has_down_orders:
                self._post_initial_grid_static(market, seconds_to_end)
            else:
                self._maintain_grid_static(market, seconds_to_end)
        else:
            if not has_up_orders and not has_down_orders:
                self._post_initial_grid(market, up_tob, down_tob, seconds_to_end)
            else:
                self._maintain_grid(market, up_tob, down_tob, seconds_to_end)

        # Check for TAKER hedge opportunity
        self._check_taker_hedge(market, up_tob, down_tob, seconds_to_end)

        # Check for eager merge (per-market)
        if self._cfg.merge_mode == "eager":
            self._check_merge(market, now)

    # -----------------------------------------------------------------
    # Static grid mode
    # -----------------------------------------------------------------

    def _post_initial_grid_static(
        self, market: GabagoolMarket, seconds_to_end: int,
    ) -> None:
        """Post full-range static grid on both sides."""
        budget = calculate_per_market_budget(
            self._effective_bankroll, max(1, len(self._markets)),
        )
        if budget <= ZERO:
            return

        side_budget = budget / 2

        for token_id, direction in [
            (market.up_token_id, Direction.UP),
            (market.down_token_id, Direction.DOWN),
        ]:
            grid = calculate_static_grid(
                self._cfg.min_entry_price,
                self._cfg.max_entry_price,
                self._cfg.grid_step,
                self._cfg.fixed_size_shares,
                side_budget,
            )
            self._grid_spec[token_id] = grid
            self._active_grid_levels[token_id] = set()

            for price, sz in grid:
                self._order_mgr.place_order(
                    self._client, market, token_id,
                    direction, price, sz, seconds_to_end,
                    reason="GRID_INIT",
                )
                self._active_grid_levels[token_id].add(price)

        n_levels = len(self._grid_spec.get(market.up_token_id, []))
        log.info(
            "%sGRID_POST_STATIC %s │ budget=$%s │ %d levels/side │ "
            "$%s-$%s @ %s shares%s",
            C_GREEN, market.slug[:40], budget, n_levels,
            self._cfg.min_entry_price, self._cfg.max_entry_price,
            self._cfg.fixed_size_shares, C_RESET,
        )

    def _maintain_grid_static(
        self, market: GabagoolMarket, seconds_to_end: int,
    ) -> None:
        """Fill-replenish: repost consumed levels, never cancel/reprice."""
        for token_id, direction in [
            (market.up_token_id, Direction.UP),
            (market.down_token_id, Direction.DOWN),
        ]:
            spec = self._grid_spec.get(token_id, [])
            if not spec:
                continue

            active = self._active_grid_levels.get(token_id, set())
            intended_prices = {price for price, _ in spec}
            missing = intended_prices - active

            if not missing:
                continue

            # Build price->size lookup from spec
            spec_lookup = {price: sz for price, sz in spec}

            for price in sorted(missing):
                sz = spec_lookup[price]
                self._order_mgr.place_order(
                    self._client, market, token_id,
                    direction, price, sz, seconds_to_end,
                    reason="GRID_REPLENISH",
                )
                active.add(price)

            log.debug(
                "GRID_REPLENISH %s %s │ %d levels reposted",
                market.slug[:30], direction.value, len(missing),
            )

    def _restore_grid_state(self) -> None:
        """Restore grid state from existing CLOB orders on restart.

        Fetches open orders from CLOB, matches against grid_spec prices,
        and populates _active_grid_levels to prevent duplicate posting.
        """
        if self._cfg.dry_run:
            return

        try:
            open_orders = self._client.get_orders()
        except Exception as e:
            log.warning("RESTORE_GRID_FAILED: %s", e)
            return

        if not open_orders or not isinstance(open_orders, list):
            return

        restored_count = 0
        for order in open_orders:
            if not isinstance(order, dict):
                continue
            token_id = order.get("asset_id") or order.get("token_id", "")
            if not token_id:
                continue

            price_str = order.get("price")
            if not price_str:
                continue

            price = Decimal(str(price_str))

            if token_id not in self._active_grid_levels:
                self._active_grid_levels[token_id] = set()
            self._active_grid_levels[token_id].add(price)
            restored_count += 1

        if restored_count:
            log.info(
                "GRID_RESTORE │ %d orders recovered from CLOB across %d tokens",
                restored_count, len(self._active_grid_levels),
            )

    # -----------------------------------------------------------------
    # Dynamic grid mode (original behavior)
    # -----------------------------------------------------------------

    def _post_initial_grid(
        self, market: GabagoolMarket, up_tob, down_tob, seconds_to_end: int,
    ) -> None:
        """Post initial grid on both sides of a market (dynamic mode)."""
        budget = calculate_per_market_budget(
            self._effective_bankroll, max(1, len(self._markets)),
        )
        if budget <= ZERO:
            return

        # Half budget per side
        side_budget = budget / 2

        # Scale grid params based on bankroll
        levels, size = scale_grid_params(
            self._effective_bankroll,
            self._cfg.grid_levels_per_side,
            self._cfg.base_size_shares,
        )

        # Generate grid for UP side
        if up_tob.best_bid is not None:
            up_levels = calculate_grid_allocation(
                side_budget, levels, size,
                self._cfg.grid_step, up_tob.best_bid,
                self._cfg.size_curve,
            )
            for price, sz in up_levels:
                if price < self._cfg.min_entry_price or price > self._cfg.max_entry_price:
                    continue
                self._order_mgr.place_order(
                    self._client, market, market.up_token_id,
                    Direction.UP, price, sz, seconds_to_end,
                    reason="GRID_INIT",
                )

        # Generate grid for DOWN side
        if down_tob.best_bid is not None:
            down_levels = calculate_grid_allocation(
                side_budget, levels, size,
                self._cfg.grid_step, down_tob.best_bid,
                self._cfg.size_curve,
            )
            for price, sz in down_levels:
                if price < self._cfg.min_entry_price or price > self._cfg.max_entry_price:
                    continue
                self._order_mgr.place_order(
                    self._client, market, market.down_token_id,
                    Direction.DOWN, price, sz, seconds_to_end,
                    reason="GRID_INIT",
                )

        log.info(
            "%sGRID_POST %s │ budget=$%s │ %d levels/side%s",
            C_GREEN, market.slug[:40], budget, levels, C_RESET,
        )

    def _maintain_grid(
        self, market: GabagoolMarket, up_tob, down_tob, seconds_to_end: int,
    ) -> None:
        """Maintain grid — cancel stale levels, post new ones tracking book (dynamic mode)."""
        for token_id, tob, direction in [
            (market.up_token_id, up_tob, Direction.UP),
            (market.down_token_id, down_tob, Direction.DOWN),
        ]:
            if tob is None or tob.best_bid is None:
                continue

            orders = self._order_mgr.get_all_orders_for_token(token_id)
            if not orders:
                # No orders on this side — repost
                budget = calculate_per_market_budget(
                    self._effective_bankroll, max(1, len(self._markets)),
                ) / 2
                levels, size = scale_grid_params(
                    self._effective_bankroll,
                    self._cfg.grid_levels_per_side,
                    self._cfg.base_size_shares,
                )
                grid = calculate_grid_allocation(
                    budget, levels, size,
                    self._cfg.grid_step, tob.best_bid,
                    self._cfg.size_curve,
                )
                for price, sz in grid:
                    if price < self._cfg.min_entry_price or price > self._cfg.max_entry_price:
                        continue
                    self._order_mgr.place_order(
                        self._client, market, token_id,
                        direction, price, sz, seconds_to_end,
                        reason="GRID_REPOST",
                    )
                continue

            # Check if book has moved significantly — if best_bid moved by
            # more than 2 steps from the nearest order, cancel and repost
            order_prices = [o.price for o in orders]
            if order_prices:
                nearest = min(order_prices, key=lambda p: abs(p - tob.best_bid))
                drift = abs(nearest - tob.best_bid)
                if drift > self._cfg.grid_step * 3:
                    log.debug(
                        "GRID_DRIFT %s %s │ drift=%s > %s │ reposting",
                        market.slug[:30], direction.value, drift, self._cfg.grid_step * 3,
                    )
                    self._order_mgr.cancel_all_for_token(
                        self._client, token_id, reason="GRID_DRIFT",
                        on_fill=self._on_fill,
                    )
                    # Repost will happen next tick when no orders exist

    # -----------------------------------------------------------------
    # Taker hedge
    # -----------------------------------------------------------------

    def _check_taker_hedge(
        self, market: GabagoolMarket, up_tob, down_tob, seconds_to_end: int,
    ) -> None:
        """Use FOK TAKER buy on deficit side when imbalance exceeds threshold."""
        up_filled = self._filled_shares.get(market.up_token_id, ZERO)
        down_filled = self._filled_shares.get(market.down_token_id, ZERO)

        total_filled = up_filled + down_filled
        if total_filled <= ZERO:
            return

        imbalance = abs(up_filled - down_filled) / total_filled
        if imbalance < self._cfg.taker_trigger_imbalance:
            return

        # Determine deficit side
        if up_filled > down_filled:
            deficit_token = market.down_token_id
            deficit_direction = Direction.DOWN
            deficit_tob = down_tob
            deficit_shares = up_filled - down_filled
        else:
            deficit_token = market.up_token_id
            deficit_direction = Direction.UP
            deficit_tob = up_tob
            deficit_shares = down_filled - up_filled

        if deficit_tob is None or deficit_tob.best_ask is None:
            return

        # Taker budget = aggression_pct of per-market budget
        taker_budget = (
            calculate_per_market_budget(self._effective_bankroll, max(1, len(self._markets)))
            * self._cfg.taker_aggression_pct
        )
        max_taker_shares = (taker_budget / deficit_tob.best_ask).quantize(
            Decimal("0.01"), rounding=0  # ROUND_DOWN
        )
        hedge_size = min(deficit_shares, max_taker_shares)

        if hedge_size < Decimal("5"):
            return

        log.info(
            "%sTAKER_HEDGE %s │ %s deficit=%s imbalance=%.0f%% │ FOK %s x%s @ %s%s",
            C_YELLOW, market.slug[:30], deficit_direction.value,
            deficit_shares, float(imbalance * 100),
            deficit_direction.value, hedge_size, deficit_tob.best_ask,
            C_RESET,
        )

        self._order_mgr.place_order(
            self._client, market, deficit_token,
            deficit_direction, deficit_tob.best_ask, hedge_size,
            seconds_to_end, reason="TAKER_HEDGE",
            order_type=OrderType.FOK if self._cfg.use_fok else None,
        )

    # -----------------------------------------------------------------
    # Merge
    # -----------------------------------------------------------------

    def _check_merge(self, market: GabagoolMarket, now: float) -> None:
        """Check if balanced shares are ready to merge (eager mode, per-market)."""
        up_filled = self._filled_shares.get(market.up_token_id, ZERO)
        down_filled = self._filled_shares.get(market.down_token_id, ZERO)

        balanced = min(up_filled, down_filled)
        if balanced < self._cfg.min_merge_shares:
            return

        # Cooldown
        last_merge = self._last_merge_at.get(market.slug, 0.0)
        if now - last_merge < self._cfg.merge_cooldown_sec:
            return

        self._execute_merge(market, balanced, now)

    def _batch_merge(self, now: float) -> None:
        """Sweep all markets for merge opportunities on a timer."""
        if now - self._last_batch_merge_at < self._cfg.merge_batch_interval_sec:
            return

        merged_count = 0
        for market in self._markets:
            if market.slug in self._completed_markets:
                continue

            up_filled = self._filled_shares.get(market.up_token_id, ZERO)
            down_filled = self._filled_shares.get(market.down_token_id, ZERO)
            balanced = min(up_filled, down_filled)

            if balanced < self._cfg.min_merge_shares:
                continue

            self._execute_merge(market, balanced, now)
            merged_count += 1

        self._last_batch_merge_at = now
        if merged_count:
            log.info(
                "%sBATCH_MERGE │ %d markets merged%s",
                C_GREEN, merged_count, C_RESET,
            )

    def _execute_merge(
        self, market: GabagoolMarket, balanced: Decimal, now: float,
    ) -> None:
        """Execute a merge for a market with balanced shares."""
        if not market.condition_id:
            log.warning("MERGE_SKIP %s │ no condition_id", market.slug[:30])
            return

        up_filled = self._filled_shares.get(market.up_token_id, ZERO)
        down_filled = self._filled_shares.get(market.down_token_id, ZERO)

        # Merge amount in base units (6 decimals for CTF)
        merge_amount = int(balanced * 10**6)

        log.info(
            "%sMERGE %s │ balanced=%s shares │ amount=%d%s",
            C_GREEN, market.slug[:30], balanced, merge_amount, C_RESET,
        )

        if self._cfg.dry_run:
            # Simulate merge
            gas_cost = self._cfg.matic_price_usd * Decimal("0.003")
            pnl = balanced * ONE - gas_cost  # $1/pair minus gas
            self._session_pnl += pnl
            log.info(
                "%sDRY_MERGE %s │ pnl=$%s (gas=$%s)%s",
                C_GREEN, market.slug[:30], pnl, gas_cost, C_RESET,
            )
        elif self._w3 and self._account and self._funder:
            try:
                result = merge_positions(
                    self._w3, self._account, self._funder,
                    market.condition_id, merge_amount,
                    neg_risk=market.neg_risk,
                    max_gas_price_gwei=self._cfg.max_gas_price_gwei,
                )
                gas_usd = Decimal(result.gas_cost_wei) / Decimal(10**18) * self._cfg.matic_price_usd
                pnl = balanced * ONE - gas_usd
                self._session_pnl += pnl
                log.info(
                    "%sMERGE_CONFIRMED %s │ tx=%s pnl=$%s%s",
                    C_GREEN, market.slug[:30], result.tx_hash, pnl, C_RESET,
                )
            except Exception as e:
                log.error("%sMERGE_FAILED %s │ %s%s", C_RED, market.slug[:30], e, C_RESET)
                return

        # Reduce filled shares
        self._filled_shares[market.up_token_id] = up_filled - balanced
        self._filled_shares[market.down_token_id] = down_filled - balanced
        self._last_merge_at[market.slug] = now

        # Mark completed if everything merged
        if self._filled_shares.get(market.up_token_id, ZERO) <= ZERO and \
           self._filled_shares.get(market.down_token_id, ZERO) <= ZERO:
            self._completed_markets.add(market.slug)

    # -----------------------------------------------------------------
    # Fill callback
    # -----------------------------------------------------------------

    def _on_fill(self, order_state, delta: Decimal) -> None:
        """Callback when an order is filled."""
        if order_state is None or delta <= ZERO:
            return

        token_id = order_state.token_id
        self._filled_shares[token_id] = self._filled_shares.get(token_id, ZERO) + delta

        direction = order_state.direction.value if order_state.direction else "?"
        market_slug = order_state.market.slug[:30] if order_state.market else "?"

        log.info(
            "%sFILL %s │ %s +%s @ %s │ total=%s%s",
            C_GREEN, market_slug, direction, delta, order_state.price,
            self._filled_shares[token_id], C_RESET,
        )

        # In static mode, remove the filled price from active levels
        # so maintain_grid_static will replenish it
        if self._cfg.grid_mode == "static":
            active = self._active_grid_levels.get(token_id)
            if active is not None:
                active.discard(order_state.price)

    # -----------------------------------------------------------------
    # Cleanup & compounding
    # -----------------------------------------------------------------

    def _cleanup_market(self, market: GabagoolMarket, reason: str) -> None:
        """Cancel all orders for a market and mark as completed."""
        self._order_mgr.cancel_market_orders(
            self._client, market, reason=reason, on_fill=self._on_fill,
        )
        self._completed_markets.add(market.slug)
        # Clean up static grid state
        self._grid_spec.pop(market.up_token_id, None)
        self._grid_spec.pop(market.down_token_id, None)
        self._active_grid_levels.pop(market.up_token_id, None)
        self._active_grid_levels.pop(market.down_token_id, None)
        log.info("%sCLEANUP %s │ %s%s", C_DIM, market.slug[:40], reason, C_RESET)

    def _compound(self, now: float) -> None:
        """Recalculate effective bankroll from session P&L."""
        new_bankroll = compound_bankroll(self._effective_bankroll, self._session_pnl)
        if new_bankroll != self._effective_bankroll:
            log.info(
                "COMPOUND │ $%s → $%s (pnl=$%s)",
                self._effective_bankroll, new_bankroll, self._session_pnl,
            )
            self._effective_bankroll = new_bankroll
        self._last_compound_at = now
