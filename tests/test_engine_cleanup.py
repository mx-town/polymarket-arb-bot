"""Tests for engine buffer phase — CLEANUP_SELL removal."""

import time
from decimal import Decimal
from unittest.mock import MagicMock, patch

from complete_set.config import CompleteSetConfig
from complete_set.models import GabagoolMarket, MarketInventory


class TestBufferPhase:
    """Verify that the pre-resolution buffer cancels orders but does NOT sell."""

    def _make_engine(self):
        from complete_set.engine import Engine

        cfg = CompleteSetConfig(
            dry_run=True,
            no_new_orders_sec=90,
            min_merge_shares=Decimal("10"),
            min_merge_profit_usd=Decimal("0.02"),
            max_gas_price_gwei=200,
        )
        client = MagicMock()
        engine = Engine(client, cfg)
        return engine

    def _make_market(self, seconds_left=30):
        return GabagoolMarket(
            slug="btc-updown-15m-test",
            up_token_id="111",
            down_token_id="222",
            end_time=time.time() + seconds_left,
            market_type="updown-15m",
            condition_id="0xabc",
        )

    def test_buffer_cancels_orders(self):
        engine = self._make_engine()
        market = self._make_market(seconds_left=30)

        # Put inventory with unhedged UP
        engine._inventory._inventory_by_market[market.slug] = MarketInventory(
            up_shares=Decimal("10"),
            up_cost=Decimal("4.50"),
            filled_up_shares=Decimal("10"),
        )

        cancel_called = []
        engine._order_mgr.cancel_market_orders = lambda *a, **kw: cancel_called.append(True)

        # Mock place_order to detect if sell is attempted
        sell_placed = []
        engine._order_mgr.place_order = lambda *a, **kw: sell_placed.append(kw.get("side", "BUY"))

        engine._evaluate_market(market, time.time())

        assert len(cancel_called) == 1, "Should cancel orders in buffer"
        assert len(sell_placed) == 0, "Should NOT place sell orders (CLEANUP_SELL removed)"

    def test_tick_timing_init(self):
        """T4-2: Tick timing counters should initialize to zero."""
        engine = self._make_engine()
        assert engine._tick_count == 0
        assert engine._tick_total_ms == 0.0
        assert engine._tick_max_ms == 0.0

    def test_reconcile_timer_init(self):
        """T3-6: Reconcile timer should initialize to zero."""
        engine = self._make_engine()
        assert engine._last_reconcile == 0.0

    def test_buffer_logs_hold(self):
        """Buffer phase should mention BUFFER_HOLD when there's inventory."""
        engine = self._make_engine()
        market = self._make_market(seconds_left=30)

        engine._inventory._inventory_by_market[market.slug] = MarketInventory(
            up_shares=Decimal("10"),
            up_cost=Decimal("4.50"),
        )

        engine._order_mgr.cancel_market_orders = lambda *a, **kw: None

        with patch("complete_set.engine.log") as mock_log:
            engine._evaluate_market(market, time.time())
            # Check that BUFFER_HOLD was logged
            log_calls = [str(c) for c in mock_log.info.call_args_list]
            assert any("BUFFER_HOLD" in c for c in log_calls)
