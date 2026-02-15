"""Tests for anti-chase and stale fill protection (Fixes 1-3)."""

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

from complete_set.config import CompleteSetConfig
from complete_set.models import Direction, GabagoolMarket, MarketInventory, OrderState

ZERO = Decimal("0")


def _make_cfg(**overrides) -> CompleteSetConfig:
    defaults = dict(
        dry_run=True,
        min_merge_shares=Decimal("10"),
        min_merge_profit_usd=Decimal("0.02"),
        max_gas_price_gwei=200,
        no_new_orders_sec=90,
        min_edge=Decimal("0.01"),
        bankroll_usd=Decimal("500"),
        min_seconds_to_end=0,
        max_seconds_to_end=900,
        stop_hunt_enabled=True,
        sh_entry_start_sec=780,
        sh_entry_end_sec=90,
        swing_filter_enabled=False,
        max_hedge_chase_cents=0,
    )
    defaults.update(overrides)
    return CompleteSetConfig(**defaults)


def _make_engine(cfg=None):
    from complete_set.engine import Engine

    if cfg is None:
        cfg = _make_cfg()
    client = MagicMock()
    return Engine(client, cfg)


def _make_market(seconds_left=600):
    return GabagoolMarket(
        slug="btc-updown-15m-test",
        up_token_id="UP_TOKEN",
        down_token_id="DOWN_TOKEN",
        end_time=time.time() + seconds_left,
        market_type="updown-15m",
        condition_id="0xabc",
    )


# ── Fix 1: First-leg anti-chase ──


