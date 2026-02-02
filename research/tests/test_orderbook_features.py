"""
Order Book Feature Tests

Tests for research/data/orderbook_features.py
Follows testing_plan.md philosophy: verify-it-fails assertions.
"""

import pytest
import json
from pathlib import Path

from research.data.orderbook_features import (
    get_executable_price,
    get_executable_price_bid,
    calculate_book_imbalance,
    calculate_vwap_ask,
    calculate_vwap_bid,
    calculate_spread,
    check_dutch_book_opportunity,
)


FIXTURES_DIR = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> dict:
    """Load a JSON test fixture."""
    with open(FIXTURES_DIR / name) as f:
        return json.load(f)


class TestAskBookTraversal:
    """Tests for get_executable_price (ask book traversal)."""

    def test_single_level_sufficient(self):
        """Single level with sufficient liquidity."""
        asks = [(0.50, 100)]  # 100 shares at $0.50
        price = get_executable_price(asks, 50)

        assert price == 0.50
        # Verify-it-fails: different price would be wrong
        assert price == pytest.approx(0.50, abs=1e-6)

    def test_multi_level_fill(self):
        """Fill across multiple levels."""
        asks = [(0.50, 50), (0.51, 50)]  # 50@0.50, 50@0.51
        price = get_executable_price(asks, 80)

        # 50@0.50 + 30@0.51 = 25 + 15.30 = 40.30 / 80 = 0.50375
        expected = (50 * 0.50 + 30 * 0.51) / 80
        assert price == pytest.approx(expected, rel=1e-6)
        # Verify-it-fails: using just best ask would be wrong
        assert price > 0.50

    def test_insufficient_liquidity(self):
        """Not enough liquidity returns partial."""
        asks = [(0.50, 100)]
        price = get_executable_price(asks, 200)

        # Can only fill 100, price is 0.50
        assert price == 0.50

    def test_empty_book(self):
        """Empty book returns None."""
        price = get_executable_price([], 100)

        assert price is None

    def test_unsorted_input(self):
        """Unsorted input should still work correctly."""
        asks = [(0.52, 50), (0.50, 50), (0.51, 50)]  # Out of order
        price = get_executable_price(asks, 80)

        # Should fill 50@0.50 + 30@0.51 (lowest first)
        expected = (50 * 0.50 + 30 * 0.51) / 80
        assert price == pytest.approx(expected, rel=1e-6)


class TestBookImbalance:
    """Tests for calculate_book_imbalance."""

    def test_equal_depth_zero_imbalance(self):
        """Equal bid and ask depth gives zero imbalance."""
        bids = [(99, 500), (98, 500)]  # Total 1000
        asks = [(101, 500), (102, 500)]  # Total 1000

        imbalance = calculate_book_imbalance(bids, asks, levels=2)

        assert imbalance == pytest.approx(0.0, abs=1e-6)

    def test_all_bids_imbalance_one(self):
        """All bids, no asks gives imbalance of 1.0."""
        bids = [(99, 1000)]
        asks = []

        imbalance = calculate_book_imbalance(bids, asks, levels=5)

        assert imbalance == 1.0
        # Verify-it-fails: negative imbalance would be wrong
        assert imbalance > 0

    def test_all_asks_imbalance_negative_one(self):
        """No bids, all asks gives imbalance of -1.0."""
        bids = []
        asks = [(101, 1000)]

        imbalance = calculate_book_imbalance(bids, asks, levels=5)

        assert imbalance == -1.0
        # Verify-it-fails: positive imbalance would be wrong
        assert imbalance < 0

    def test_heavy_bid_positive_imbalance(self):
        """Heavy bids gives positive imbalance."""
        bids = [(99, 800)]
        asks = [(101, 200)]

        imbalance = calculate_book_imbalance(bids, asks, levels=5)

        # (800 - 200) / (800 + 200) = 0.6
        assert imbalance == pytest.approx(0.6, abs=1e-6)


