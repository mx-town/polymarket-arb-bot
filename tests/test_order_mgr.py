"""Tests for OrderManager — FOK sentinel guard + order reconciliation + dry-run fill sim."""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

from py_clob_client.clob_types import OrderType

from rebate_maker.models import Direction, GabagoolMarket, OrderState
from shared.order_mgr import OrderManager

ZERO = Decimal("0")


def _make_market():
    return GabagoolMarket(
        slug="btc-updown-15m-test",
        up_token_id="111",
        down_token_id="222",
        end_time=time.time() + 600,
        market_type="updown-15m",
        condition_id="0xabc",
    )


class TestFOKSentinelGuard:
    """T3-2: FOK null orderId should NOT insert sentinel."""

    def test_fok_null_order_id_no_sentinel(self):
        """FOK order with null orderId should not block the token_id."""
        mgr = OrderManager(dry_run=False)
        market = _make_market()
        client = MagicMock()
        # post_order returns response with no orderId
        client.create_order.return_value = MagicMock()
        client.post_order.return_value = {"status": "ok"}

        result = mgr.place_order(
            client, market, "111", Direction.UP,
            Decimal("0.45"), Decimal("10"), 300,
            reason="TEST", order_type=OrderType.FOK,
        )

        assert result is False
        assert not mgr.has_order("111"), "FOK null orderId should not insert sentinel"

    def test_gtc_null_order_id_inserts_sentinel(self):
        """GTC order with null orderId SHOULD insert sentinel."""
        mgr = OrderManager(dry_run=False)
        market = _make_market()
        client = MagicMock()
        client.create_order.return_value = MagicMock()
        client.post_order.return_value = {"status": "ok"}

        result = mgr.place_order(
            client, market, "111", Direction.UP,
            Decimal("0.45"), Decimal("10"), 300,
            reason="TEST", order_type=OrderType.GTC,
        )

        assert result is False
        assert mgr.has_order("111"), "GTC null orderId should insert sentinel"
        state = mgr.get_order("111")
        assert state.order_id == ""

    def test_fok_exception_no_sentinel(self):
        """FOK order that raises exception should not insert sentinel."""
        mgr = OrderManager(dry_run=False)
        market = _make_market()
        client = MagicMock()
        client.create_order.return_value = MagicMock()
        client.post_order.side_effect = RuntimeError("network error")

        result = mgr.place_order(
            client, market, "111", Direction.UP,
            Decimal("0.45"), Decimal("10"), 300,
            reason="TEST", order_type=OrderType.FOK,
        )

        assert result is False
        assert not mgr.has_order("111"), "FOK exception should not insert sentinel"


class TestReconcileOrders:
    """T3-6: Sentinel upgrade + orphan detection."""

    def test_sentinel_upgraded_to_real_order(self):
        """Sentinel matching a CLOB order should be upgraded."""
        mgr = OrderManager(dry_run=False)
        market = _make_market()

        # Insert sentinel
        mgr._orders["111"] = [OrderState(
            order_id="",
            market=market,
            token_id="111",
            direction=Direction.UP,
            price=Decimal("0.45"),
            size=Decimal("10"),
            placed_at=time.time(),
            side="BUY",
        )]

        client = MagicMock()
        client.get_orders.return_value = [
            {"asset_id": "111", "id": "real-order-123", "status": "LIVE"},
        ]

        mgr.reconcile_orders(client)

        state = mgr.get_order("111")
        assert state is not None
        assert state.order_id == "real-order-123"

    def test_dry_run_skips_reconcile(self):
        """Reconciliation should be skipped in dry-run mode."""
        mgr = OrderManager(dry_run=True)
        client = MagicMock()
        mgr.reconcile_orders(client)
        client.get_orders.assert_not_called()

    def test_orphan_detection(self):
        """CLOB orders not tracked locally should be logged."""
        mgr = OrderManager(dry_run=False)
        client = MagicMock()
        client.get_orders.return_value = [
            {"asset_id": "999", "id": "orphan-order-456", "status": "LIVE"},
        ]

        # Should not raise — orphans are just logged
        mgr.reconcile_orders(client)

    def test_no_open_orders(self):
        """Empty CLOB order list should not error."""
        mgr = OrderManager(dry_run=False)
        client = MagicMock()
        client.get_orders.return_value = []
        mgr.reconcile_orders(client)

    def test_fetch_failure_handled(self):
        """Network error in get_orders should be caught."""
        mgr = OrderManager(dry_run=False)
        client = MagicMock()
        client.get_orders.side_effect = RuntimeError("network timeout")
        # Should not raise
        mgr.reconcile_orders(client)


