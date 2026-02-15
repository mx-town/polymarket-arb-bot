"""Tests for InventoryTracker — reduce_merged, clear_market, cost scaling."""

from decimal import Decimal

from complete_set.inventory import InventoryTracker
from complete_set.models import MarketInventory

ZERO = Decimal("0")
ONE = Decimal("1")


class TestReduceMerged:
    def test_basic_reduce(self):
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=Decimal("10"),
            up_cost=Decimal("4.50"),
            down_cost=Decimal("4.50"),
            filled_up_shares=Decimal("10"),
            filled_down_shares=Decimal("10"),
        )
        tracker.reduce_merged("test", Decimal("10"))
        inv = tracker.get_inventory("test")
        assert inv.up_shares == ZERO
        assert inv.down_shares == ZERO
        assert inv.up_cost == ZERO
        assert inv.down_cost == ZERO

    def test_partial_reduce(self):
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("20"),
            down_shares=Decimal("15"),
            up_cost=Decimal("9.00"),
            down_cost=Decimal("6.75"),
            filled_up_shares=Decimal("20"),
            filled_down_shares=Decimal("15"),
        )
        tracker.reduce_merged("test", Decimal("10"))
        inv = tracker.get_inventory("test")
        assert inv.up_shares == Decimal("10")
        assert inv.down_shares == Decimal("5")
        # Cost scaled proportionally: up: 9.00 * 10/20 = 4.50
        assert inv.up_cost == Decimal("4.50")
        # down: 6.75 * 5/15 = 2.25
        assert inv.down_cost == Decimal("2.25")

    def test_pnl_recorded(self):
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=Decimal("10"),
            up_cost=Decimal("4.50"),
            down_cost=Decimal("4.50"),
        )
        tracker.reduce_merged("test", Decimal("10"))
        # PnL = 10 * 1.00 - 10 * (0.45 + 0.45) = 10 - 9.0 = 1.0
        assert tracker.session_realized_pnl == Decimal("1.00")

    def test_filled_shares_scale(self):
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("20"),
            down_shares=Decimal("20"),
            up_cost=Decimal("9.00"),
            down_cost=Decimal("9.00"),
            filled_up_shares=Decimal("20"),
            filled_down_shares=Decimal("20"),
        )
        tracker.reduce_merged("test", Decimal("10"))
        inv = tracker.get_inventory("test")
        assert inv.filled_up_shares == Decimal("10")
        assert inv.filled_down_shares == Decimal("10")

    def test_entry_dynamic_edge_preserved(self):
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=Decimal("10"),
            up_cost=Decimal("4.50"),
            down_cost=Decimal("4.50"),
            entry_dynamic_edge=Decimal("0.02"),
        )
        tracker.reduce_merged("test", Decimal("10"))
        inv = tracker.get_inventory("test")
        assert inv.entry_dynamic_edge == Decimal("0.02")

    def test_last_merge_at_set(self):
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=Decimal("10"),
            up_cost=Decimal("4.50"),
            down_cost=Decimal("4.50"),
        )
        tracker.reduce_merged("test", Decimal("10"))
        inv = tracker.get_inventory("test")
        assert inv.last_merge_at is not None

    def test_full_merge_no_fp_residual(self):
        """Merging all shares should produce exact ZERO, not 0E-N artifacts."""
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("16"),
            down_shares=Decimal("16"),
            up_cost=Decimal("7.36"),
            down_cost=Decimal("7.84"),
            filled_up_shares=Decimal("16"),
            filled_down_shares=Decimal("16"),
        )
        tracker.reduce_merged("test", Decimal("16"))
        inv = tracker.get_inventory("test")
        # All fields should be canonical ZERO, not 0E-25 or similar
        assert inv.up_shares == ZERO
        assert inv.down_shares == ZERO
        assert inv.up_cost == ZERO
        assert inv.down_cost == ZERO
        assert inv.filled_up_shares == ZERO
        assert inv.filled_down_shares == ZERO
        # Verify string representation is clean (catches 0E-N)
        assert str(inv.up_cost) == "0"
        assert str(inv.down_cost) == "0"
        assert str(inv.filled_up_shares) == "0"
        assert str(inv.filled_down_shares) == "0"

    def test_prior_merge_pnl_accumulated(self):
        """Merge PnL accumulates across multiple merges for CLEAR_INVENTORY display."""
        tracker = InventoryTracker(dry_run=True)
        # Start with 30/30, merge 10 twice
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("30"),
            down_shares=Decimal("30"),
            up_cost=Decimal("13.50"),   # VWAP = 0.45
            down_cost=Decimal("13.50"),  # VWAP = 0.45
            filled_up_shares=Decimal("30"),
            filled_down_shares=Decimal("30"),
        )
        tracker.reduce_merged("test", Decimal("10"))
        inv = tracker.get_inventory("test")
        # PnL from first merge: 10 * (1 - 0.45 - 0.45) = 10 * 0.10 = $1.00
        assert inv.prior_merge_pnl == Decimal("1.00")

        tracker.reduce_merged("test", Decimal("10"))
        inv = tracker.get_inventory("test")
        # PnL from second merge: 10 * (1 - 0.45 - 0.45) = $1.00
        # Accumulated: $1.00 + $1.00 = $2.00
        assert inv.prior_merge_pnl == Decimal("2.00")

    def test_clear_market_includes_prior_merge_pnl_in_session(self):
        """clear_market books residual PnL; prior merge PnL was already booked in reduce_merged."""
        tracker = InventoryTracker(dry_run=True)
        # Simulate: had 20/20, merged 10, left with 10/10
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=Decimal("10"),
            up_cost=Decimal("4.50"),
            down_cost=Decimal("4.50"),
            prior_merge_pnl=Decimal("1.00"),  # from a previous merge of 10 shares
        )
        # Pre-load session_realized_pnl with the merge PnL (as reduce_merged would have)
        tracker.session_realized_pnl = Decimal("1.00")

        tracker.clear_market("test")
        # clear_market books: hedged=10, pnl = 10*(1-0.45-0.45) = $1.00
        # session total = $1.00 (from merge) + $1.00 (from clear) = $2.00
        assert tracker.session_realized_pnl == Decimal("2.00")


