"""Tests for MarketInventory data model — VWAP, add/reduce, imbalance."""

from decimal import Decimal

from rebate_maker.models import MarketInventory

ZERO = Decimal("0")


class TestVWAP:
    def test_up_vwap_basic(self):
        inv = MarketInventory(up_shares=Decimal("10"), up_cost=Decimal("4.50"))
        assert inv.up_vwap == Decimal("0.45")

    def test_down_vwap_basic(self):
        inv = MarketInventory(down_shares=Decimal("8"), down_cost=Decimal("3.60"))
        assert inv.down_vwap == Decimal("0.45")

    def test_vwap_none_when_zero_shares(self):
        inv = MarketInventory()
        assert inv.up_vwap is None
        assert inv.down_vwap is None

    def test_vwap_full_precision_no_quantize(self):
        """VWAP should return full precision, not quantized to 4 decimals."""
        inv = MarketInventory(up_shares=Decimal("3"), up_cost=Decimal("1"))
        vwap = inv.up_vwap
        # 1/3 = 0.333333... — should NOT be 0.3333
        assert vwap is not None
        assert str(vwap) != "0.3333"
        assert vwap == Decimal("1") / Decimal("3")

    def test_vwap_single_fill(self):
        inv = MarketInventory(up_shares=Decimal("5"), up_cost=Decimal("2.25"))
        assert inv.up_vwap == Decimal("0.45")

    def test_vwap_multiple_fills(self):
        inv = MarketInventory()
        inv = inv.add_up(Decimal("5"), 1.0, Decimal("0.40"))
        inv = inv.add_up(Decimal("5"), 2.0, Decimal("0.50"))
        # cost = 5*0.40 + 5*0.50 = 4.50, shares=10
        assert inv.up_vwap == Decimal("0.45")


class TestAddReduce:
    def test_add_up(self):
        inv = MarketInventory()
        inv = inv.add_up(Decimal("10"), 1.0, Decimal("0.45"))
        assert inv.up_shares == Decimal("10")
        assert inv.up_cost == Decimal("4.50")
        assert inv.filled_up_shares == Decimal("10")

    def test_add_down(self):
        inv = MarketInventory()
        inv = inv.add_down(Decimal("8"), 1.0, Decimal("0.50"))
        assert inv.down_shares == Decimal("8")
        assert inv.down_cost == Decimal("4.00")
        assert inv.filled_down_shares == Decimal("8")

    def test_reduce_up_proportional_cost(self):
        inv = MarketInventory(
            up_shares=Decimal("10"), up_cost=Decimal("4.50"),
            filled_up_shares=Decimal("10"),
        )
        inv = inv.reduce_up(Decimal("5"), Decimal("0.60"))
        assert inv.up_shares == Decimal("5")
        assert inv.up_cost == Decimal("2.25")  # cost halved

    def test_reduce_down_proportional_cost(self):
        inv = MarketInventory(
            down_shares=Decimal("8"), down_cost=Decimal("4.00"),
            filled_down_shares=Decimal("8"),
        )
        inv = inv.reduce_down(Decimal("4"), Decimal("0.55"))
        assert inv.down_shares == Decimal("4")
        assert inv.down_cost == Decimal("2.00")

    def test_reduce_to_zero(self):
        inv = MarketInventory(
            up_shares=Decimal("10"), up_cost=Decimal("4.50"),
            filled_up_shares=Decimal("10"),
        )
        inv = inv.reduce_up(Decimal("10"), Decimal("0.50"))
        assert inv.up_shares == ZERO
        assert inv.up_cost == ZERO

    def test_reduce_more_than_available(self):
        inv = MarketInventory(
            up_shares=Decimal("5"), up_cost=Decimal("2.50"),
            filled_up_shares=Decimal("5"),
        )
        inv = inv.reduce_up(Decimal("10"), Decimal("0.50"))
        assert inv.up_shares == ZERO
        assert inv.up_cost == ZERO

    def test_cost_accumulation_multi_fill(self):
        inv = MarketInventory()
        inv = inv.add_up(Decimal("5"), 1.0, Decimal("0.40"))
        inv = inv.add_up(Decimal("3"), 2.0, Decimal("0.50"))
        assert inv.up_cost == Decimal("5") * Decimal("0.40") + Decimal("3") * Decimal("0.50")
        assert inv.up_shares == Decimal("8")


class TestImbalance:
    def test_balanced(self):
        inv = MarketInventory(up_shares=Decimal("10"), down_shares=Decimal("10"))
        assert inv.imbalance == ZERO

    def test_more_up(self):
        inv = MarketInventory(up_shares=Decimal("10"), down_shares=Decimal("5"))
        assert inv.imbalance == Decimal("5")

    def test_more_down(self):
        inv = MarketInventory(up_shares=Decimal("3"), down_shares=Decimal("8"))
        assert inv.imbalance == Decimal("-5")


class TestEntryDynamicEdge:
    def test_preserves_through_add(self):
        inv = MarketInventory(entry_dynamic_edge=Decimal("0.02"))
        inv = inv.add_up(Decimal("5"), 1.0, Decimal("0.45"))
        assert inv.entry_dynamic_edge == Decimal("0.02")

    def test_preserves_through_reduce(self):
        inv = MarketInventory(
            up_shares=Decimal("10"), up_cost=Decimal("4.50"),
            entry_dynamic_edge=Decimal("0.03"),
            filled_up_shares=Decimal("10"),
        )
        inv = inv.reduce_up(Decimal("5"), Decimal("0.50"))
        assert inv.entry_dynamic_edge == Decimal("0.03")

    def test_preserves_through_mark_top_up(self):
        inv = MarketInventory(entry_dynamic_edge=Decimal("0.015"))
        inv = inv.mark_top_up(1.0)
        assert inv.entry_dynamic_edge == Decimal("0.015")
