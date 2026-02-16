"""Tests for grid-maker strategy — static grid, config, and bulk fill detection."""

from __future__ import annotations

import time
from dataclasses import replace
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from grid_maker.capital import calculate_grid_allocation, calculate_static_grid
from grid_maker.config import GridMakerConfig, load_grid_maker_config, validate_config
from shared.models import ZERO, Direction, GabagoolMarket, OrderState
from shared.order_mgr import OrderManager

D = Decimal


# -----------------------------------------------------------------
# Static grid tests
# -----------------------------------------------------------------


class TestCalculateStaticGrid:
    def test_full_range(self):
        """99 levels from $0.01 to $0.99, all sizes = fixed."""
        grid = calculate_static_grid(
            min_price=D("0.01"),
            max_price=D("0.99"),
            grid_step=D("0.01"),
            fixed_size=D("26"),
            budget=D("100000"),  # huge budget, no cap
        )
        assert len(grid) == 99
        # All sizes should be 26
        for price, size in grid:
            assert size == D("26")
        # First and last prices
        assert grid[0][0] == D("0.01")
        assert grid[-1][0] == D("0.99")

    def test_budget_cap(self):
        """Budget=$50 should truncate from the expensive end."""
        grid = calculate_static_grid(
            min_price=D("0.01"),
            max_price=D("0.99"),
            grid_step=D("0.01"),
            fixed_size=D("26"),
            budget=D("50"),
        )
        # Budget caps: cheapest levels first, so should get fewer than 99
        assert len(grid) < 99
        assert len(grid) > 0
        # Total notional should be <= $50
        total = sum(p * s for p, s in grid)
        assert total <= D("50")
        # First price should still be $0.01
        assert grid[0][0] == D("0.01")

    def test_custom_range(self):
        """$0.10-$0.50 at $0.01 step = 41 levels."""
        grid = calculate_static_grid(
            min_price=D("0.10"),
            max_price=D("0.50"),
            grid_step=D("0.01"),
            fixed_size=D("10"),
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
            fixed_size=D("10"),
            budget=D("100"),
        )
        assert len(grid) == 1
        assert grid[0] == (D("0.50"), D("10"))


class TestCalculateGridAllocationUnchanged:
    """Regression: dynamic mode grid allocation is identical to before."""

    def test_flat_basic(self):
        grid = calculate_grid_allocation(
            budget=D("100"),
            grid_levels=10,
            base_size=D("5"),
            grid_step=D("0.01"),
            best_bid=D("0.50"),
            size_curve="flat",
        )
        assert len(grid) > 0
        # All sizes should be 5 (flat curve)
        for _, size in grid:
            assert size == D("5")
        # Prices should start at best_bid + step
        assert grid[0][0] == D("0.51")

    def test_budget_capped(self):
        grid = calculate_grid_allocation(
            budget=D("5"),
            grid_levels=30,
            base_size=D("10"),
            grid_step=D("0.01"),
            best_bid=D("0.50"),
            size_curve="flat",
        )
        total = sum(p * s for p, s in grid)
        assert total <= D("5")

    def test_empty_on_bad_inputs(self):
        assert calculate_grid_allocation(D("100"), 0, D("5"), D("0.01"), D("0.50")) == []
        assert calculate_grid_allocation(D("0"), 10, D("5"), D("0.01"), D("0.50")) == []
        assert calculate_grid_allocation(D("100"), 10, D("5"), D("0.01"), None) == []


# -----------------------------------------------------------------
# Config tests
# -----------------------------------------------------------------


class TestGridMakerConfig:
    def test_static_mode_defaults(self):
        """New fields parse correctly with defaults."""
        cfg = GridMakerConfig()
        assert cfg.grid_mode == "dynamic"
        assert cfg.fixed_size_shares == D("26")
        assert cfg.merge_mode == "eager"
        assert cfg.merge_batch_interval_sec == 3600

    def test_static_mode_values(self):
        cfg = GridMakerConfig(
            grid_mode="static",
            fixed_size_shares=D("10"),
            merge_mode="batch",
            merge_batch_interval_sec=1800,
        )
        assert cfg.grid_mode == "static"
        assert cfg.fixed_size_shares == D("10")
        assert cfg.merge_mode == "batch"
        assert cfg.merge_batch_interval_sec == 1800

    def test_invalid_grid_mode(self):
        cfg = GridMakerConfig(grid_mode="invalid")
        with pytest.raises(ValueError, match="grid_mode"):
            validate_config(cfg)

    def test_invalid_merge_mode(self):
        cfg = GridMakerConfig(merge_mode="invalid")
        with pytest.raises(ValueError, match="merge_mode"):
            validate_config(cfg)

    def test_invalid_fixed_size(self):
        cfg = GridMakerConfig(fixed_size_shares=D("0"))
        with pytest.raises(ValueError, match="fixed_size_shares"):
            validate_config(cfg)

    def test_invalid_batch_interval(self):
        cfg = GridMakerConfig(merge_batch_interval_sec=0)
        with pytest.raises(ValueError, match="merge_batch_interval_sec"):
            validate_config(cfg)

    def test_backward_compat_no_new_fields(self):
        """YAML without new fields loads with current defaults."""
        raw = {
            "grid_maker": {
                "enabled": True,
                "dry_run": True,
                "bankroll_usd": 500,
            }
        }
        cfg = load_grid_maker_config(raw)
        assert cfg.grid_mode == "dynamic"
        assert cfg.fixed_size_shares == D("26")
        assert cfg.merge_mode == "eager"
        assert cfg.merge_batch_interval_sec == 3600

    def test_load_static_config(self):
        """YAML with new fields loads correctly."""
        raw = {
            "grid_maker": {
                "grid_mode": "static",
                "fixed_size_shares": 10,
                "merge_mode": "batch",
                "merge_batch_interval_sec": 1800,
            }
        }
        cfg = load_grid_maker_config(raw)
        assert cfg.grid_mode == "static"
        assert cfg.fixed_size_shares == D("10")
        assert cfg.merge_mode == "batch"
        assert cfg.merge_batch_interval_sec == 1800


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
