"""Bankroll scenario tests using real Polymarket 15m market data.

Real market characteristics (BTC 15m up/down):
- Asks sum to 0.99-1.02 (MMs take 1-2%)
- Bid-ask spread: 1-3 cents per side
- VWAPs at fill: 0.47-0.53 (bid+1c for maker orders)
- Position sizes: 50-200 shares
- Edge at maker: 0-2 cents
- Hedge only works when combined VWAP + maker < 1 - min_edge

Run with: uv run pytest tests/test_bankroll_scenarios.py -v -s
"""

from decimal import Decimal

import pytest

from rebate_maker.models import MarketInventory, OrderState, Direction
from rebate_maker.quote_calc import (
    calculate_exposure,
    calculate_exposure_breakdown,
    total_bankroll_cap,
)

ZERO = Decimal("0")
ONE = Decimal("1")


# ---------------------------------------------------------------------------
# Test 1: Exposure — does it correctly reserve for hedge?
# ---------------------------------------------------------------------------

class TestExposureRealistic:
    """Verify exposure calculation with real position structures."""

    def test_single_unhedged_up_position(self):
        """100 UP shares at VWAP 0.48 → should reserve ~$100 (not just $48)."""
        inv = MarketInventory(
            up_shares=Decimal("100"),
            up_cost=Decimal("48.00"),  # VWAP = 0.48
        )
        exposure = calculate_exposure({}, {"btc-1": inv})
        # first_leg_cost = 100 * 0.48 = $48
        # hedge_reserve = 100 * (1 - 0.48) = $52
        # total = $100 (reserves for both legs)
        assert exposure == Decimal("100.00"), f"Should reserve $100, got ${exposure}"

    def test_single_unhedged_down_position(self):
        """80 DOWN shares at VWAP 0.53 → should reserve ~$80."""
        inv = MarketInventory(
            down_shares=Decimal("80"),
            down_cost=Decimal("42.40"),  # VWAP = 0.53
        )
        exposure = calculate_exposure({}, {"btc-2": inv})
        # first_leg_cost = 80 * 0.53 = $42.40
        # hedge_reserve = 80 * (1 - 0.53) = $37.60
        # total = $80.00
        assert exposure == Decimal("80.00"), f"Should reserve $80, got ${exposure}"

    def test_hedged_position_uses_actual_cost(self):
        """100 hedged pairs at VWAP 0.48+0.51 → locked at actual cost, not $1/share."""
        inv = MarketInventory(
            up_shares=Decimal("100"),
            down_shares=Decimal("100"),
            up_cost=Decimal("48.00"),   # VWAP 0.48
            down_cost=Decimal("51.00"),  # VWAP 0.51
        )
        exposure = calculate_exposure({}, {"btc-3": inv})
        # No imbalance → no unhedged exposure
        # hedged_locked = 100 * (0.48 + 0.51) = $99
        assert exposure == Decimal("99.00"), f"Hedged cost should be $99, got ${exposure}"

    def test_partial_hedge_mixed(self):
        """150 UP, 100 DOWN → 100 hedged + 50 unhedged UP."""
        inv = MarketInventory(
            up_shares=Decimal("150"),
            down_shares=Decimal("100"),
            up_cost=Decimal("72.00"),   # VWAP 0.48
            down_cost=Decimal("51.00"),  # VWAP 0.51
        )
        exposure = calculate_exposure({}, {"btc-4": inv})
        # imbalance = 50 UP, vwap = 0.48
        # unhedged = 50 * 0.48 + 50 * (1-0.48) = 50 * 1.0 = $50
        # hedged_locked = 100 * (0.48 + 0.51) = $99
        # total = $149
        assert exposure == Decimal("149.00"), f"Expected $149, got ${exposure}"

    def test_two_concurrent_markets(self):
        """Two markets: one unhedged, one hedged. Real multi-market scenario."""
        inv_a = MarketInventory(
            up_shares=Decimal("100"),
            up_cost=Decimal("48.00"),  # VWAP 0.48, unhedged
        )
        inv_b = MarketInventory(
            up_shares=Decimal("80"),
            down_shares=Decimal("80"),
            up_cost=Decimal("37.60"),   # VWAP 0.47
            down_cost=Decimal("41.60"),  # VWAP 0.52
        )
        exposure = calculate_exposure({}, {"btc-a": inv_a, "btc-b": inv_b})
        # Market A: 100 unhedged at $1/share = $100
        # Market B: 80 hedged at (0.47 + 0.52) = $79.20
        # Total = $179.20
        assert exposure == Decimal("179.20"), f"Expected $179.20, got ${exposure}"