class TestVWAPCalculation:
    """Tests for VWAP calculation."""

    def test_single_level_vwap(self):
        """Single level VWAP equals that level's price."""
        asks = [(0.50, 1000)]
        vwap = calculate_vwap_ask(asks, 500)

        assert vwap == 0.50

    def test_multi_level_vwap(self):
        """Multi-level VWAP is weighted average."""
        asks = [(0.50, 1000), (0.51, 1000)]  # $500 + $510 available
        vwap = calculate_vwap_ask(asks, 600)

        # Fill: 1000 shares @ 0.50 = $500, then 196.08 shares @ 0.51 = $100
        # VWAP = $600 / (1000 + 196.08) = 0.5016...
        assert vwap > 0.50
        assert vwap < 0.51

    def test_depth_exceeds_available(self):
        """Depth exceeds available returns partial."""
        asks = [(0.50, 100)]  # Only $50 available
        vwap = calculate_vwap_ask(asks, 10000)

        # Can only fill what's available
        assert vwap == 0.50


class TestSpreadCalculation:
    """Tests for spread calculation."""

    def test_spread_calculation(self):
        """Spread is ask - bid."""
        spread, spread_bps = calculate_spread(0.49, 0.51)

        assert spread == pytest.approx(0.02, abs=1e-6)
        # Midpoint = 0.50, spread_bps = 0.02 / 0.50 * 10000 = 400
        assert spread_bps == pytest.approx(400.0, rel=1e-6)


class TestDutchBookOpportunity:
    """Tests for Dutch Book detection."""

    def test_clear_opportunity(self):
        """Detect clear Dutch Book opportunity."""
        up_asks = [(0.48, 100)]
        down_asks = [(0.50, 100)]

        is_opp, up_price, down_price, combined = check_dutch_book_opportunity(
            up_asks, down_asks, 50, threshold=0.99
        )

        assert is_opp is True
        assert combined == pytest.approx(0.98, abs=1e-6)
        # Verify-it-fails: no opportunity would be wrong
        assert combined < 1.0

    def test_no_opportunity(self):
        """No opportunity when combined >= threshold."""
        up_asks = [(0.52, 100)]
        down_asks = [(0.52, 100)]

        is_opp, up_price, down_price, combined = check_dutch_book_opportunity(
            up_asks, down_asks, 50, threshold=0.99
        )

        assert is_opp is False
        assert combined == pytest.approx(1.04, abs=1e-6)

    def test_boundary_exactly_one(self):
        """Exactly $1.00 is not an opportunity."""
        up_asks = [(0.50, 100)]
        down_asks = [(0.50, 100)]

        is_opp, _, _, combined = check_dutch_book_opportunity(
            up_asks, down_asks, 50, threshold=0.99
        )

        assert is_opp is False
        # Verify-it-fails: signaling opportunity would be wrong
        assert combined >= 0.99

    def test_boundary_099(self):
        """Just below $0.99 triggers opportunity with default threshold."""
        up_asks = [(0.494, 100)]  # 0.494 + 0.494 = 0.988 < 0.99
        down_asks = [(0.494, 100)]

        is_opp, _, _, combined = check_dutch_book_opportunity(
            up_asks, down_asks, 50, threshold=0.99
        )

        assert is_opp is True
        assert combined < 0.99

    def test_fixture_opportunity(self):
        """Test with fixture data."""
        fixture = load_fixture("dutch_book_opportunity.json")

        up_asks = [(a["price"], a["size"]) for a in fixture["up_book"]["asks"]]
        down_asks = [(a["price"], a["size"]) for a in fixture["down_book"]["asks"]]

        is_opp, up_price, down_price, combined = check_dutch_book_opportunity(
            up_asks, down_asks, 50, threshold=0.99
        )

        expected = fixture["expected_signal"]
        assert is_opp is True
        assert up_price == pytest.approx(expected["up_price"], abs=0.01)
        assert down_price == pytest.approx(expected["down_price"], abs=0.01)
        assert combined == pytest.approx(expected["combined"], abs=0.01)
