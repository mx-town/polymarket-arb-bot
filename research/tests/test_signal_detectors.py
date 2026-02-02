"""
Signal Detector Tests

Tests for research/signals/detectors.py
Follows testing_plan.md philosophy: verify-it-fails assertions.
"""

import pytest

from research.signals.detectors import (
    SignalType,
    Signal,
    DutchBookDetector,
    LagArbDetector,
    MomentumDetector,
    FlashCrashDetector,
)


class TestDutchBookDetector:
    """Tests for Dutch Book detection."""

    def test_clear_opportunity_triggers(self):
        """Clear opportunity (UP=$0.48, DOWN=$0.50) should trigger."""
        detector = DutchBookDetector(threshold=0.99)

        signal = detector.detect(
            up_executable_price=0.48,
            down_executable_price=0.50,
            timestamp_ms=1700000000000,
            time_remaining_sec=300,
            session="us_eu_overlap"
        )

        assert signal is not None
        assert signal.signal_type == SignalType.DUTCH_BOOK
        assert signal.combined_price == pytest.approx(0.98, abs=1e-6)
        assert signal.expected_edge == pytest.approx(0.02, abs=1e-6)
        # Verify-it-fails: no signal would be wrong
        assert signal.confidence == 1.0  # Zero risk

    def test_no_opportunity_no_signal(self):
        """No opportunity (UP=$0.52, DOWN=$0.52) should not trigger."""
        detector = DutchBookDetector(threshold=0.99)

        signal = detector.detect(
            up_executable_price=0.52,
            down_executable_price=0.52,
            timestamp_ms=1700000000000,
            time_remaining_sec=300,
            session="us"
        )

        assert signal is None
        # Verify-it-fails: signal would be wrong

    def test_boundary_exactly_099_no_signal(self):
        """Exactly at threshold should not trigger."""
        detector = DutchBookDetector(threshold=0.99)

        signal = detector.detect(
            up_executable_price=0.50,
            down_executable_price=0.49,
            timestamp_ms=1700000000000,
            time_remaining_sec=300,
            session="us"
        )

        # 0.50 + 0.49 = 0.99, not less than threshold
        assert signal is None

    def test_boundary_just_below_triggers(self):
        """Just below threshold should trigger."""
        detector = DutchBookDetector(threshold=0.99, min_profit_pct=0.001)

        signal = detector.detect(
            up_executable_price=0.495,
            down_executable_price=0.494,
            timestamp_ms=1700000000000,
            time_remaining_sec=300,
            session="us"
        )

        # 0.495 + 0.494 = 0.989 < 0.99
        assert signal is not None


class TestLagArbDetector:
    """Tests for Lag Arbitrage detection."""

    def test_binance_leads_up_triggers(self):
        """Binance leading up (>0.1% sustained) should trigger LAG_ARB_UP."""
        detector = LagArbDetector(
            deviation_threshold=0.001,  # 0.1%
            min_duration_ms=500,
            max_combined_price=0.995,
            min_edge_threshold=0.01
        )

        open_price = 50000.0
        binance_price = 50100.0  # +0.2%
        chainlink_price = 50000.0  # Flat

        # First call to establish lag
        detector.detect(
            binance_price=binance_price,
            chainlink_price=chainlink_price,
            open_price=open_price,
            up_price=0.50,
            down_price=0.49,
            timestamp_ms=1700000000000,
            time_remaining_sec=300,
            model_prob_up=0.55
        )

        # Second call after 500ms
        signal = detector.detect(
            binance_price=binance_price,
            chainlink_price=chainlink_price,
            open_price=open_price,
            up_price=0.50,
            down_price=0.49,
            timestamp_ms=1700000000500,  # 500ms later
            time_remaining_sec=300,
            model_prob_up=0.55
        )

        assert signal is not None
        assert signal.signal_type == SignalType.LAG_ARB_UP
        # Verify-it-fails: DOWN signal would be wrong
        assert signal.signal_type != SignalType.LAG_ARB_DOWN

    def test_binance_leads_down_triggers(self):
        """Binance leading down should trigger LAG_ARB_DOWN."""
        detector = LagArbDetector(
            deviation_threshold=0.001,
            min_duration_ms=500,
            min_edge_threshold=0.01
        )

        open_price = 50000.0
        binance_price = 49900.0  # -0.2%
        chainlink_price = 50000.0

        detector.detect(
            binance_price=binance_price,
            chainlink_price=chainlink_price,
            open_price=open_price,
            up_price=0.50,
            down_price=0.49,
            timestamp_ms=1700000000000,
            time_remaining_sec=300,
            model_prob_up=0.45
        )

        signal = detector.detect(
            binance_price=binance_price,
            chainlink_price=chainlink_price,
            open_price=open_price,
            up_price=0.50,
            down_price=0.49,
            timestamp_ms=1700000000500,
            time_remaining_sec=300,
            model_prob_up=0.45
        )

        assert signal is not None
        assert signal.signal_type == SignalType.LAG_ARB_DOWN

    def test_no_significant_lag_no_signal(self):
        """No significant lag (<0.1%) should not trigger."""
        detector = LagArbDetector(deviation_threshold=0.001)

        signal = detector.detect(
            binance_price=50000.0,
            chainlink_price=50000.0,  # No lag
            open_price=50000.0,
            up_price=0.50,
            down_price=0.49,
            timestamp_ms=1700000000000,
            time_remaining_sec=300
        )

        assert signal is None

    def test_lag_not_sustained_no_signal(self):
        """Lag not sustained (< min_duration) should not trigger."""
        detector = LagArbDetector(
            deviation_threshold=0.001,
            min_duration_ms=500
        )

        signal = detector.detect(
            binance_price=50100.0,  # +0.2%
            chainlink_price=50000.0,
            open_price=50000.0,
            up_price=0.50,
            down_price=0.49,
            timestamp_ms=1700000000000,
            time_remaining_sec=300
        )

        # First call, not sustained yet
        assert signal is None


