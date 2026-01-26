"""
Unit tests for market state management.

Tests MarketState and MarketStateManager without network calls.
"""

import pytest
from datetime import datetime, timedelta, UTC

from src.market.state import MarketState, MarketStateManager, MarketStatus


class TestMarketState:
    """Tests for MarketState dataclass"""

    def test_create_market_state(self):
        """Test basic market state creation"""
        state = MarketState(
            market_id="0xabc123",
            slug="bitcoin-up-or-down",
            question="Bitcoin Up or Down?",
            up_token_id="token1",
            down_token_id="token2",
        )

        assert state.market_id == "0xabc123"
        assert state.slug == "bitcoin-up-or-down"
        assert state.up_token_id == "token1"
        assert state.down_token_id == "token2"

    def test_market_state_with_resolution_time(self):
        """Test market state with resolution time"""
        resolution = datetime.now(UTC) + timedelta(hours=1)
        state = MarketState(
            market_id="0xabc123",
            slug="test",
            question="Test?",
            up_token_id="t1",
            down_token_id="t2",
            resolution_time=resolution,
        )

        assert state.resolution_time == resolution

    def test_market_state_default_status(self):
        """Test that default status is ACTIVE"""
        state = MarketState(
            market_id="0xabc123",
            slug="test",
            question="Test?",
            up_token_id="t1",
            down_token_id="t2",
        )

        assert state.status == MarketStatus.ACTIVE


class TestMarketStateManager:
    """Tests for MarketStateManager"""

    @pytest.fixture
    def manager(self):
        """Create a fresh manager for each test"""
        return MarketStateManager()

    @pytest.fixture
    def sample_market(self):
        """Sample market state for testing"""
        return MarketState(
            market_id="0xabc123",
            slug="bitcoin-up-or-down",
            question="Bitcoin Up or Down?",
            up_token_id="token1",
            down_token_id="token2",
        )

    def test_add_market(self, manager, sample_market):
        """Test adding a market"""
        manager.add_market(sample_market)

        assert len(manager.markets) == 1
        assert sample_market.market_id in manager.markets

    def test_get_market(self, manager, sample_market):
        """Test retrieving a market by ID"""
        manager.add_market(sample_market)

        retrieved = manager.get_market(sample_market.market_id)
        assert retrieved == sample_market

    def test_get_nonexistent_market(self, manager):
        """Test retrieving non-existent market returns None"""
        assert manager.get_market("nonexistent") is None

    def test_remove_market(self, manager, sample_market):
        """Test removing a market"""
        manager.add_market(sample_market)
        manager.remove_market(sample_market.market_id)

        assert len(manager.markets) == 0

    def test_get_all_token_ids(self, manager):
        """Test getting all token IDs"""
        market1 = MarketState(
            market_id="m1",
            slug="test1",
            question="Test1?",
            up_token_id="up1",
            down_token_id="down1",
        )
        market2 = MarketState(
            market_id="m2",
            slug="test2",
            question="Test2?",
            up_token_id="up2",
            down_token_id="down2",
        )

        manager.add_market(market1)
        manager.add_market(market2)

        token_ids = manager.get_all_token_ids()

        assert len(token_ids) == 4
        assert "up1" in token_ids
        assert "down1" in token_ids
        assert "up2" in token_ids
        assert "down2" in token_ids

    def test_get_market_by_token(self, manager, sample_market):
        """Test finding market by token ID"""
        manager.add_market(sample_market)

        # Find by up token
        found_up = manager.get_market_by_token("token1")
        assert found_up == sample_market

        # Find by down token
        found_down = manager.get_market_by_token("token2")
        assert found_down == sample_market

    def test_get_market_by_nonexistent_token(self, manager, sample_market):
        """Test finding market by non-existent token returns None"""
        manager.add_market(sample_market)

        assert manager.get_market_by_token("nonexistent") is None

    def test_update_from_book(self, manager, sample_market):
        """Test updating prices from order book"""
        manager.add_market(sample_market)

        manager.update_from_book(
            token_id="token1",  # up token
            best_bid=0.52,
            best_ask=0.54,
            bid_size=1000,
            ask_size=800,
        )

        market = manager.get_market(sample_market.market_id)
        assert market.up_best_bid == 0.52
        assert market.up_best_ask == 0.54

    def test_multiple_markets(self, manager):
        """Test managing multiple markets"""
        for i in range(5):
            market = MarketState(
                market_id=f"market_{i}",
                slug=f"test-{i}",
                question=f"Test {i}?",
                up_token_id=f"up_{i}",
                down_token_id=f"down_{i}",
            )
            manager.add_market(market)

        assert len(manager.markets) == 5
        assert len(manager.get_all_token_ids()) == 10


class TestMarketStatus:
    """Tests for MarketStatus enum"""

    def test_status_values(self):
        """Test all status values exist"""
        assert MarketStatus.ACTIVE is not None
        assert MarketStatus.CLOSED is not None
        assert MarketStatus.RESOLVED is not None
