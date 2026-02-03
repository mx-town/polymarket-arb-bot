"""
Unit tests for configuration loading.

Tests config parsing, defaults, and validation.
"""

import pytest

from trading.config import (
    TradingConfig,
    PollingConfig,
    WebSocketConfig,
    LagArbConfig,
    RiskConfig,
    FilterConfig,
)


class TestTradingConfig:
    """Tests for TradingConfig defaults and validation"""

    def test_default_values(self):
        """Test default trading config values"""
        config = TradingConfig()

        assert config.dry_run is True
        assert config.min_spread == 0.02
        assert config.min_net_profit == 0.005
        assert config.max_position_size == 100
        assert config.fee_rate == 0.02

    def test_custom_values(self):
        """Test custom trading config values"""
        config = TradingConfig(
            dry_run=False,
            min_spread=0.03,
            max_position_size=500,
        )

        assert config.dry_run is False
        assert config.min_spread == 0.03
        assert config.max_position_size == 500


class TestLagArbConfig:
    """Tests for LagArbConfig"""

    def test_default_candle_interval(self):
        """Test default candle interval is 1h"""
        config = LagArbConfig()
        assert config.candle_interval == "1h"

    def test_custom_candle_interval(self):
        """Test custom candle interval"""
        config = LagArbConfig(candle_interval="15m")
        assert config.candle_interval == "15m"

    def test_default_momentum_threshold(self):
        """Test default momentum threshold"""
        config = LagArbConfig()
        assert config.momentum_trigger_threshold_pct == 0.001  # 0.1%

    def test_default_fee_rate_zero(self):
        """Test 1H markets have 0% fees by default"""
        config = LagArbConfig()
        assert config.fee_rate == 0.0


class TestFilterConfig:
    """Tests for FilterConfig"""

    def test_default_market_types(self):
        """Test default market types"""
        config = FilterConfig()
        assert "btc-updown" in config.market_types or len(config.market_types) > 0

    def test_custom_market_types(self):
        """Test custom market types"""
        config = FilterConfig(market_types=["bitcoin", "ethereum", "solana"])
        assert "bitcoin" in config.market_types
        assert "solana" in config.market_types

    def test_default_volume_filter(self):
        """Test default volume filter"""
        config = FilterConfig()
        assert config.min_volume_24h == 100

    def test_age_filters(self):
        """Test age filter defaults"""
        config = FilterConfig()
        assert config.max_market_age_hours == 1
        assert config.fallback_age_hours == 24


class TestPollingConfig:
    """Tests for PollingConfig"""

    def test_default_interval(self):
        """Test default polling interval"""
        config = PollingConfig()
        assert config.interval == 5

    def test_default_refresh_interval(self):
        """Test default market refresh interval"""
        config = PollingConfig()
        assert config.market_refresh_interval == 300


class TestWebSocketConfig:
    """Tests for WebSocketConfig"""

    def test_default_ping_interval(self):
        """Test default ping interval"""
        config = WebSocketConfig()
        assert config.ping_interval == 30.0

    def test_default_reconnect_delay(self):
        """Test default reconnect delay"""
        config = WebSocketConfig()
        assert config.reconnect_delay == 5.0


class TestRiskConfig:
    """Tests for RiskConfig"""

    def test_default_loss_limits(self):
        """Test default loss limits"""
        config = RiskConfig()
        assert config.max_consecutive_losses == 3
        assert config.max_daily_loss_usd == 100

    def test_default_cooldown(self):
        """Test default cooldown period"""
        config = RiskConfig()
        assert config.cooldown_after_loss_sec == 300

    def test_default_exposure_limit(self):
        """Test default exposure limit"""
        config = RiskConfig()
        assert config.max_total_exposure == 1000