class TestFirstLegChaseCancel:
    """Fix 1: Upward reprice triggers CHASE_CANCEL, not repost."""

    def test_upward_reprice_triggers_chase_cancel(self):
        """When book moves up (against us), cancel order and set price cap."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug

        # Simulate existing order at 0.40
        existing_order = OrderState(
            order_id="dry-123",
            market=market,
            token_id="UP_TOKEN",
            direction=Direction.UP,
            price=Decimal("0.40"),
            size=Decimal("20"),
            placed_at=time.time(),
            side="BUY",
        )
        engine._order_mgr._orders["UP_TOKEN"] = existing_order

        cancelled = []
        original_cancel = engine._order_mgr.cancel_order
        def track_cancel(client, token_id, reason, on_fill=None):
            cancelled.append((token_id, reason))
            engine._order_mgr._orders.pop(token_id, None)
        engine._order_mgr.cancel_order = track_cancel

        placed = []
        original_place = engine._order_mgr.place_order
        def track_place(*a, **kw):
            placed.append(True)
            return True
        engine._order_mgr.place_order = track_place

        from complete_set.mean_reversion import MRDirection
        # Call _place_first_leg with a higher maker_price (0.45 > existing 0.40)
        engine._place_first_leg(
            MRDirection.BUY_UP, market, slug,
            up_ask=Decimal("0.47"), down_ask=Decimal("0.53"),
            up_bid=Decimal("0.44"), down_bid=Decimal("0.52"),
            max_first_leg=Decimal("0.495"),
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600, exposure=ZERO,
            reason="SH_ENTRY",
        )

        assert len(cancelled) == 1
        assert cancelled[0][1] == "CHASE_CANCEL"
        assert len(placed) == 0, "Should NOT repost at higher price"
        assert slug in engine._entry_price_caps
        assert engine._entry_price_caps[slug] == Decimal("0.40")

    def test_downward_reprice_still_works(self):
        """When book moves down (better price for us), reprice as before."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug

        existing_order = OrderState(
            order_id="dry-123",
            market=market,
            token_id="UP_TOKEN",
            direction=Direction.UP,
            price=Decimal("0.45"),
            size=Decimal("20"),
            placed_at=time.time(),
            side="BUY",
        )
        engine._order_mgr._orders["UP_TOKEN"] = existing_order

        cancelled = []
        def track_cancel(client, token_id, reason, on_fill=None):
            cancelled.append((token_id, reason))
            engine._order_mgr._orders.pop(token_id, None)
        engine._order_mgr.cancel_order = track_cancel

        placed = []
        def track_place(*a, **kw):
            placed.append(True)
            return True
        engine._order_mgr.place_order = track_place

        from complete_set.mean_reversion import MRDirection
        # maker_price will be min(bid+0.01, ask-0.01) = min(0.39+0.01, 0.42-0.01) = 0.40
        engine._place_first_leg(
            MRDirection.BUY_UP, market, slug,
            up_ask=Decimal("0.42"), down_ask=Decimal("0.58"),
            up_bid=Decimal("0.39"), down_bid=Decimal("0.57"),
            max_first_leg=Decimal("0.495"),
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600, exposure=ZERO,
            reason="SH_ENTRY",
        )

        assert len(cancelled) == 1
        assert cancelled[0][1] == "REPRICE"
        assert len(placed) == 1, "Should repost at lower price"
        assert slug not in engine._entry_price_caps

    def test_price_cap_blocks_reentry(self):
        """When price is above cap, entry is blocked."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug

        # Set a cap
        engine._entry_price_caps[slug] = Decimal("0.40")

        placed = []
        def track_place(*a, **kw):
            placed.append(True)
            return True
        engine._order_mgr.place_order = track_place

        from complete_set.mean_reversion import MRDirection
        # maker_price = min(0.44+0.01, 0.47-0.01) = 0.45 > cap 0.40
        engine._place_first_leg(
            MRDirection.BUY_UP, market, slug,
            up_ask=Decimal("0.47"), down_ask=Decimal("0.53"),
            up_bid=Decimal("0.44"), down_bid=Decimal("0.52"),
            max_first_leg=Decimal("0.495"),
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600, exposure=ZERO,
            reason="SH_ENTRY",
        )

        assert len(placed) == 0, "Entry should be blocked by cap"
        assert slug in engine._entry_price_caps, "Cap should remain"

    def test_price_cap_clears_when_price_drops(self):
        """When price drops back below cap, cap is cleared and entry allowed."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug

        engine._entry_price_caps[slug] = Decimal("0.42")

        placed = []
        def track_place(*a, **kw):
            placed.append(True)
            return True
        engine._order_mgr.place_order = track_place

        from complete_set.mean_reversion import MRDirection
        # maker_price = min(0.39+0.01, 0.42-0.01) = 0.40 <= cap 0.42
        engine._place_first_leg(
            MRDirection.BUY_UP, market, slug,
            up_ask=Decimal("0.42"), down_ask=Decimal("0.58"),
            up_bid=Decimal("0.39"), down_bid=Decimal("0.57"),
            max_first_leg=Decimal("0.495"),
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600, exposure=ZERO,
            reason="SH_ENTRY",
        )

        assert slug not in engine._entry_price_caps, "Cap should be cleared"
        assert len(placed) == 1, "Entry should proceed"

    def test_cap_cleared_on_fill(self):
        """Price cap is removed when a fill arrives."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug
        engine._active_markets = [market]

        engine._entry_price_caps[slug] = Decimal("0.40")

        fill_state = OrderState(
            order_id="dry-fill",
            market=market,
            token_id="UP_TOKEN",
            direction=Direction.UP,
            price=Decimal("0.39"),
            size=Decimal("20"),
            placed_at=time.time(),
            side="BUY",
        )

        engine._handle_fill(fill_state, Decimal("20"))

        assert slug not in engine._entry_price_caps

    def test_cap_cleaned_on_market_rotation(self):
        """Caps for rotated-out markets are cleaned up in _apply_discovery."""
        engine = _make_engine()
        old_market = _make_market()
        engine._active_markets = [old_market]
        engine._entry_price_caps[old_market.slug] = Decimal("0.40")
        engine._entry_price_caps["other-slug"] = Decimal("0.35")

        # Discover new markets that don't include old_market
        new_market = GabagoolMarket(
            slug="btc-updown-15m-new",
            up_token_id="NEW_UP",
            down_token_id="NEW_DOWN",
            end_time=time.time() + 600,
            market_type="updown-15m",
            condition_id="0xnew",
        )
        engine._apply_discovery([new_market], time.time())

        assert old_market.slug not in engine._entry_price_caps
        assert "other-slug" not in engine._entry_price_caps


# ── Fix 2: Cancel remaining orders after hedge completion ──


class TestHedgeCompleteCleanup:
    """Fix 2: Cancel remaining orders when hedge is complete."""

    def test_orders_cancelled_after_hedge_complete(self):
        """After HEDGE_COMPLETE, remaining orders for the market are cancelled."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug
        engine._active_markets = [market]

        # Pre-load inventory so hedge completes on this fill
        engine._inventory._inventory_by_market[slug] = MarketInventory(
            up_shares=Decimal("15"),
            up_cost=Decimal("6.00"),
            filled_up_shares=Decimal("15"),
            down_shares=Decimal("5"),
            down_cost=Decimal("2.50"),
            filled_down_shares=Decimal("5"),
        )

        # Place a lingering first-leg order on UP_TOKEN
        engine._order_mgr._orders["UP_TOKEN"] = OrderState(
            order_id="dry-lingering",
            market=market,
            token_id="UP_TOKEN",
            direction=Direction.UP,
            price=Decimal("0.40"),
            size=Decimal("20"),
            placed_at=time.time(),
            side="BUY",
        )

        cancelled_reasons = []
        original_cancel = engine._order_mgr.cancel_order
        def track_cancel(client, token_id, reason, on_fill=None):
            cancelled_reasons.append((token_id, reason))
            engine._order_mgr._orders.pop(token_id, None)
        engine._order_mgr.cancel_order = track_cancel

        # Fill DOWN enough to make hedged >= min_merge_shares (10)
        fill_state = OrderState(
            order_id="dry-hedge-fill",
            market=market,
            token_id="DOWN_TOKEN",
            direction=Direction.DOWN,
            price=Decimal("0.50"),
            size=Decimal("10"),
            placed_at=time.time(),
            side="BUY",
        )

        engine._handle_fill(fill_state, Decimal("10"))

        assert slug in engine._completed_markets
        # Should have cancelled UP_TOKEN and DOWN_TOKEN via cancel_market_orders
        cleanup_cancels = [r for r in cancelled_reasons if r[1] == "HEDGE_COMPLETE_CLEANUP"]
        assert len(cleanup_cancels) >= 1, f"Expected HEDGE_COMPLETE_CLEANUP cancels, got {cancelled_reasons}"

    def test_no_crash_when_no_remaining_orders(self):
        """HEDGE_COMPLETE_CLEANUP doesn't crash when there are no orders to cancel."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug
        engine._active_markets = [market]

        engine._inventory._inventory_by_market[slug] = MarketInventory(
            up_shares=Decimal("10"),
            up_cost=Decimal("4.00"),
            filled_up_shares=Decimal("10"),
        )

        fill_state = OrderState(
            order_id="dry-hedge",
            market=market,
            token_id="DOWN_TOKEN",
            direction=Direction.DOWN,
            price=Decimal("0.50"),
            size=Decimal("10"),
            placed_at=time.time(),
            side="BUY",
        )

        # Should not raise
        engine._handle_fill(fill_state, Decimal("10"))
        assert slug in engine._completed_markets

    def test_dry_merge_also_cancels(self):
        """Dry-run merge path also cancels remaining orders."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug
        engine._active_markets = [market]

        engine._inventory._inventory_by_market[slug] = MarketInventory(
            up_shares=Decimal("15"),
            up_cost=Decimal("6.00"),
            down_shares=Decimal("15"),
            down_cost=Decimal("7.00"),
            filled_up_shares=Decimal("15"),
            filled_down_shares=Decimal("15"),
        )

        # Place a lingering order
        engine._order_mgr._orders["UP_TOKEN"] = OrderState(
            order_id="dry-lingering",
            market=market,
            token_id="UP_TOKEN",
            direction=Direction.UP,
            price=Decimal("0.40"),
            size=Decimal("20"),
            placed_at=time.time(),
            side="BUY",
        )

        cancelled_reasons = []
        def track_cancel(client, token_id, reason, on_fill=None):
            cancelled_reasons.append((token_id, reason))
            engine._order_mgr._orders.pop(token_id, None)
        engine._order_mgr.cancel_order = track_cancel

        engine._check_settlements(time.time())

        cleanup_cancels = [r for r in cancelled_reasons if r[1] == "HEDGE_COMPLETE_CLEANUP"]
        assert len(cleanup_cancels) >= 1