class TestClearMarket:
    def test_hedged_pnl(self):
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=Decimal("10"),
            up_cost=Decimal("4.00"),
            down_cost=Decimal("4.00"),
        )
        tracker.clear_market("test")
        # hedged=10, cost=10*(0.40+0.40)=8.00, value=10.00, PnL=2.00
        assert tracker.session_realized_pnl == Decimal("2.00")

    def test_no_shares(self):
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory()
        tracker.clear_market("test")
        assert tracker.session_realized_pnl == ZERO

    def test_unhedged_only(self):
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("10"), up_cost=Decimal("4.00"),
        )
        tracker.clear_market("test")
        # hedged=0, unhedged cost booked as loss: 10 shares * 0.40 vwap = -$4.00
        assert tracker.session_realized_pnl == Decimal("-4.00")


    def test_unhedged_with_resolution_bids(self):
        """clear_market with final bids logs resolution estimate but doesn't change PnL accounting."""
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("10"), up_cost=Decimal("4.00"),
        )
        tracker.clear_market("test", up_bid=Decimal("0.95"), down_bid=Decimal("0.05"))
        # PnL accounting unchanged: unhedged cost = 10 * 0.40 = $4.00 loss
        # (resolution_est is logging-only, doesn't affect session_realized_pnl)
        assert tracker.session_realized_pnl == Decimal("-4.00")

    def test_clear_with_no_bids_still_works(self):
        """clear_market without bids works exactly as before."""
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=Decimal("10"),
            up_cost=Decimal("4.00"),
            down_cost=Decimal("4.00"),
        )
        tracker.clear_market("test")
        assert tracker.session_realized_pnl == Decimal("2.00")


