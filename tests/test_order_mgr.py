"""Tests for OrderManager — FOK sentinel guard + order reconciliation."""

from __future__ import annotations

import time
from decimal import Decimal
from unittest.mock import MagicMock

from py_clob_client.clob_types import OrderType

from complete_set.models import Direction, GabagoolMarket, OrderState
from complete_set.order_mgr import OrderManager

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
        mgr._orders["111"] = OrderState(
            order_id="",
            market=market,
            token_id="111",
            direction=Direction.UP,
            price=Decimal("0.45"),
            size=Decimal("10"),
            placed_at=time.time(),
            side="BUY",
        )

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