# ── Fix 3: Hedge freeze ──


class TestHedgeFreeze:
    """Fix 3: Hedge order frozen at original price when book moves up."""

    def _setup_hedge_scenario(self, max_hedge_chase_cents=0):
        cfg = _make_cfg(
            max_hedge_chase_cents=max_hedge_chase_cents,
            hedge_edge_buffer=Decimal("0.005"),
        )
        engine = _make_engine(cfg)
        market = _make_market()
        slug = market.slug
        engine._active_markets = [market]

        inv = MarketInventory(
            up_shares=Decimal("20"),
            up_cost=Decimal("8.00"),
            filled_up_shares=Decimal("20"),
        )
        engine._inventory._inventory_by_market[slug] = inv

        return engine, market, slug, inv

    def test_hedge_upward_blocked_default(self):
        """max_hedge_chase_cents=0: any upward reprice is frozen."""
        engine, market, slug, inv = self._setup_hedge_scenario(max_hedge_chase_cents=0)

        # Existing hedge order at 0.50
        engine._order_mgr._orders["DOWN_TOKEN"] = OrderState(
            order_id="dry-hedge",
            market=market,
            token_id="DOWN_TOKEN",
            direction=Direction.DOWN,
            price=Decimal("0.50"),
            size=Decimal("20"),
            placed_at=time.time(),
            side="BUY",
        )

        cancelled = []
        def track_cancel(client, token_id, reason, on_fill=None):
            cancelled.append(reason)
            engine._order_mgr._orders.pop(token_id, None)
        engine._order_mgr.cancel_order = track_cancel

        # Book moves up: bid=0.54, ask=0.57 → maker_price = 0.55 > existing 0.50
        engine._place_hedge_leg(
            market, slug, inv,
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600, exposure=ZERO,
            first_side="UP", hedge_direction=Direction.DOWN,
            first_vwap=Decimal("0.40"), first_filled=Decimal("20"),
            bootstrapped=False,
            hedge_token="DOWN_TOKEN",
            hedge_bid=Decimal("0.54"), hedge_ask=Decimal("0.57"),
        )

        assert len(cancelled) == 0, "Should NOT cancel — freeze at original price"
        assert "DOWN_TOKEN" in engine._order_mgr._orders, "Order should remain at original price"

    def test_hedge_downward_reprice_allowed(self):
        """Downward reprice (better price for hedge) always allowed."""
        engine, market, slug, inv = self._setup_hedge_scenario(max_hedge_chase_cents=0)

        engine._order_mgr._orders["DOWN_TOKEN"] = OrderState(
            order_id="dry-hedge",
            market=market,
            token_id="DOWN_TOKEN",
            direction=Direction.DOWN,
            price=Decimal("0.50"),
            size=Decimal("20"),
            placed_at=time.time(),
            side="BUY",
        )

        cancelled = []
        def track_cancel(client, token_id, reason, on_fill=None):
            cancelled.append(reason)
            engine._order_mgr._orders.pop(token_id, None)
        engine._order_mgr.cancel_order = track_cancel

        placed = []
        def track_place(*a, **kw):
            placed.append(True)
            return True
        engine._order_mgr.place_order = track_place

        # Book moves down: bid=0.44, ask=0.47 → maker_price = 0.45 < existing 0.50
        engine._place_hedge_leg(
            market, slug, inv,
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600, exposure=ZERO,
            first_side="UP", hedge_direction=Direction.DOWN,
            first_vwap=Decimal("0.40"), first_filled=Decimal("20"),
            bootstrapped=False,
            hedge_token="DOWN_TOKEN",
            hedge_bid=Decimal("0.44"), hedge_ask=Decimal("0.47"),
        )

        assert len(cancelled) == 1
        assert cancelled[0] == "REPRICE"
        assert len(placed) == 1

    def test_hedge_small_upward_within_tolerance(self):
        """max_hedge_chase_cents=3: 2c upward is within tolerance, allow reprice."""
        engine, market, slug, inv = self._setup_hedge_scenario(max_hedge_chase_cents=3)

        engine._order_mgr._orders["DOWN_TOKEN"] = OrderState(
            order_id="dry-hedge",
            market=market,
            token_id="DOWN_TOKEN",
            direction=Direction.DOWN,
            price=Decimal("0.50"),
            size=Decimal("20"),
            placed_at=time.time(),
            side="BUY",
        )

        cancelled = []
        def track_cancel(client, token_id, reason, on_fill=None):
            cancelled.append(reason)
            engine._order_mgr._orders.pop(token_id, None)
        engine._order_mgr.cancel_order = track_cancel

        placed = []
        def track_place(*a, **kw):
            placed.append(True)
            return True
        engine._order_mgr.place_order = track_place

        # Book moves up 2c: bid=0.51, ask=0.54 → maker_price = 0.52, within 3c tolerance
        engine._place_hedge_leg(
            market, slug, inv,
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600, exposure=ZERO,
            first_side="UP", hedge_direction=Direction.DOWN,
            first_vwap=Decimal("0.40"), first_filled=Decimal("20"),
            bootstrapped=False,
            hedge_token="DOWN_TOKEN",
            hedge_bid=Decimal("0.51"), hedge_ask=Decimal("0.54"),
        )

        assert len(cancelled) == 1, "Within tolerance, should allow reprice"
        assert len(placed) == 1

    def test_hedge_large_upward_beyond_tolerance(self):
        """max_hedge_chase_cents=3: 5c upward exceeds tolerance, freeze."""
        engine, market, slug, inv = self._setup_hedge_scenario(max_hedge_chase_cents=3)

        engine._order_mgr._orders["DOWN_TOKEN"] = OrderState(
            order_id="dry-hedge",
            market=market,
            token_id="DOWN_TOKEN",
            direction=Direction.DOWN,
            price=Decimal("0.50"),
            size=Decimal("20"),
            placed_at=time.time(),
            side="BUY",
        )

        cancelled = []
        def track_cancel(client, token_id, reason, on_fill=None):
            cancelled.append(reason)
            engine._order_mgr._orders.pop(token_id, None)
        engine._order_mgr.cancel_order = track_cancel

        # Book moves up 5c: bid=0.54, ask=0.57 → maker_price = 0.55 > 0.50+0.03
        engine._place_hedge_leg(
            market, slug, inv,
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600, exposure=ZERO,
            first_side="UP", hedge_direction=Direction.DOWN,
            first_vwap=Decimal("0.40"), first_filled=Decimal("20"),
            bootstrapped=False,
            hedge_token="DOWN_TOKEN",
            hedge_bid=Decimal("0.54"), hedge_ask=Decimal("0.57"),
        )

        assert len(cancelled) == 0, "Beyond tolerance, should freeze"
        assert "DOWN_TOKEN" in engine._order_mgr._orders


