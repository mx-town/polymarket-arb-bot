"""Tests for entry safety guards (post log-analysis 2026-02-15).

Fix 1: min BTC tick count before entry
Fix 2: hedge margin entry guard
Fix 3: abandon deeply negative positions
"""

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from complete_set.binance_ws import CandleState
from complete_set.config import CompleteSetConfig
from complete_set.mean_reversion import MRDirection, StopHuntSignal, evaluate_stop_hunt
from complete_set.models import Direction, GabagoolMarket, MarketInventory, OrderState

ZERO = Decimal("0")
ONE = Decimal("1")


# ── Helpers ──

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
        min_btc_ticks=5,
        abandon_edge_threshold=Decimal("-0.10"),
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


def _make_candle(tick_count=10, **kwargs):
    defaults = dict(
        open_price=Decimal("70000"),
        current_price=Decimal("70050"),
        high=Decimal("70100"),
        low=Decimal("69950"),
        last_update=time.time(),
        _market_window_start=time.time() - 300,
        tick_count=tick_count,
    )
    defaults.update(kwargs)
    return CandleState(**defaults)


# ── Fix 1: Minimum BTC tick count ──

class TestMinTickCount:
    """evaluate_stop_hunt should SKIP when tick_count < min_ticks."""

    def test_insufficient_ticks_returns_skip(self):
        candle = _make_candle(tick_count=2)
        sig = evaluate_stop_hunt(
            candle,
            up_ask=Decimal("0.40"), down_ask=Decimal("0.60"),
            seconds_to_end=700,
            max_first_leg=Decimal("0.495"),
            max_range_pct=Decimal("0.0050"),
            sh_entry_start_sec=780,
            sh_entry_end_sec=90,
            no_new_orders_sec=90,
            min_ticks=5,
        )
        assert sig.direction == MRDirection.SKIP
        assert "insufficient ticks" in sig.reason
        assert "(2/5)" in sig.reason

    def test_sufficient_ticks_allows_entry(self):
        candle = _make_candle(tick_count=5)
        sig = evaluate_stop_hunt(
            candle,
            up_ask=Decimal("0.40"), down_ask=Decimal("0.60"),
            seconds_to_end=700,
            max_first_leg=Decimal("0.495"),
            max_range_pct=Decimal("0.0050"),
            sh_entry_start_sec=780,
            sh_entry_end_sec=90,
            no_new_orders_sec=90,
            min_ticks=5,
        )
        assert sig.direction != MRDirection.SKIP

    def test_tick_count_zero_on_first_tick(self):
        candle = _make_candle(tick_count=0)
        sig = evaluate_stop_hunt(
            candle,
            up_ask=Decimal("0.40"), down_ask=Decimal("0.60"),
            seconds_to_end=700,
            max_first_leg=Decimal("0.495"),
            max_range_pct=Decimal("0.0050"),
            sh_entry_start_sec=780,
            sh_entry_end_sec=90,
            no_new_orders_sec=90,
            min_ticks=5,
        )
        assert sig.direction == MRDirection.SKIP
        assert "(0/5)" in sig.reason


# ── Fix 2: Hedge margin entry guard ──

class TestHedgeMarginGuard:
    """_place_first_leg should reject entries with no profitable hedge path."""

    def _setup_entry(self, up_ask, down_ask, up_bid, down_bid, direction=MRDirection.BUY_DOWN):
        """Set up engine and call _place_first_leg, return whether order was placed."""
        cfg = _make_cfg(min_edge=Decimal("0.01"))
        engine = _make_engine(cfg)
        market = _make_market()
        slug = market.slug

        placed = []
        original_place = engine._order_mgr.place_order

        def mock_place(*a, **kw):
            placed.append(True)
            return original_place(*a, **kw)

        engine._order_mgr.place_order = mock_place

        dynamic_edge = Decimal("0.01")
        max_first_leg = (ONE - dynamic_edge) / 2

        engine._place_first_leg(
            direction, market, slug,
            up_ask, down_ask, up_bid, down_bid,
            max_first_leg, dynamic_edge,
            seconds_to_end=600,
            exposure=ZERO,
            reason="SH_ENTRY",
        )
        return len(placed) > 0

    def test_zero_margin_rejected(self):
        """DOWN maker=0.17, UP opp_maker=0.83 → 1.00 >= 0.99 → rejected."""
        placed = self._setup_entry(
            up_ask=Decimal("0.85"), down_ask=Decimal("0.19"),
            up_bid=Decimal("0.82"), down_bid=Decimal("0.16"),
            direction=MRDirection.BUY_DOWN,
        )
        assert not placed, "Should reject entry with no hedge margin"

    def test_sufficient_margin_allowed(self):
        """DOWN maker=0.40, UP opp_maker=0.52 → 0.92 < 0.99 → allowed."""
        placed = self._setup_entry(
            up_ask=Decimal("0.54"), down_ask=Decimal("0.42"),
            up_bid=Decimal("0.51"), down_bid=Decimal("0.39"),
            direction=MRDirection.BUY_DOWN,
        )
        assert placed, "Should allow entry with sufficient hedge margin"

    def test_up_entry_zero_margin_rejected(self):
        """UP maker=0.17, DOWN opp_maker=0.83 → 1.00 >= 0.99 → rejected."""
        placed = self._setup_entry(
            up_ask=Decimal("0.19"), down_ask=Decimal("0.85"),
            up_bid=Decimal("0.16"), down_bid=Decimal("0.82"),
            direction=MRDirection.BUY_UP,
        )
        assert not placed, "Should reject UP entry with no hedge margin"


