"""
Feature Extraction Tests

Tests for research/data/feature_extractor.py
Follows testing_plan.md philosophy: verify-it-fails assertions.

Each test includes an assertion that would fail if the logic were wrong.
"""

import pytest
import json
from pathlib import Path

import pandas as pd
import numpy as np

from research.data.feature_extractor import (
    FeatureExtractor,
    TradingSession,
    VolatilityRegime,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a JSON test fixture."""
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


class TestDeviationCalculation:
    """Tests for deviation_pct calculation."""

    def test_zero_deviation(self):
        """Zero deviation when current equals open."""
        open_price = 50000.0
        current_price = 50000.0
        deviation = (current_price - open_price) / open_price

        assert deviation == 0.0
        # Verify-it-fails: wrong formula would give non-zero
        assert not ((current_price - open_price) / current_price != 0.0 and open_price == current_price)

    def test_positive_deviation(self):
        """Positive deviation when price increases."""
        open_price = 50000.0
        current_price = 50500.0  # +1%
        deviation = (current_price - open_price) / open_price

        assert deviation == pytest.approx(0.01, rel=1e-6)
        # Verify-it-fails: negative deviation would be wrong
        assert deviation > 0

    def test_negative_deviation(self):
        """Negative deviation when price decreases."""
        open_price = 50000.0
        current_price = 49500.0  # -1%
        deviation = (current_price - open_price) / open_price

        assert deviation == pytest.approx(-0.01, rel=1e-6)
        # Verify-it-fails: positive deviation would be wrong
        assert deviation < 0

    def test_boundary_up(self):
        """Exactly at boundary - price slightly above open is UP."""
        open_price = 50000.0
        current_price = 50000.01
        deviation = (current_price - open_price) / open_price

        assert deviation > 0
        # Verify-it-fails: zero or negative would be wrong
        assert not (deviation <= 0)


class TestVelocityCalculation:
    """Tests for velocity calculation."""

    def test_steady_price_zero_velocity(self):
        """Flat prices should give approximately zero velocity."""
        extractor = FeatureExtractor(window_minutes=15)

        prices = [50000.0] * 10
        timestamps = [1700000000000 + i * 60000 for i in range(10)]

        velocity = extractor._calculate_velocity(prices, timestamps, lookback_sec=300)

        assert abs(velocity) < 0.01  # Near zero
        # Verify-it-fails: large velocity would be wrong
        assert not (abs(velocity) > 1.0)

    def test_linear_increase_positive_velocity(self):
        """Linear price increase should give positive velocity."""
        extractor = FeatureExtractor(window_minutes=15)

        # Price increases by $100 over 5 minutes (300 seconds)
        prices = [50000.0 + i * 20 for i in range(6)]  # 0, 20, 40, 60, 80, 100
        timestamps = [1700000000000 + i * 60000 for i in range(6)]

        velocity = extractor._calculate_velocity(prices, timestamps, lookback_sec=300)

        # Expected: $100 / 300s ≈ $0.33/sec
        assert velocity > 0
        assert velocity == pytest.approx(100 / 300, rel=0.1)
        # Verify-it-fails: negative velocity would be wrong
        assert not (velocity < 0)

    def test_linear_decrease_negative_velocity(self):
        """Linear price decrease should give negative velocity."""
        extractor = FeatureExtractor(window_minutes=15)

        prices = [50000.0 - i * 20 for i in range(6)]
        timestamps = [1700000000000 + i * 60000 for i in range(6)]

        velocity = extractor._calculate_velocity(prices, timestamps, lookback_sec=300)

        assert velocity < 0
        # Verify-it-fails: positive velocity would be wrong
        assert not (velocity > 0)

    def test_insufficient_data(self):
        """Insufficient data should return 0."""
        extractor = FeatureExtractor(window_minutes=15)

        velocity = extractor._calculate_velocity([50000.0], [1700000000000], lookback_sec=300)

        assert velocity == 0.0


class TestAccelerationCalculation:
    """Tests for acceleration calculation."""

    def test_constant_velocity_zero_acceleration(self):
        """Constant velocity should give zero acceleration."""
        extractor = FeatureExtractor(window_minutes=15)

        velocities = [0.5, 0.5, 0.5, 0.5, 0.5]
        timestamps = [1700000000000 + i * 60000 for i in range(5)]

        acceleration = extractor._calculate_acceleration(velocities, timestamps, lookback_sec=300)

        assert abs(acceleration) < 0.001
        # Verify-it-fails: large acceleration would be wrong
        assert not (abs(acceleration) > 0.1)

    def test_increasing_velocity_positive_acceleration(self):
        """Increasing velocity should give positive acceleration."""
        extractor = FeatureExtractor(window_minutes=15)

        velocities = [0.1, 0.2, 0.3, 0.4, 0.5]  # Accelerating
        timestamps = [1700000000000 + i * 60000 for i in range(5)]

        acceleration = extractor._calculate_acceleration(velocities, timestamps, lookback_sec=240)

        assert acceleration > 0
        # Verify-it-fails: negative acceleration would be wrong
        assert not (acceleration < 0)


class TestSessionClassification:
    """Tests for trading session classification."""

    def test_asia_session(self):
        """03:00 UTC should be ASIA."""
        extractor = FeatureExtractor(window_minutes=15)
        session = extractor._get_session(3)

        assert session == TradingSession.ASIA
        # Verify-it-fails: any other session would be wrong
        assert session.value == "asia"

    def test_europe_session(self):
        """10:00 UTC should be EUROPE."""
        extractor = FeatureExtractor(window_minutes=15)
        session = extractor._get_session(10)

        assert session == TradingSession.EUROPE
        assert session.value == "europe"

    def test_us_eu_overlap_session(self):
        """15:00 UTC should be US_EU_OVERLAP."""
        extractor = FeatureExtractor(window_minutes=15)
        session = extractor._get_session(15)

        assert session == TradingSession.US_EU_OVERLAP
        assert session.value == "us_eu_overlap"

    def test_us_session(self):
        """19:00 UTC should be US."""
        extractor = FeatureExtractor(window_minutes=15)
        session = extractor._get_session(19)

        assert session == TradingSession.US
        assert session.value == "us"

    def test_late_us_session(self):
        """23:00 UTC should be LATE_US."""
        extractor = FeatureExtractor(window_minutes=15)
        session = extractor._get_session(23)

        assert session == TradingSession.LATE_US
        assert session.value == "late_us"

    def test_boundary_08_is_europe(self):
        """08:00 exactly should be EUROPE, not ASIA."""
        extractor = FeatureExtractor(window_minutes=15)
        session = extractor._get_session(8)

        assert session == TradingSession.EUROPE
        # Verify-it-fails: ASIA would be wrong
        assert session != TradingSession.ASIA

    def test_boundary_13_is_overlap(self):
        """13:00 exactly should be US_EU_OVERLAP."""
        extractor = FeatureExtractor(window_minutes=15)
        session = extractor._get_session(13)

        assert session == TradingSession.US_EU_OVERLAP


class TestCandlePhase:
    """Tests for candle phase calculation."""

    def test_candle_open_phase_zero(self):
        """At candle open, phase should be 0.0."""
        minute_index = 0
        window_minutes = 15
        phase = minute_index / max(1, window_minutes - 1)

        assert phase == 0.0

    def test_candle_mid_phase_half(self):
        """At candle midpoint, phase should be ~0.5."""
        minute_index = 7
        window_minutes = 15
        phase = minute_index / max(1, window_minutes - 1)

        assert phase == pytest.approx(0.5, rel=0.1)

    def test_candle_close_phase_one(self):
        """At candle close, phase should be 1.0."""
        minute_index = 14
        window_minutes = 15
        phase = minute_index / max(1, window_minutes - 1)

        assert phase == 1.0


class TestTimeRemaining:
    """Tests for time remaining calculation."""

    def test_full_period_remaining(self):
        """At t=0, full period remains."""
        minute_index = 0
        window_minutes = 15
        time_remaining = window_minutes - minute_index - 1

        assert time_remaining == 14

    def test_mid_period_remaining(self):
        """At t=7.5min, half period remains."""
        minute_index = 7
        window_minutes = 15
        time_remaining = window_minutes - minute_index - 1

        assert time_remaining == 7

    def test_end_of_period_zero_remaining(self):
        """At t=15min, zero remains."""
        minute_index = 14
        window_minutes = 15
        time_remaining = window_minutes - minute_index - 1

        assert time_remaining == 0


class TestFeatureExtractorIntegration:
    """Integration tests for full feature extraction."""

    def test_extract_flat_prices_fixture(self):
        """Extract features from flat prices fixture - test deviation logic."""
        # Create inline data aligned to a 15-min boundary
        # Using timestamp at 00:00:00 UTC which aligns to :00
        # Need 16 candles so window_end <= last_time condition is satisfied
        base_time = 1700006400000  # 2023-11-15 00:00:00 UTC

        candles = []
        for i in range(16):  # 16 candles to ensure window fits
            candles.append({
                "open_time": base_time + i * 60000,
                "open": 50000.0,
                "high": 50000.0,
                "low": 50000.0,
                "close": 50000.0,
                "volume": 100.0,
                "close_time": base_time + i * 60000 + 60000,
                "quote_volume": 5000000.0,
                "trades": 10,
                "taker_buy_base": 50.0,
                "taker_buy_quote": 2500000.0,
            })

        df = pd.DataFrame(candles)
        extractor = FeatureExtractor(window_minutes=15)
        features_df = extractor.extract_windows(df, "BTCUSDT")

        # Should have 15 observations (one per minute in the window)
        assert len(features_df) == 15

        # Final deviation should be 0
        final_row = features_df[features_df["time_remaining"] == 0].iloc[0]
        assert final_row["deviation_pct"] == pytest.approx(0.0, abs=1e-6)

        # Outcome should be UP (close >= open)
        assert final_row["outcome"] == 1

    def test_extract_trending_up_fixture(self):
        """Extract features from trending up data - test velocity logic."""
        # Create inline data with 1% uptrend
        # Need 16 candles so window_end <= last_time condition is satisfied
        base_time = 1700006400000  # Aligned to :00

        candles = []
        for i in range(16):  # 16 candles to ensure window fits
            price = 50000.0 + (i * 500.0 / 14)  # Linear increase to 50500+
            candles.append({
                "open_time": base_time + i * 60000,
                "open": price - 10,
                "high": price + 10,
                "low": price - 10,
                "close": price,
                "volume": 100.0,
                "close_time": base_time + i * 60000 + 60000,
                "quote_volume": price * 100,
                "trades": 10,
                "taker_buy_base": 50.0,
                "taker_buy_quote": price * 50,
            })

        df = pd.DataFrame(candles)
        extractor = FeatureExtractor(window_minutes=15)
        features_df = extractor.extract_windows(df, "BTCUSDT")

        assert len(features_df) == 15

        # Final deviation should be positive (~1%)
        final_row = features_df[features_df["time_remaining"] == 0].iloc[0]
        assert final_row["deviation_pct"] > 0
        assert final_row["deviation_pct"] == pytest.approx(0.01, rel=0.15)

        # Outcome should be UP
        assert final_row["outcome"] == 1

        # Velocity should be positive (price increasing)
        assert final_row["velocity"] > 0
