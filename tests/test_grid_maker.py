"""Tests for grid-maker strategy — static grid, config, and bulk fill detection."""

from __future__ import annotations

import time
from dataclasses import replace
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from grid_maker.capital import calculate_static_grid
from grid_maker.config import GridMakerConfig, load_grid_maker_config, validate_config
from shared.models import ZERO, Direction, GabagoolMarket, OrderState
from shared.order_mgr import OrderManager

D = Decimal


# -----------------------------------------------------------------
# Static grid tests
# -----------------------------------------------------------------


class TestCalculateStaticGrid:
    def test_full_range_all_99_levels(self):
        """99 levels from $0.01 to $0.99, all sizes = target when budget is huge."""
        grid = calculate_static_grid(
            min_price=D("0.01"),
            max_price=D("0.99"),
            grid_step=D("0.01"),
            target_size=D("20"),
            budget=D("100000"),
        )
        assert len(grid) == 99
        for price, size in grid:
            assert size == D("20")
        assert grid[0][0] == D("0.01")
        assert grid[-1][0] == D("0.99")

    def test_budget_scaling_keeps_99_levels(self):
        """Small budget scales down shares but keeps ALL 99 levels."""
        grid = calculate_static_grid(
            min_price=D("0.01"),
            max_price=D("0.99"),
            grid_step=D("0.01"),
            target_size=D("20"),
            budget=D("50"),
        )
        # Must still have all 99 levels — never truncate coverage
        assert len(grid) == 99
        assert grid[0][0] == D("0.01")
        assert grid[-1][0] == D("0.99")
        # All sizes should be the same (uniform scaling)
        sizes = {s for _, s in grid}
        assert len(sizes) == 1
        # Scaled size must be less than target
        actual_size = grid[0][1]
        assert actual_size < D("20")
        assert actual_size >= D("1")  # minimum floor
        # Total notional should be <= budget
        total = sum(p * s for p, s in grid)
        assert total <= D("50")

    def test_min_1_share_floor(self):
        """Extremely tight budget still gives at least 1 share per level."""
        grid = calculate_static_grid(
            min_price=D("0.01"),
            max_price=D("0.99"),
            grid_step=D("0.01"),
            target_size=D("26"),
            budget=D("100"),  # full grid at 26 shares costs ~$1300, so heavy scaling
        )
        assert len(grid) == 99
        for _, size in grid:
            assert size >= D("1")

    def test_full_budget_at_target_size(self):
        """When budget covers full grid, every level gets target_size."""
        # Full grid at 26 shares: sum(i*26 for i=0.01..0.99) = 26 * 49.50 = $1287
        grid = calculate_static_grid(
            min_price=D("0.01"),
            max_price=D("0.99"),
            grid_step=D("0.01"),
            target_size=D("26"),
            budget=D("1300"),
        )
        assert len(grid) == 99
        for _, size in grid:
            assert size == D("26")

    def test_custom_range(self):
        """$0.10-$0.50 at $0.01 step = 41 levels."""
        grid = calculate_static_grid(
            min_price=D("0.10"),
            max_price=D("0.50"),
            grid_step=D("0.01"),
            target_size=D("10"),
            budget=D("100000"),
        )
        assert len(grid) == 41
        assert grid[0][0] == D("0.10")
        assert grid[-1][0] == D("0.50")

    def test_empty_on_bad_inputs(self):
        """Invalid inputs should return empty list."""
        assert calculate_static_grid(D("0"), D("0.99"), D("0.01"), D("26"), D("100")) == []
        assert calculate_static_grid(D("0.50"), D("0.01"), D("0.01"), D("26"), D("100")) == []
        assert calculate_static_grid(D("0.01"), D("0.99"), D("0"), D("26"), D("100")) == []
        assert calculate_static_grid(D("0.01"), D("0.99"), D("0.01"), D("0"), D("100")) == []
        assert calculate_static_grid(D("0.01"), D("0.99"), D("0.01"), D("26"), D("0")) == []

    def test_single_level(self):
        """min_price == max_price should give exactly 1 level."""
        grid = calculate_static_grid(
            min_price=D("0.50"),
            max_price=D("0.50"),
            grid_step=D("0.01"),
            target_size=D("10"),
            budget=D("100"),
        )
        assert len(grid) == 1
        assert grid[0] == (D("0.50"), D("10"))

    def test_different_target_sizes(self):
        """Different target sizes produce correct grids (gabagool sizing table)."""
        for target in [10, 15, 16, 20, 26]:
            grid = calculate_static_grid(
                min_price=D("0.01"),
                max_price=D("0.99"),
                grid_step=D("0.01"),
                target_size=D(str(target)),
                budget=D("100000"),
            )
            assert len(grid) == 99
            for _, size in grid:
                assert size == D(str(target))


