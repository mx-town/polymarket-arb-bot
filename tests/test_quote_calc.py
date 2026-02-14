"""Tests for quote_calc — dynamic edge, exposure, FOK sizing."""

import time
from decimal import Decimal

from complete_set.models import Direction, GabagoolMarket, MarketInventory, OrderState
from complete_set.quote_calc import (
    calculate_dynamic_edge,
    calculate_exposure,
    calculate_exposure_breakdown,
    has_minimum_edge,
)

ZERO = Decimal("0")
ONE = Decimal("1")


def _market():
    return GabagoolMarket(
        slug="btc-updown-15m-test",
        up_token_id="111",
        down_token_id="222",
        end_time=time.time() + 600,
        market_type="updown-15m",
    )


def _order(price="0.45", size="10", reserved="0"):
    return OrderState(
        order_id="o1",
        market=_market(),
        token_id="111",
        direction=Direction.UP,
        price=Decimal(price),
        size=Decimal(size),
        placed_at=time.time(),
        reserved_hedge_notional=Decimal(reserved),
    )


class TestDynamicEdge:
    def test_tight_spread(self):
        """Spread < 6% returns base edge."""
        result = calculate_dynamic_edge(Decimal("0.04"), Decimal("0.01"))
        assert result == Decimal("0.01")

    def test_moderate_spread(self):
        """Spread 6-10% returns 1.5x edge."""
        result = calculate_dynamic_edge(Decimal("0.08"), Decimal("0.01"))
        assert result == Decimal("0.015")

    def test_wide_spread(self):
        """Spread >= 10% returns 2x edge."""
        result = calculate_dynamic_edge(Decimal("0.12"), Decimal("0.01"))
        assert result == Decimal("0.02")

    def test_boundary_6pct(self):
        """Exactly 6% triggers moderate tier."""
        result = calculate_dynamic_edge(Decimal("0.06"), Decimal("0.01"))
        assert result == Decimal("0.015")

    def test_boundary_10pct(self):
        """Exactly 10% triggers wide tier."""
        result = calculate_dynamic_edge(Decimal("0.10"), Decimal("0.01"))
        assert result == Decimal("0.02")


class TestHasMinimumEdge:
    def test_above_edge(self):
        assert has_minimum_edge(Decimal("0.44"), Decimal("0.44"), Decimal("0.01")) is True

    def test_exactly_at_edge(self):
        # 1 - (0.495 + 0.495) = 0.01
        assert has_minimum_edge(Decimal("0.495"), Decimal("0.495"), Decimal("0.01")) is True

    def test_below_edge(self):
        assert has_minimum_edge(Decimal("0.50"), Decimal("0.50"), Decimal("0.01")) is False


class TestExposure:
    def test_orders_only(self):
        orders = {"111": _order(price="0.45", size="10")}
        exposure = calculate_exposure(orders, {})
        assert exposure == Decimal("4.50")

    def test_unhedged_uses_vwap(self):
        """Unhedged exposure should use actual VWAP, not hardcoded 0.50."""
        inv = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=ZERO,
            up_cost=Decimal("4.00"),  # VWAP = 0.40
        )
        exposure = calculate_exposure({}, {"test": inv})
        # 10 shares unhedged * VWAP 0.40 = 4.00
        assert exposure == Decimal("10") * Decimal("0.40")

    def test_unhedged_fallback_050(self):
        """Falls back to 0.50 when no VWAP available."""
        inv = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=ZERO,
            up_cost=ZERO,  # no cost info → vwap is None
        )
        # up_shares=10, down_shares=0, imbalance=10 (positive)
        # up_vwap is None (shares > 0 but cost is 0, so 0/10 = 0... wait
        # Actually up_cost=0, up_shares=10, so up_vwap = 0/10 = 0
        # The code says: vwap = inv.up_vwap or Decimal("0.50")
        # 0 is falsy, so it falls back to 0.50
        exposure = calculate_exposure({}, {"test": inv})
        assert exposure == Decimal("5.00")

    def test_hedged_locked(self):
        inv = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=Decimal("10"),
            up_cost=Decimal("4.50"),
            down_cost=Decimal("4.50"),
        )
        exposure = calculate_exposure({}, {"test": inv})
        # hedged=10, VWAP_up=0.45, VWAP_down=0.45
        # hedged_locked = 10 * (0.45 + 0.45) = 9.00
        assert exposure == Decimal("9.00")

    def test_mixed(self):
        orders = {"111": _order(price="0.45", size="10")}
        inv = MarketInventory(
            up_shares=Decimal("5"),
            down_shares=Decimal("5"),
            up_cost=Decimal("2.25"),
            down_cost=Decimal("2.25"),
        )
        exposure = calculate_exposure(orders, {"test": inv})
        # orders: 4.50, hedged: 5 * (0.45 + 0.45) = 4.50
        assert exposure == Decimal("9.00")

    def test_reserved_hedge_notional(self):
        """Reserved hedge notional should be included in exposure."""
        orders = {"111": _order(price="0.45", size="10", reserved="4.50")}
        exposure = calculate_exposure(orders, {})
        # order notional 4.50 + reserved 4.50 = 9.00
        assert exposure == Decimal("9.00")

    def test_reserved_hedge_in_breakdown(self):
        """Breakdown total should include reserved hedge."""
        orders = {"111": _order(price="0.45", size="10", reserved="3.00")}
        ord_not, unhedged, hedged, total = calculate_exposure_breakdown(orders, {})
        assert ord_not == Decimal("4.50")
        assert total == Decimal("7.50")  # 4.50 + 3.00