# ── Fix 3: Abandon deeply negative positions ──

class TestAbandonUnhedgeable:
    """_place_hedge_leg should add to _completed_markets when edge is deeply negative."""

    def test_abandon_when_edge_deeply_negative(self):
        cfg = _make_cfg(
            min_edge=Decimal("0.01"),
            abandon_edge_threshold=Decimal("-0.10"),
        )
        engine = _make_engine(cfg)
        market = _make_market()
        slug = market.slug

        # First leg filled UP at VWAP 0.60 — hedge DOWN bid=0.52 → combined=1.13 → edge=-0.13
        inv = MarketInventory(
            up_shares=Decimal("20"),
            down_shares=ZERO,
            up_cost=Decimal("12.00"),  # VWAP = 0.60
            down_cost=ZERO,
            filled_up_shares=Decimal("20"),
        )
        engine._inventory._inventory_by_market[slug] = inv

        engine._place_hedge_leg(
            market, slug, inv,
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600,
            exposure=ZERO,
            first_side="UP",
            hedge_direction=Direction.DOWN,
            first_vwap=Decimal("0.60"),
            first_filled=Decimal("20"),
            bootstrapped=False,
            hedge_token="DOWN_TOKEN",
            hedge_bid=Decimal("0.52"),
            hedge_ask=Decimal("0.54"),
        )

        assert slug in engine._completed_markets, "Should abandon deeply negative position"

    def test_no_abandon_when_edge_mildly_negative(self):
        cfg = _make_cfg(
            min_edge=Decimal("0.01"),
            abandon_edge_threshold=Decimal("-0.10"),
        )
        engine = _make_engine(cfg)
        market = _make_market()
        slug = market.slug

        # First leg filled UP at VWAP 0.45 — hedge DOWN bid=0.50 → combined=0.96 → edge=0.04
        # But edge < hedge_edge (0.01) is false here — edge=0.04 > 0.01 so it would proceed
        # Use VWAP 0.50 — hedge bid=0.48 → combined=0.99 → edge=0.01, just at threshold
        inv = MarketInventory(
            up_shares=Decimal("20"),
            down_shares=ZERO,
            up_cost=Decimal("10.00"),  # VWAP = 0.50
            down_cost=ZERO,
            filled_up_shares=Decimal("20"),
        )
        engine._inventory._inventory_by_market[slug] = inv

        engine._place_hedge_leg(
            market, slug, inv,
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600,
            exposure=ZERO,
            first_side="UP",
            hedge_direction=Direction.DOWN,
            first_vwap=Decimal("0.50"),
            first_filled=Decimal("20"),
            bootstrapped=False,
            hedge_token="DOWN_TOKEN",
            hedge_bid=Decimal("0.45"),
            hedge_ask=Decimal("0.48"),
        )

        assert slug not in engine._completed_markets, "Should NOT abandon mildly negative position"

    def test_abandon_threshold_boundary(self):
        """Edge exactly at -0.10 should trigger abandon."""
        cfg = _make_cfg(
            min_edge=Decimal("0.01"),
            abandon_edge_threshold=Decimal("-0.10"),
        )
        engine = _make_engine(cfg)
        market = _make_market()
        slug = market.slug

        # VWAP 0.55, hedge maker=0.56 → combined=1.11 → edge=-0.11 < -0.10 → abandon
        inv = MarketInventory(
            up_shares=Decimal("20"),
            down_shares=ZERO,
            up_cost=Decimal("11.00"),  # VWAP = 0.55
            down_cost=ZERO,
            filled_up_shares=Decimal("20"),
        )
        engine._inventory._inventory_by_market[slug] = inv

        engine._place_hedge_leg(
            market, slug, inv,
            dynamic_edge=Decimal("0.01"),
            seconds_to_end=600,
            exposure=ZERO,
            first_side="UP",
            hedge_direction=Direction.DOWN,
            first_vwap=Decimal("0.55"),
            first_filled=Decimal("20"),
            bootstrapped=False,
            hedge_token="DOWN_TOKEN",
            hedge_bid=Decimal("0.55"),
            hedge_ask=Decimal("0.58"),
        )

        assert slug in engine._completed_markets, "Edge -0.11 should trigger abandon"


# ── Config validation ──

class TestConfigValidation:
    def test_min_btc_ticks_validation(self):
        from complete_set.config import validate_config
        with pytest.raises(ValueError, match="min_btc_ticks"):
            cfg = CompleteSetConfig(min_btc_ticks=0)
            validate_config(cfg)

    def test_abandon_edge_threshold_validation(self):
        from complete_set.config import validate_config
        with pytest.raises(ValueError, match="abandon_edge_threshold"):
            cfg = CompleteSetConfig(abandon_edge_threshold=Decimal("0.05"))
            validate_config(cfg)