# -----------------------------------------------------------------
# Config tests
# -----------------------------------------------------------------


class TestGridMakerConfig:
    def test_defaults(self):
        """Default config values for gabagool clone."""
        cfg = GridMakerConfig()
        assert cfg.grid_sizes == {
            "bitcoin": {"5m": 20, "15m": 15, "1h": 26},
            "ethereum": {"15m": 10, "1h": 16},
        }
        assert cfg.merge_batch_interval_sec == 3600
        assert cfg.min_seconds_to_end == 30
        assert cfg.entry_delay_sec == 5

    def test_get_size_for_known_combos(self):
        """get_size_for returns correct sizes for all gabagool combos."""
        cfg = GridMakerConfig()
        assert cfg.get_size_for("bitcoin", "5m") == 20
        assert cfg.get_size_for("bitcoin", "15m") == 15
        assert cfg.get_size_for("bitcoin", "1h") == 26
        assert cfg.get_size_for("ethereum", "15m") == 10
        assert cfg.get_size_for("ethereum", "1h") == 16

    def test_get_size_for_missing_combo(self):
        """get_size_for returns None for combos not in the sizing table."""
        cfg = GridMakerConfig()
        assert cfg.get_size_for("ethereum", "5m") is None
        assert cfg.get_size_for("dogecoin", "5m") is None

    def test_custom_grid_sizes(self):
        cfg = GridMakerConfig(
            grid_sizes={"bitcoin": {"5m": 50}},
        )
        assert cfg.get_size_for("bitcoin", "5m") == 50
        assert cfg.get_size_for("bitcoin", "15m") is None

    def test_invalid_grid_sizes_zero(self):
        cfg = GridMakerConfig(grid_sizes={"bitcoin": {"5m": 0}})
        with pytest.raises(ValueError, match="grid_sizes"):
            validate_config(cfg)

    def test_invalid_empty_grid_sizes(self):
        cfg = GridMakerConfig(grid_sizes={})
        with pytest.raises(ValueError, match="grid_sizes must not be empty"):
            validate_config(cfg)

    def test_invalid_batch_interval(self):
        cfg = GridMakerConfig(merge_batch_interval_sec=0)
        with pytest.raises(ValueError, match="merge_batch_interval_sec"):
            validate_config(cfg)

    def test_backward_compat_no_grid_sizes(self):
        """YAML without grid_sizes loads with default sizing table."""
        raw = {
            "grid_maker": {
                "enabled": True,
                "dry_run": True,
                "bankroll_usd": 500,
            }
        }
        cfg = load_grid_maker_config(raw)
        assert cfg.grid_sizes == {
            "bitcoin": {"5m": 20, "15m": 15, "1h": 26},
            "ethereum": {"15m": 10, "1h": 16},
        }
        assert cfg.merge_batch_interval_sec == 3600

    def test_load_config_with_grid_sizes(self):
        """YAML with grid_sizes loads correctly."""
        raw = {
            "grid_maker": {
                "grid_sizes": {
                    "bitcoin": {"5m": 30, "1h": 50},
                },
                "merge_batch_interval_sec": 1800,
                "entry_delay_sec": 3,
            }
        }
        cfg = load_grid_maker_config(raw)
        assert cfg.get_size_for("bitcoin", "5m") == 30
        assert cfg.get_size_for("bitcoin", "1h") == 50
        assert cfg.get_size_for("bitcoin", "15m") is None
        assert cfg.merge_batch_interval_sec == 1800
        assert cfg.entry_delay_sec == 3


