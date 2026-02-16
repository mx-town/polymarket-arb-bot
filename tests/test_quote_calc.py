"""Tests for quote_calc — exposure calculations."""

import time
from decimal import Decimal

from rebate_maker.models import Direction, GabagoolMarket, MarketInventory, OrderState
from rebate_maker.quote_calc import (
    calculate_exposure,
    calculate_exposure_breakdown,
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


class TestExposure:
    def test_orders_only(self):
        orders = {"111": _order(price="0.45", size="10")}
        exposure = calculate_exposure(orders, {})
        assert exposure == Decimal("4.50")

    def test_unhedged_uses_vwap(self):
        """Unhedged exposure reserves for both legs: first_leg_cost + hedge_reserve."""
        inv = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=ZERO,
            up_cost=Decimal("4.00"),  # VWAP = 0.40
        )
        exposure = calculate_exposure({}, {"test": inv})
        # 10 shares unhedged: first_leg_cost=10*0.40=4.00, hedge_reserve=10*(1-0.40)=6.00
        # total = 4.00 + 6.00 = 10.00
        assert exposure == Decimal("10.00")

    def test_unhedged_fallback_050(self):
        """Falls back to 0.50 when no VWAP available, still reserves both legs."""
        inv = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=ZERO,
            up_cost=ZERO,  # no cost info → vwap is None
        )
        # up_vwap = 0/10 = 0 (falsy), falls back to 0.50
        # first_leg_cost=10*0.50=5.00, hedge_reserve=10*(1-0.50)=5.00
        # total = 5.00 + 5.00 = 10.00
        exposure = calculate_exposure({}, {"test": inv})
        assert exposure == Decimal("10.00")

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