# ---------------------------------------------------------------------------
# Test 2: Hedge affordability — can the hedge leg proceed given exposure?
# ---------------------------------------------------------------------------

class TestHedgeAffordability:
    """Simulate the bankroll check in _place_hedge_leg with real numbers.

    This tests the logic at engine.py:899-908 without needing the full engine.
    """

    @staticmethod
    def _can_afford_hedge(
        bankroll: int,
        unhedged_shares: Decimal,
        first_vwap: Decimal,
        hedge_maker: Decimal,
        other_exposure: Decimal = ZERO,
    ) -> tuple[bool, Decimal, Decimal]:
        """Simulate _place_hedge_leg bankroll check. Returns (can_afford, effective_remaining, needed).

        Mirrors engine.py: unhedged exposure reserves ~(1-first_vwap)/share for
        the hedge. The bankroll check adds that embedded reserve back so the
        hedge isn't starved by its own reservation.
        """
        inv = MarketInventory(
            up_shares=unhedged_shares,
            up_cost=unhedged_shares * first_vwap,
        )
        inventories = {"this-market": inv}
        exposure = calculate_exposure({}, inventories) + other_exposure
        cap = total_bankroll_cap(Decimal(str(bankroll)))
        remaining = cap - exposure
        # Add back hedge reserve already embedded in unhedged exposure
        embedded_reserve = unhedged_shares * (ONE - first_vwap)
        effective_remaining = remaining + embedded_reserve
        hedge_notional = unhedged_shares * hedge_maker
        return (hedge_notional <= effective_remaining, effective_remaining, hedge_notional)

    @pytest.mark.parametrize("bankroll,shares,first_vwap,hedge_maker,other_exp,should_pass", [
        # $500 bankroll, 100 shares at 0.48, hedge at 0.51 → exposure=$100, eff_remaining=$352, need=$51
        (500, Decimal("100"), Decimal("0.48"), Decimal("0.51"), ZERO, True),
        # $200 bankroll, 80 shares at 0.47, hedge at 0.52 → exposure=$80, eff_remaining=$122.40, need=$41.60
        (200, Decimal("80"), Decimal("0.47"), Decimal("0.52"), ZERO, True),
        # $500 bankroll, 100 shares at 0.48, $300 other → remaining=$0 + $52 reserve = $52, need=$51 → OK
        (500, Decimal("100"), Decimal("0.48"), Decimal("0.51"), Decimal("300"), True),
        # $200 bankroll, 150 shares at 0.48, $0 other → remaining=$10 + $78 reserve = $88, need=$76.50 → OK
        (200, Decimal("150"), Decimal("0.48"), Decimal("0.51"), ZERO, True),
        # $500 bankroll, 100 shares at 0.48, $360 other → remaining=-$60 + $52 = -$8, need=$51 → BLOCKED
        (500, Decimal("100"), Decimal("0.48"), Decimal("0.51"), Decimal("360"), False),
        # $1000 bankroll, 200 shares at 0.47, hedge at 0.52, $400 other → eff_remaining=$306, need=$104
        (1000, Decimal("200"), Decimal("0.47"), Decimal("0.52"), Decimal("400"), True),
    ], ids=[
        "500-100sh-clean",
        "200-80sh-clean",
        "500-100sh-crowded-ok",
        "200-large-position-ok",
        "500-truly-exhausted",
        "1000-200sh-half-used",
    ])
    def test_hedge_affordability(self, bankroll, shares, first_vwap, hedge_maker, other_exp, should_pass):
        can_afford, remaining, needed = self._can_afford_hedge(
            bankroll, shares, first_vwap, hedge_maker, other_exp,
        )
        if should_pass:
            assert can_afford, (
                f"Hedge should be affordable: need=${needed:.2f}, remaining=${remaining:.2f} "
                f"(bankroll=${bankroll})"
            )
        else:
            assert not can_afford, (
                f"Hedge should be BLOCKED: need=${needed:.2f}, remaining=${remaining:.2f} "
                f"(bankroll=${bankroll})"
            )