# -----------------------------------------------------------------
# Bulk fill detection tests
# -----------------------------------------------------------------


class TestCheckPendingOrdersBulk:
    def _make_market(self) -> GabagoolMarket:
        return GabagoolMarket(
            slug="test-market",
            up_token_id="up123",
            down_token_id="down456",
            end_time=time.time() + 600,
            market_type="updown-5m",
            condition_id="0xtest",
        )

    def test_bulk_detects_fill(self):
        """Bulk fetch detects partial fill and fires on_fill callback."""
        mgr = OrderManager(dry_run=False)
        market = self._make_market()

        # Manually add an order to tracking
        state = OrderState(
            order_id="order-abc",
            market=market,
            token_id="up123",
            direction=Direction.UP,
            price=D("0.45"),
            size=D("26"),
            placed_at=time.time(),
            side="BUY",
            matched_size=D("0"),
        )
        mgr._orders["up123"] = [state]

        # Mock client.get_orders to return the order with partial fill
        mock_client = MagicMock()
        mock_client.get_orders.return_value = [
            {
                "id": "order-abc",
                "asset_id": "up123",
                "price": "0.45",
                "matched_size": "10",
                "status": "LIVE",
            }
        ]

        fills = []
        def on_fill(os, delta):
            fills.append((os.order_id, delta))

        mgr.check_pending_orders_bulk(mock_client, on_fill=on_fill)

        assert len(fills) == 1
        assert fills[0] == ("order-abc", D("10"))
        # Order should still be tracked (not fully filled)
        assert mgr.has_order("up123")

    def test_bulk_removes_terminal(self):
        """Order not in CLOB response triggers individual refresh."""
        mgr = OrderManager(dry_run=False)
        market = self._make_market()

        state = OrderState(
            order_id="order-xyz",
            market=market,
            token_id="up123",
            direction=Direction.UP,
            price=D("0.30"),
            size=D("10"),
            placed_at=time.time(),
            side="BUY",
            matched_size=D("0"),
        )
        mgr._orders["up123"] = [state]

        # CLOB returns empty (order not there anymore)
        mock_client = MagicMock()
        mock_client.get_orders.return_value = []
        # Individual refresh will be called; mock get_order to return filled
        mock_client.get_order.return_value = {
            "status": "FILLED",
            "matched_size": "10",
        }

        fills = []
        def on_fill(os, delta):
            fills.append((os.order_id, delta))

        mgr.check_pending_orders_bulk(mock_client, on_fill=on_fill)

        # Fill should be detected via individual refresh
        assert len(fills) == 1
        assert fills[0] == ("order-xyz", D("10"))

    def test_bulk_fallback_on_error(self):
        """Falls back to individual polling if bulk fetch fails."""
        mgr = OrderManager(dry_run=False)
        market = self._make_market()

        state = OrderState(
            order_id="order-err",
            market=market,
            token_id="up123",
            direction=Direction.UP,
            price=D("0.50"),
            size=D("5"),
            placed_at=time.time(),
            side="BUY",
            matched_size=D("0"),
        )
        mgr._orders["up123"] = [state]

        mock_client = MagicMock()
        mock_client.get_orders.side_effect = Exception("network error")
        mock_client.get_order.return_value = {
            "status": "LIVE",
            "matched_size": "3",
        }

        fills = []
        def on_fill(os, delta):
            fills.append(delta)

        mgr.check_pending_orders_bulk(mock_client, on_fill=on_fill)

        # Should have fallen back and detected fill
        assert len(fills) == 1
        assert fills[0] == D("3")

    def test_dry_run_delegates(self):
        """Dry run delegates to check_pending_orders."""
        mgr = OrderManager(dry_run=True)

        mock_client = MagicMock()
        with patch.object(mgr, "check_pending_orders") as mock_check:
            mgr.check_pending_orders_bulk(mock_client, on_fill=None)
            mock_check.assert_called_once_with(mock_client, on_fill=None)
