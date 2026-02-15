"""TrendRiderEngine — directional momentum strategy for tight-spread markets.

Buys the winning side when BTC trends and complete-set has no edge (combined asks >= 0.98).
Holds to resolution. Stop-loss on BTC reversal + price drop.
"""

from __future__ import annotations

import asyncio
import logging
import time
from decimal import Decimal

from py_clob_client.clob_types import OrderType

from complete_set.binance_ws import is_btc_trending
from complete_set.market_data import discover_markets, get_top_of_book, prefetch_order_books
from complete_set.models import (
    C_DIM,
    C_GREEN,
    C_RED,
    C_RESET,
    ZERO,
    Direction,
    GabagoolMarket,
    OrderState,
)
from complete_set.events import EventType, emit
from complete_set.order_mgr import OrderManager
from trend_rider.config import TrendRiderConfig
from trend_rider.positions import TrendPositionTracker
from trend_rider.signal import evaluate_trend_entry
from trend_rider.sizing import calculate_trend_size

log = logging.getLogger("tr.engine")


class TrendRiderEngine:
    def __init__(self, client, cfg: TrendRiderConfig, cs_engine=None):
        self._client = client
        self._cfg = cfg
        self._order_mgr = OrderManager(dry_run=cfg.dry_run)
        self._positions = TrendPositionTracker()
        self._cs_engine = cs_engine
        self._active_markets: list[GabagoolMarket] = []
        self._last_discovery: float = 0.0
        self._bg_discovery: asyncio.Task | None = None
        self._tick_count: int = 0
        self._tick_total_ms: float = 0.0
        self._tick_max_ms: float = 0.0
        self._last_summary_log: float = 0.0

    async def run(self) -> None:
        mode = "DRY RUN" if self._cfg.dry_run else "LIVE"
        log.info("=" * 56)
        log.info("  Trend Rider Engine v0.1.0  [%s]", mode)
        log.info("=" * 56)
        log.info("  Bankroll        : $%s", self._cfg.bankroll_usd)
        log.info(
            "  Time window     : %d-%ds to end",
            self._cfg.min_seconds_to_end, self._cfg.max_seconds_to_end,
        )
        log.info(
            "  Momentum        : $%s/%ds",
            self._cfg.momentum_threshold_usd, self._cfg.momentum_lookback_sec,
        )
        log.info(
            "  Fav price range : [%s, %s]",
            self._cfg.min_favorite_price, self._cfg.max_favorite_price,
        )
        log.info("  Combined asks   : >= %s", self._cfg.min_combined_asks)
        log.info(
            "  Max positions   : %d @ %s%% bankroll",
            self._cfg.max_positions, self._cfg.max_position_pct * 100,
        )
        log.info("  Stop-loss drop  : %s", self._cfg.stop_loss_drop)
        log.info("  Order type      : %s", "FOK" if self._cfg.use_fok else "GTC")
        log.info("=" * 56)

        tick_interval = self._cfg.refresh_millis / 1000.0

        try:
            while True:
                await self._tick()
                await asyncio.sleep(tick_interval)
        except asyncio.CancelledError:
            log.info("TrendRider cancelled, shutting down")
        finally:
            self._order_mgr.cancel_all(self._client, "SHUTDOWN", self._handle_fill)

    async def _tick(self) -> None:
        tick_start = time.monotonic()
        now = time.time()

        # Harvest background discovery
        if self._bg_discovery is not None and self._bg_discovery.done():
            try:
                new_markets = self._bg_discovery.result()
                self._apply_discovery(new_markets, now)
            except Exception as e:
                log.warning("Discovery failed: %s", e)
            self._bg_discovery = None

        # Launch background discovery every 30s
        if now - self._last_discovery > 30.0 and self._bg_discovery is None:
            self._last_discovery = now
            # Reuse same discovery as CS — markets are the same
            self._bg_discovery = asyncio.ensure_future(
                asyncio.to_thread(discover_markets, ("bitcoin",))
            )

        # Sync + evaluate in thread pool
        await asyncio.to_thread(self._tick_core, now)

        # Tick timing
        tick_ms = (time.monotonic() - tick_start) * 1000
        self._tick_count += 1
        self._tick_total_ms += tick_ms
        if tick_ms > self._tick_max_ms:
            self._tick_max_ms = tick_ms
        budget_ms = self._cfg.refresh_millis
        if tick_ms > budget_ms * 0.8:
            log.warning("TR_TICK_SLOW %.0fms (budget=%dms)", tick_ms, budget_ms)

    def _tick_core(self, now: float) -> None:
        prefetch_order_books(self._client, self._active_markets)
        self._order_mgr.check_pending_orders(self._client, self._handle_fill)
        self._check_stop_losses(now)

        for market in self._active_markets:
            try:
                self._evaluate_entry(market, now)
            except Exception as e:
                log.error("TR_ERROR %s: %s", market.slug, e)

        # Periodic summary
        if now - self._last_summary_log >= 30:
            self._last_summary_log = now
            self._log_summary(now)

    def _apply_discovery(self, new_markets: list[GabagoolMarket], now: float) -> None:
        old_slugs = {m.slug for m in self._active_markets}
        self._active_markets = new_markets
        new_slugs = {m.slug for m in self._active_markets}

        # Clear resolved positions for rotated-out markets
        for slug in old_slugs - new_slugs:
            pos = self._positions.get_position(slug)
            if pos:
                # Market rotated out = resolution happened
                # We can't know if we won here — assume resolution already paid out
                self._positions.clear_resolved(slug, won=False)
                log.info(
                    "TR_ROTATED slug=%s — position cleared (assume resolved)",
                    slug,
                )

    def _evaluate_entry(self, market: GabagoolMarket, now: float) -> None:
        slug = market.slug
        seconds_to_end = int(market.end_time - now)

        # Already have a position
        if self._positions.get_position(slug):
            return

        # Already at max positions
        if self._positions.position_count >= self._cfg.max_positions:
            return

        # CS engine is active on this market — avoid conflicts
        if self._cs_engine is not None:
            cs_active = self._cs_engine.get_active_slugs()
            if slug in cs_active:
                return

        # Already have a pending order on this market
        has_pending = (
            self._order_mgr.has_order(market.up_token_id)
            or self._order_mgr.has_order(market.down_token_id)
        )
        if has_pending:
            return

        # Fetch TOB
        up_tob = get_top_of_book(self._client, market.up_token_id)
        down_tob = get_top_of_book(self._client, market.down_token_id)
        if not up_tob or not down_tob:
            return

        up_ask = up_tob.best_ask
        down_ask = down_tob.best_ask
        up_bid = up_tob.best_bid
        down_bid = down_tob.best_bid

        # Evaluate signal
        signal = evaluate_trend_entry(
            seconds_to_end=seconds_to_end,
            up_ask=up_ask,
            down_ask=down_ask,
            up_bid=up_bid,
            down_bid=down_bid,
            cfg=self._cfg,
        )
        if signal is None:
            return

        # Determine token and price to buy
        if signal.direction == Direction.UP:
            token_id = market.up_token_id
            entry_price = up_ask
        else:
            token_id = market.down_token_id
            entry_price = down_ask

        # Size the position
        exposure = self._positions.total_exposure()
        shares = calculate_trend_size(entry_price, self._cfg, exposure)
        if shares is None:
            log.debug("TR_SKIP_SIZE slug=%s price=%.2f exposure=$%.2f", slug, entry_price, exposure)
            return

        log.info(
            "%sTREND_ENTRY%s slug=%s dir=%s ask=%.2f shares=%s ($%.2f) │ %s",
            C_GREEN, C_RESET,
            slug[:40], signal.direction.value, entry_price, shares,
            entry_price * shares, signal.reason,
        )

        order_type = OrderType.FOK if self._cfg.use_fok else OrderType.GTC
        self._order_mgr.place_order(
            client=self._client,
            market=market,
            token_id=token_id,
            direction=signal.direction,
            price=entry_price,
            size=shares,
            seconds_to_end=seconds_to_end,
            reason="TREND_ENTRY",
            on_fill=None,
            order_type=order_type,
            side="BUY",
        )
        emit(EventType.ORDER_PLACED, {
            "slug": slug,
            "direction": signal.direction.value,
            "side": "BUY",
            "price": float(entry_price),
            "shares": float(shares),
            "strategy": "trend_rider",
            "reason": signal.reason,
        }, slug)

    def _check_stop_losses(self, now: float) -> None:
        for slug in list(self._positions.get_all_slugs()):
            pos = self._positions.get_position(slug)
            if not pos:
                continue

            # Find the market for this position
            market = None
            for m in self._active_markets:
                if m.slug == slug:
                    market = m
                    break
            if not market:
                continue

            # Get current bid for our side
            if pos.direction == Direction.UP:
                tob = get_top_of_book(self._client, market.up_token_id)
            else:
                tob = get_top_of_book(self._client, market.down_token_id)

            if not tob or tob.best_bid is None:
                continue

            current_bid = tob.best_bid
            price_drop = pos.entry_price - current_bid

            # Stop-loss requires BOTH conditions:
            # 1. Price dropped below entry - stop_loss_drop
            # 2. BTC has reversed direction
            if price_drop < self._cfg.stop_loss_drop:
                continue

            # Check BTC reversal
            trending, btc_move = is_btc_trending(
                lookback_sec=self._cfg.momentum_lookback_sec,
                threshold=self._cfg.momentum_threshold_usd,
            )
            if not trending:
                # BTC not trending = momentum died, trigger stop
                pass
            elif (pos.direction == Direction.UP and btc_move > ZERO) or \
                 (pos.direction == Direction.DOWN and btc_move < ZERO):
                # BTC still moving in our direction — hold despite price drop
                continue

            # Both conditions met: sell at bid
            log.info(
                "%sTREND_STOP%s slug=%s dir=%s entry=%.2f bid=%.2f drop=%.2f btc=$%.0f",
                C_RED, C_RESET,
                slug[:40], pos.direction.value, pos.entry_price, current_bid, price_drop, btc_move,
            )

            order_type = OrderType.FOK if self._cfg.use_fok else OrderType.GTC
            self._order_mgr.place_order(
                client=self._client,
                market=market,
                token_id=pos.token_id,
                direction=pos.direction,
                price=current_bid,
                size=pos.shares,
                seconds_to_end=int(market.end_time - now),
                reason="TREND_STOP",
                on_fill=None,
                order_type=order_type,
                side="SELL",
            )
            emit(EventType.ORDER_PLACED, {
                "slug": slug,
                "direction": pos.direction.value,
                "side": "SELL",
                "price": float(current_bid),
                "shares": float(pos.shares),
                "strategy": "trend_rider",
                "reason": "TREND_STOP",
            }, slug)

    def _handle_fill(self, state: OrderState, filled_shares: Decimal) -> None:
        slug = state.market.slug
        if state.side == "BUY":
            self._positions.record_entry(
                slug=slug,
                direction=state.direction,
                token_id=state.token_id,
                shares=filled_shares,
                price=state.price,
                market_end_time=state.market.end_time,
            )
            log.info(
                "%sTREND_FILL%s %s %s @ %.2f x%s ($%.2f)",
                C_GREEN, C_RESET,
                slug[:40], state.direction.value, state.price, filled_shares,
                state.price * filled_shares,
            )
            emit(EventType.ORDER_FILLED, {
                "slug": slug,
                "direction": state.direction.value,
                "side": "BUY",
                "price": float(state.price),
                "shares": float(filled_shares),
                "strategy": "trend_rider",
            }, slug)
        elif state.side == "SELL":
            self._positions.record_exit(slug, filled_shares, state.price)
            log.info(
                "%sTREND_EXIT%s %s @ %.2f x%s",
                C_RED, C_RESET,
                slug[:40], state.price, filled_shares,
            )
            emit(EventType.ORDER_FILLED, {
                "slug": slug,
                "direction": state.direction.value,
                "side": "SELL",
                "price": float(state.price),
                "shares": float(filled_shares),
                "strategy": "trend_rider",
            }, slug)

    def _log_summary(self, now: float) -> None:
        n_pos = self._positions.position_count
        exposure = self._positions.total_exposure()
        pnl = self._positions.session_realized_pnl
        avg_tick = self._tick_total_ms / max(self._tick_count, 1)
        log.info(
            "%sTR_SUMMARY%s positions=%d exposure=$%.2f realized=$%.2f "
            "ticks=%d avg=%.0fms max=%.0fms markets=%d",
            C_DIM, C_RESET,
            n_pos, exposure, pnl,
            self._tick_count, avg_tick, self._tick_max_ms,
            len(self._active_markets),
        )

    def get_state_snapshot(self) -> dict:
        """Return current state for dashboard API."""
        import time as _time
        positions = []
        for slug, pos in self._positions._positions.items():
            positions.append({
                "slug": slug,
                "direction": pos.direction.value,
                "shares": float(pos.shares),
                "entry_price": float(pos.entry_price),
                "cost": float(pos.cost),
                "seconds_held": _time.time() - pos.entered_at,
            })
        avg_tick = self._tick_total_ms / max(self._tick_count, 1)
        return {
            "positions": positions,
            "exposure": float(self._positions.total_exposure()),
            "pnl": {"realized": float(self._positions.session_realized_pnl)},
            "config": {
                "enabled": self._cfg.enabled,
                "dry_run": self._cfg.dry_run,
                "bankroll_usd": float(self._cfg.bankroll_usd),
            },
            "meta": {
                "tick_count": self._tick_count,
                "avg_tick_ms": round(avg_tick, 1),
                "position_count": self._positions.position_count,
            },
        }

    def get_active_slugs(self) -> set[str]:
        """Slugs with open positions or pending orders — for conflict avoidance."""
        slugs = self._positions.get_all_slugs()
        for token_id, order in self._order_mgr.get_open_orders().items():
            slugs.add(order.market.slug)
        return slugs