class TestMomentumDetector:
    """Tests for Momentum detection."""

    def test_strong_up_momentum_triggers(self):
        """Strong up momentum with confirmation should trigger."""
        detector = MomentumDetector(
            velocity_threshold=0.001,
            min_book_imbalance=0.3,
            min_time_remaining_sec=60,
            require_positive_acceleration=True,
            min_edge_threshold=0.01
        )

        signal = detector.detect(
            velocity=0.002,  # Above threshold
            acceleration=0.0001,  # Positive (accelerating)
            book_imbalance=0.5,  # Strong buy pressure
            deviation_pct=0.005,
            up_price=0.50,
            down_price=0.49,
            timestamp_ms=1700000000000,
            time_remaining_sec=300,
            model_prob_up=0.60
        )

        assert signal is not None
        assert signal.signal_type == SignalType.MOMENTUM_UP
        # Verify-it-fails: DOWN signal would be wrong
        assert signal.signal_type != SignalType.MOMENTUM_DOWN

    def test_velocity_without_imbalance_no_signal(self):
        """Velocity without book imbalance confirmation should not trigger."""
        detector = MomentumDetector(
            velocity_threshold=0.001,
            min_book_imbalance=0.3
        )

        signal = detector.detect(
            velocity=0.002,  # Above threshold
            acceleration=0.0001,
            book_imbalance=0.1,  # Below threshold
            deviation_pct=0.005,
            up_price=0.50,
            down_price=0.49,
            timestamp_ms=1700000000000,
            time_remaining_sec=300
        )

        assert signal is None

    def test_decelerating_no_signal(self):
        """Decelerating momentum should not trigger."""
        detector = MomentumDetector(
            velocity_threshold=0.001,
            require_positive_acceleration=True
        )

        signal = detector.detect(
            velocity=0.002,  # Above threshold
            acceleration=-0.0001,  # Decelerating
            book_imbalance=0.5,
            deviation_pct=0.005,
            up_price=0.50,
            down_price=0.49,
            timestamp_ms=1700000000000,
            time_remaining_sec=300
        )

        assert signal is None

    def test_too_close_to_resolution_no_signal(self):
        """Too close to resolution should not trigger."""
        detector = MomentumDetector(
            min_time_remaining_sec=60
        )

        signal = detector.detect(
            velocity=0.002,
            acceleration=0.0001,
            book_imbalance=0.5,
            deviation_pct=0.005,
            up_price=0.50,
            down_price=0.49,
            timestamp_ms=1700000000000,
            time_remaining_sec=30  # Too close
        )

        assert signal is None


class TestFlashCrashDetector:
    """Tests for Flash Crash detection."""

    def test_30_percent_drop_triggers(self):
        """30% drop in 10 seconds should trigger."""
        detector = FlashCrashDetector(
            drop_threshold=0.30,
            window_sec=10
        )

        # Build up history
        base_time = 1700000000000
        for i in range(10):
            # UP price starts at 0.50, crashes to 0.35 (30% drop)
            if i < 5:
                up_price = 0.50
            else:
                up_price = 0.35  # Crash at i=5
            detector.update(up_price, 0.50, base_time + i * 1000)

        # Check at i=10 (after 10 seconds)
        signal = detector.detect(
            up_price=0.35,
            down_price=0.50,
            timestamp_ms=base_time + 10000,
            time_remaining_sec=300
        )

        assert signal is not None
        assert signal.signal_type == SignalType.FLASH_CRASH_UP
        # Verify-it-fails: no signal would miss the opportunity
        assert signal.metadata["drop_pct"] >= 0.30

    def test_20_percent_drop_no_signal(self):
        """20% drop (below threshold) should not trigger."""
        detector = FlashCrashDetector(drop_threshold=0.30)

        base_time = 1700000000000
        for i in range(10):
            if i < 5:
                up_price = 0.50
            else:
                up_price = 0.40  # Only 20% drop
            detector.update(up_price, 0.50, base_time + i * 1000)

        signal = detector.detect(
            up_price=0.40,
            down_price=0.50,
            timestamp_ms=base_time + 10000,
            time_remaining_sec=300
        )

        assert signal is None

    def test_small_gradual_decline_no_signal(self):
        """Small gradual decline (5% over 10s) should not trigger."""
        detector = FlashCrashDetector(
            drop_threshold=0.30,  # Need 30% drop
            window_sec=10
        )

        base_time = 1700000000000
        # Small gradual decline - only 5% over 10 seconds
        for i in range(11):
            # Price drops from 0.50 to 0.475 (5% drop)
            up_price = 0.50 - (0.025 * i / 10)
            detector.update(up_price, 0.50, base_time + i * 1000)

        signal = detector.detect(
            up_price=0.475,
            down_price=0.50,
            timestamp_ms=base_time + 10000,
            time_remaining_sec=300
        )

        # 5% drop is below 30% threshold
        assert signal is None
