"""Shared fixtures for complete-set strategy tests."""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from complete_set.config import CompleteSetConfig
from complete_set.models import Direction, GabagoolMarket, MarketInventory, OrderState

ZERO = Decimal("0")


@pytest.fixture
def default_cfg() -> CompleteSetConfig:
    return CompleteSetConfig(
        enabled=True,
        dry_run=True,
        refresh_millis=500,
        assets=("bitcoin",),
        min_seconds_to_end=0,
        max_seconds_to_end=900,
        no_new_orders_sec=90,
        min_edge=Decimal("0.01"),
        bankroll_usd=Decimal("30"),
        min_merge_shares=Decimal("10"),
        min_merge_profit_usd=Decimal("0.02"),
        max_gas_price_gwei=200,
    )


@pytest.fixture
def sample_market() -> GabagoolMarket:
    return GabagoolMarket(
        slug="btc-updown-15m-2026-02-14-1200",
        up_token_id="111111",
        down_token_id="222222",
        end_time=time.time() + 600,
        market_type="updown-15m",
        condition_id="0xabc123",
        neg_risk=False,
    )


@pytest.fixture
def sample_inventory() -> MarketInventory:
    return MarketInventory(
        up_shares=Decimal("10"),
        down_shares=Decimal("8"),
        up_cost=Decimal("4.50"),
        down_cost=Decimal("3.60"),
        filled_up_shares=Decimal("10"),
        filled_down_shares=Decimal("8"),
    )


@pytest.fixture
def empty_inventory() -> MarketInventory:
    return MarketInventory()


@pytest.fixture
def sample_order_state(sample_market) -> OrderState:
    return OrderState(
        order_id="order-123",
        market=sample_market,
        token_id="111111",
        direction=Direction.UP,
        price=Decimal("0.45"),
        size=Decimal("10"),
        placed_at=time.time(),
        side="BUY",
    )
