"""Tests for engine merge profitability check."""

import time
from decimal import Decimal
from unittest.mock import MagicMock

from rebate_maker.config import RebateMakerConfig
from rebate_maker.models import GabagoolMarket, MarketInventory


class TestMergeProfitabilityCheck:
    """Verify merge is skipped when gross profit is below threshold."""

    def _make_engine(self, min_merge_profit="0.02"):
        from rebate_maker.engine import Engine

        cfg = RebateMakerConfig(
            dry_run=True,
            no_new_orders_sec=90,
            min_merge_shares=Decimal("10"),
            min_merge_profit_usd=Decimal(min_merge_profit),
            max_gas_price_gwei=200,
        )
        client = MagicMock()
        engine = Engine(client, cfg)
        return engine

    def _make_market(self, seconds_left=300):
        return GabagoolMarket(
            slug="btc-updown-15m-test",
            up_token_id="111",
            down_token_id="222",
            end_time=time.time() + seconds_left,
            market_type="updown-15m",
            condition_id="0xabc",
        )

    def test_merge_skipped_when_unprofitable(self):
        engine = self._make_engine(min_merge_profit="0.50")
        market = self._make_market()
        now = time.time()

        # Set up hedged position with thin edge (VWAP sum = 0.99, gross = 0.10)
        engine._inventory._inventory_by_market[market.slug] = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=Decimal("10"),
            up_cost=Decimal("4.95"),  # VWAP = 0.495
            down_cost=Decimal("4.95"),  # VWAP = 0.495
        )
        engine._active_markets = [market]

        merge_called = []
        engine._inventory.reduce_merged = lambda *a: merge_called.append(True)

        engine._check_settlements(now)

        assert len(merge_called) == 0, "Merge should be skipped when gross < min_profit"

    def test_merge_proceeds_when_profitable(self):
        engine = self._make_engine(min_merge_profit="0.02")
        market = self._make_market()
        now = time.time()

        # Set up hedged position with good edge (VWAP sum = 0.90, gross = 1.00)
        engine._inventory._inventory_by_market[market.slug] = MarketInventory(
            up_shares=Decimal("10"),
            down_shares=Decimal("10"),
            up_cost=Decimal("4.50"),  # VWAP = 0.45
            down_cost=Decimal("4.50"),  # VWAP = 0.45
        )
        engine._active_markets = [market]

        engine._check_settlements(now)

        # In dry-run mode, reduce_merged is called directly
        inv = engine._inventory.get_inventory(market.slug)
        # After merge, shares should be 0
        assert inv.up_shares == Decimal("0")
        assert inv.down_shares == Decimal("0")