# ── Fix 4: Partial hedge detection ──


class TestHedgePartial:
    """Partial hedge fills should NOT mark market complete."""

    def test_partial_fill_does_not_complete(self):
        """Fill 5 DOWN on top of 20 UP → hedged=5, imbalance=15. Must NOT mark complete."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug
        engine._active_markets = [market]

        # 20 UP shares filled, 0 DOWN
        engine._inventory._inventory_by_market[slug] = MarketInventory(
            up_shares=Decimal("20"),
            up_cost=Decimal("8.00"),
            filled_up_shares=Decimal("20"),
        )

        fill_state = OrderState(
            order_id="dry-hedge-partial",
            market=market,
            token_id="DOWN_TOKEN",
            direction=Direction.DOWN,
            price=Decimal("0.50"),
            size=Decimal("5"),
            placed_at=time.time(),
            side="BUY",
        )

        engine._handle_fill(fill_state, Decimal("5"))

        # hedged=5 >= min_merge_shares(10)? No. But even if hedged were 10,
        # imbalance=15 >= min_merge_shares → should NOT mark complete
        assert slug not in engine._completed_markets, "Partial hedge must not mark complete"

    def test_partial_fill_above_min_merge_not_complete(self):
        """Fill 15 DOWN on top of 30 UP → hedged=15 >= 10, but imbalance=15 >= 10. NOT complete."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug
        engine._active_markets = [market]

        engine._inventory._inventory_by_market[slug] = MarketInventory(
            up_shares=Decimal("30"),
            up_cost=Decimal("12.00"),
            filled_up_shares=Decimal("30"),
        )

        cancelled = []
        def track_cancel(client, token_id, reason, on_fill=None):
            cancelled.append(reason)
            engine._order_mgr._orders.pop(token_id, None)
        engine._order_mgr.cancel_order = track_cancel

        fill_state = OrderState(
            order_id="dry-partial",
            market=market,
            token_id="DOWN_TOKEN",
            direction=Direction.DOWN,
            price=Decimal("0.50"),
            size=Decimal("15"),
            placed_at=time.time(),
            side="BUY",
        )

        engine._handle_fill(fill_state, Decimal("15"))

        # hedged=15 >= 10 but imbalance=15 >= 10 → HEDGE_PARTIAL, not complete
        assert slug not in engine._completed_markets, "Should log HEDGE_PARTIAL, not complete"
        assert "HEDGE_COMPLETE_CLEANUP" not in cancelled, "Should NOT cancel orders on partial"

    def test_full_fill_marks_complete(self):
        """Fill 20 DOWN on top of 20 UP → hedged=20, imbalance=0. SHOULD mark complete."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug
        engine._active_markets = [market]

        engine._inventory._inventory_by_market[slug] = MarketInventory(
            up_shares=Decimal("20"),
            up_cost=Decimal("8.00"),
            filled_up_shares=Decimal("20"),
        )

        fill_state = OrderState(
            order_id="dry-full",
            market=market,
            token_id="DOWN_TOKEN",
            direction=Direction.DOWN,
            price=Decimal("0.50"),
            size=Decimal("20"),
            placed_at=time.time(),
            side="BUY",
        )

        engine._handle_fill(fill_state, Decimal("20"))

        assert slug in engine._completed_markets, "Fully hedged should mark complete"


# ── Fix 5: Entry price bounds ──


class TestEntryPriceBounds:
    """Entry price guards in _place_first_leg."""

    def test_rejects_above_max_entry(self):
        """maker=0.48 > max_entry=0.45 → skip."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug

        placed = []
        def track_place(*a, **kw):
            placed.append(True)
        engine._order_mgr.place_order = track_place

        from complete_set.mean_reversion import MRDirection
        # bid=0.47, ask=0.50 → maker=min(0.48, 0.49) = 0.48 > max_entry 0.45
        engine._place_first_leg(
            MRDirection.BUY_UP, market, slug,
            up_ask=Decimal("0.50"), down_ask=Decimal("0.50"),
            up_bid=Decimal("0.47"), down_bid=Decimal("0.49"),
            max_first_leg=Decimal("0.495"),
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600, exposure=ZERO,
            reason="SH_ENTRY",
        )

        assert len(placed) == 0, "Should reject — above max_entry_price"

    def test_rejects_below_min_entry(self):
        """maker=0.06 < min_entry=0.10 → skip."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug

        placed = []
        def track_place(*a, **kw):
            placed.append(True)
        engine._order_mgr.place_order = track_place

        from complete_set.mean_reversion import MRDirection
        # bid=0.05, ask=0.08 → maker=min(0.06, 0.07) = 0.06 < min_entry 0.10
        engine._place_first_leg(
            MRDirection.BUY_UP, market, slug,
            up_ask=Decimal("0.08"), down_ask=Decimal("0.92"),
            up_bid=Decimal("0.05"), down_bid=Decimal("0.91"),
            max_first_leg=Decimal("0.495"),
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600, exposure=ZERO,
            reason="SH_ENTRY",
        )

        assert len(placed) == 0, "Should reject — below min_entry_price"

    def test_accepts_within_bounds(self):
        """maker=0.40 within [0.10, 0.45] → proceed."""
        engine = _make_engine()
        market = _make_market()
        slug = market.slug

        placed = []
        def track_place(*a, **kw):
            placed.append(True)
        engine._order_mgr.place_order = track_place

        from complete_set.mean_reversion import MRDirection
        # bid=0.39, ask=0.42 → maker=min(0.40, 0.41) = 0.40
        engine._place_first_leg(
            MRDirection.BUY_UP, market, slug,
            up_ask=Decimal("0.42"), down_ask=Decimal("0.58"),
            up_bid=Decimal("0.39"), down_bid=Decimal("0.57"),
            max_first_leg=Decimal("0.495"),
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600, exposure=ZERO,
            reason="SH_ENTRY",
        )

        assert len(placed) == 1, "Should accept — within price bounds"
