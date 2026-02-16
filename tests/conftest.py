"""Shared fixtures for grid-maker and order_mgr tests."""

from __future__ import annotations

import time
from decimal import Decimal

import pytest

from shared.models import Direction, GabagoolMarket, OrderState

ZERO = Decimal("0")


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