class TestSetEntryDynamicEdge:
    def test_sets_when_zero(self):
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory()
        tracker.set_entry_dynamic_edge("test", Decimal("0.02"))
        assert tracker.get_inventory("test").entry_dynamic_edge == Decimal("0.02")

    def test_does_not_overwrite(self):
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            entry_dynamic_edge=Decimal("0.03"),
        )
        tracker.set_entry_dynamic_edge("test", Decimal("0.01"))
        # Should keep original value
        assert tracker.get_inventory("test").entry_dynamic_edge == Decimal("0.03")


class TestBootstrapFlags:
    """T3-5: Bootstrap flag propagation."""

    def test_add_up_clears_bootstrapped_up(self):
        inv = MarketInventory(
            up_shares=Decimal("10"),
            up_cost=Decimal("5"),
            bootstrapped_up=True,
            bootstrapped_down=True,
        )
        result = inv.add_up(Decimal("5"), 1000.0, Decimal("0.50"))
        assert result.bootstrapped_up is False
        assert result.bootstrapped_down is True

    def test_add_down_clears_bootstrapped_down(self):
        inv = MarketInventory(
            down_shares=Decimal("10"),
            down_cost=Decimal("5"),
            bootstrapped_up=True,
            bootstrapped_down=True,
        )
        result = inv.add_down(Decimal("5"), 1000.0, Decimal("0.50"))
        assert result.bootstrapped_up is True
        assert result.bootstrapped_down is False

    def test_reduce_up_preserves_flags(self):
        inv = MarketInventory(
            up_shares=Decimal("10"),
            up_cost=Decimal("5"),
            bootstrapped_up=True,
            bootstrapped_down=True,
            filled_up_shares=Decimal("10"),
        )
        result = inv.reduce_up(Decimal("5"), Decimal("0.50"))
        assert result.bootstrapped_up is True
        assert result.bootstrapped_down is True

    def test_reduce_down_preserves_flags(self):
        inv = MarketInventory(
            down_shares=Decimal("10"),
            down_cost=Decimal("5"),
            bootstrapped_up=True,
            bootstrapped_down=True,
            filled_down_shares=Decimal("10"),
        )
        result = inv.reduce_down(Decimal("5"), Decimal("0.50"))
        assert result.bootstrapped_up is True
        assert result.bootstrapped_down is True

    def test_bootstrap_detected_in_sync(self):
        """sync_inventory should set bootstrapped flags when cost is estimated."""
        tracker = InventoryTracker(dry_run=False)
        import time

        from complete_set.models import GabagoolMarket
        market = GabagoolMarket(
            slug="test-bootstrap",
            up_token_id="tok-up",
            down_token_id="tok-down",
            end_time=time.time() + 600,
            market_type="updown-15m",
        )
        # Simulate chain showing shares but no prior inventory
        tracker._shares_by_token = {"tok-up": Decimal("10"), "tok-down": ZERO}
        tracker.sync_inventory([market], get_mid_price=lambda tid: Decimal("0.45"))
        inv = tracker.get_inventory("test-bootstrap")
        assert inv.bootstrapped_up is True
        assert inv.bootstrapped_down is False

    def test_reduce_merged_preserves_bootstrap_flags(self):
        tracker = InventoryTracker(dry_run=True)
        tracker._inventory_by_market["test"] = MarketInventory(
            up_shares=Decimal("20"),
            down_shares=Decimal("20"),
            up_cost=Decimal("9"),
            down_cost=Decimal("9"),
            filled_up_shares=Decimal("20"),
            filled_down_shares=Decimal("20"),
            bootstrapped_up=True,
            bootstrapped_down=False,
        )
        tracker.reduce_merged("test", Decimal("10"))
        inv = tracker.get_inventory("test")
        assert inv.bootstrapped_up is True
        assert inv.bootstrapped_down is False