class TestConsumedCrossing:
    """Dry-run fill sim should track consumed crossing to prevent double-counting."""

    def _place_dry_order(self, mgr):
        market = _make_market()
        mgr.place_order(
            client=None, market=market, token_id="111", direction=Direction.UP,
            price=Decimal("0.50"), size=Decimal("20"), seconds_to_end=300,
            reason="TEST",
        )
        return market

    @patch("shared.order_mgr.get_simulated_fill_size")
    def test_consumed_passed_and_incremented(self, mock_sim):
        """consumed_crossing should be passed to get_simulated_fill_size and grow after fills."""
        mgr = OrderManager(dry_run=True)
        self._place_dry_order(mgr)
        fills = []

        # First tick: sim returns 10 shares filled
        mock_sim.return_value = Decimal("10")
        mgr.check_pending_orders(client=None, on_fill=lambda s, d: fills.append(d))

        # Verify consumed was passed as 0 on first call
        _, kwargs = mock_sim.call_args
        assert kwargs["consumed"] == ZERO

        state = mgr.get_order("111")
        assert state.consumed_crossing == Decimal("10")
        assert state.matched_size == Decimal("10")
        assert len(fills) == 1
        assert fills[0] == Decimal("10")

        # Second tick: sim returns 5 more
        mock_sim.return_value = Decimal("5")
        mgr.check_pending_orders(client=None, on_fill=lambda s, d: fills.append(d))

        # Verify consumed was passed as 10 (accumulated from first fill)
        _, kwargs = mock_sim.call_args
        assert kwargs["consumed"] == Decimal("10")

        state = mgr.get_order("111")
        assert state.consumed_crossing == Decimal("15")
        assert state.matched_size == Decimal("15")

    @patch("shared.order_mgr.get_simulated_fill_size")
    def test_stale_book_prevents_double_fill(self, mock_sim):
        """Same crossing volume across ticks should not produce additional fills."""
        mgr = OrderManager(dry_run=True)
        self._place_dry_order(mgr)

        # First tick: 15 shares available, fill 15
        mock_sim.return_value = Decimal("15")
        mgr.check_pending_orders(client=None)

        state = mgr.get_order("111")
        assert state.consumed_crossing == Decimal("15")

        # Second tick: sim returns 0 (no new liquidity beyond consumed)
        mock_sim.return_value = ZERO
        mgr.check_pending_orders(client=None)

        # consumed_crossing unchanged — no new fill
        state = mgr.get_order("111")
        assert state.consumed_crossing == Decimal("15")
        assert state.matched_size == Decimal("15")

    @patch("shared.order_mgr.get_simulated_fill_size")
    def test_consumed_resets_on_new_order(self, mock_sim):
        """A new order should start with consumed_crossing=0."""
        mgr = OrderManager(dry_run=True)
        market = _make_market()

        # Place, fill partially, cancel
        mgr.place_order(
            client=None, market=market, token_id="111", direction=Direction.UP,
            price=Decimal("0.50"), size=Decimal("20"), seconds_to_end=300,
        )
        mock_sim.return_value = Decimal("8")
        mgr.check_pending_orders(client=None)
        mgr.cancel_order(client=None, token_id="111", reason="REPLACE")

        # Place new order on same token
        mgr.place_order(
            client=None, market=market, token_id="111", direction=Direction.UP,
            price=Decimal("0.48"), size=Decimal("15"), seconds_to_end=280,
        )
        state = mgr.get_order("111")
        assert state.consumed_crossing == ZERO