# ---------------------------------------------------------------------------
# Test 3: Edge cases — boundary conditions from real trading
# ---------------------------------------------------------------------------

class TestEdgeCases:
    """Boundary conditions observed in real trading sessions."""

    def test_exposure_with_pending_order_and_position(self):
        """Real scenario: first-leg GTC order + existing hedged position from prior window."""
        order = OrderState(
            order_id="o1",
            market=None,
            token_id="UP_TOK",
            direction=Direction.UP,
            price=Decimal("0.48"),
            size=Decimal("100"),
            placed_at=0,
            reserved_hedge_notional=Decimal("51.00"),  # hedge reserve = 100 * (1 - 0.01 - 0.48)
        )
        prior_inv = MarketInventory(
            up_shares=Decimal("50"),
            down_shares=Decimal("50"),
            up_cost=Decimal("23.50"),  # VWAP 0.47
            down_cost=Decimal("26.00"),  # VWAP 0.52
        )
        orders = {"UP_TOK": order}
        invs = {"prior-market": prior_inv}
        exposure = calculate_exposure(orders, invs)

        # Order: 0.48 * 100 = $48 notional + $51 reserve = $99
        # Prior hedged: 50 * (0.47 + 0.52) = $49.50
        # Total = $148.50
        expected = Decimal("48.00") + Decimal("51.00") + Decimal("49.50")
        assert exposure == expected, f"Expected ${expected}, got ${exposure}"

    def test_breakdown_matches_total(self):
        """Verify breakdown components sum to total for a complex scenario."""
        order = OrderState(
            order_id="o1", market=None, token_id="UP_TOK",
            direction=Direction.UP, price=Decimal("0.48"), size=Decimal("100"),
            placed_at=0, reserved_hedge_notional=Decimal("51.00"),
        )
        inv_unhedged = MarketInventory(
            down_shares=Decimal("80"),
            down_cost=Decimal("41.60"),  # VWAP 0.52
        )
        inv_hedged = MarketInventory(
            up_shares=Decimal("60"),
            down_shares=Decimal("60"),
            up_cost=Decimal("28.80"),  # VWAP 0.48
            down_cost=Decimal("31.20"),  # VWAP 0.52
        )
        orders = {"UP_TOK": order}
        invs = {"mkt-a": inv_unhedged, "mkt-b": inv_hedged}

        total = calculate_exposure(orders, invs)
        ord_n, unh, hed, brk_total = calculate_exposure_breakdown(orders, invs)

        assert brk_total == total, f"Breakdown total ${brk_total} != exposure ${total}"
        # Verify components:
        # orders = 0.48 * 100 = $48, reserved = $51
        assert ord_n == Decimal("48.00")
        # unhedged: 80 DOWN at vwap 0.52 → 80*0.52 + 80*0.48 = $80
        assert unh == Decimal("80.00"), f"Unhedged should be $80, got ${unh}"
        # hedged: 60 * (0.48 + 0.52) = $60
        assert hed == Decimal("60.00"), f"Hedged should be $60, got ${hed}"
        # total = 48 + 51 + 80 + 60 = $239
        assert total == Decimal("239.00"), f"Total should be $239, got ${total}"
