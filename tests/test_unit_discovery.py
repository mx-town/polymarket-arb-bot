"""
Unit tests for market discovery logic.

Tests filtering, parsing, and event-based market discovery without network calls.
"""

import pytest
from datetime import datetime, timedelta, UTC
from unittest.mock import patch, MagicMock

from src.market.discovery import (
    parse_json_field,
    parse_datetime,
    fetch_updown_events,
    fetch_recent_updown_markets,
    INTERVAL_TO_RECURRENCE,
    ASSET_ALIASES,
    DEFAULT_ASSETS,
)


class TestParseJsonField:
    """Tests for parse_json_field helper"""

    def test_none_returns_empty_list(self):
        assert parse_json_field(None) == []

    def test_list_returns_as_is(self):
        data = ["a", "b", "c"]
        assert parse_json_field(data) == data

    def test_json_string_returns_parsed(self):
        json_str = '["token1", "token2"]'
        assert parse_json_field(json_str) == ["token1", "token2"]

    def test_invalid_json_returns_empty_list(self):
        assert parse_json_field("not valid json") == []

    def test_number_returns_empty_list(self):
        assert parse_json_field(123) == []


class TestParseDatetime:
    """Tests for parse_datetime helper"""

    def test_none_returns_none(self):
        assert parse_datetime(None) is None

    def test_iso_format_with_z(self):
        result = parse_datetime("2026-01-26T19:00:00Z")
        assert result is not None
        assert result.year == 2026
        assert result.month == 1
        assert result.day == 26

    def test_iso_format_with_offset(self):
        result = parse_datetime("2026-01-26T19:00:00+00:00")
        assert result is not None
        assert result.hour == 19

    def test_invalid_returns_none(self):
        assert parse_datetime("not a date") is None


class TestIntervalMapping:
    """Tests for candle interval to recurrence mapping"""

    def test_1h_maps_to_hourly(self):
        assert INTERVAL_TO_RECURRENCE["1h"] == "hourly"

    def test_15m_maps_correctly(self):
        assert INTERVAL_TO_RECURRENCE["15m"] == "15m"

    def test_5m_maps_correctly(self):
        assert INTERVAL_TO_RECURRENCE["5m"] == "5m"


class TestAssetAliases:
    """Tests for asset alias mappings"""

    def test_bitcoin_aliases(self):
        assert "bitcoin" in ASSET_ALIASES["bitcoin"]
        assert "btc" in ASSET_ALIASES["bitcoin"]

    def test_ethereum_aliases(self):
        assert "ethereum" in ASSET_ALIASES["ethereum"]
        assert "eth" in ASSET_ALIASES["ethereum"]

    def test_solana_aliases(self):
        assert "solana" in ASSET_ALIASES["solana"]
        assert "sol" in ASSET_ALIASES["solana"]


class TestFetchUpdownEvents:
    """Tests for fetch_updown_events with mocked API"""

    @pytest.fixture
    def mock_events_response(self):
        """Sample events API response"""
        return [
            {
                "slug": "bitcoin-up-or-down-january-26-1pm-et",
                "title": "Bitcoin Up or Down - January 26, 1PM ET",
                "endDate": "2026-01-26T19:00:00Z",
                "series": [{"slug": "btc-up-or-down-hourly", "recurrence": "hourly"}],
                "markets": [
                    {
                        "conditionId": "0xabc123",
                        "slug": "bitcoin-up-or-down-january-26-1pm-et",
                        "question": "Bitcoin Up or Down - January 26, 1PM ET",
                        "clobTokenIds": '["token1", "token2"]',
                        "outcomes": '["Up", "Down"]',
                        "endDate": "2026-01-26T19:00:00Z",
                        "acceptingOrders": True,
                        "volume24hr": 50000,
                    }
                ],
            },
            {
                "slug": "ethereum-up-or-down-january-26-1pm-et",
                "title": "Ethereum Up or Down - January 26, 1PM ET",
                "endDate": "2026-01-26T19:00:00Z",
                "series": [{"slug": "eth-up-or-down-hourly", "recurrence": "hourly"}],
                "markets": [
                    {
                        "conditionId": "0xdef456",
                        "slug": "ethereum-up-or-down-january-26-1pm-et",
                        "question": "Ethereum Up or Down - January 26, 1PM ET",
                        "clobTokenIds": '["token3", "token4"]',
                        "outcomes": '["Up", "Down"]',
                        "endDate": "2026-01-26T19:00:00Z",
                        "acceptingOrders": True,
                        "volume24hr": 30000,
                    }
                ],
            },
            {
                "slug": "btc-updown-15m-1769540400",
                "title": "BTC Up or Down 15m",
                "endDate": "2026-01-26T19:15:00Z",
                "series": [{"slug": "btc-up-or-down-15m", "recurrence": "15m"}],
                "markets": [
                    {
                        "conditionId": "0x15m123",
                        "slug": "btc-updown-15m-1769540400",
                        "clobTokenIds": '["token5", "token6"]',
                        "outcomes": '["Up", "Down"]',
                        "endDate": "2026-01-26T19:15:00Z",
                    }
                ],
            },
            {
                # Non-updown event should be filtered out
                "slug": "some-other-market",
                "title": "Some Other Market",
                "series": [],
                "markets": [],
            },
        ]

    @patch("src.market.discovery.requests.get")
    def test_filters_by_candle_interval_1h(self, mock_get, mock_events_response):
        """Test that 1h interval only returns hourly markets"""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_events_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        markets = fetch_updown_events(candle_interval="1h", assets=["bitcoin"])

        assert len(markets) == 1
        assert markets[0]["slug"] == "bitcoin-up-or-down-january-26-1pm-et"
        assert markets[0]["condition_id"] == "0xabc123"

    @patch("src.market.discovery.requests.get")
    def test_filters_by_candle_interval_15m(self, mock_get, mock_events_response):
        """Test that 15m interval only returns 15m markets"""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_events_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        markets = fetch_updown_events(candle_interval="15m", assets=["bitcoin"])

        assert len(markets) == 1
        assert "15m" in markets[0]["slug"]

    @patch("src.market.discovery.requests.get")
    def test_filters_by_asset(self, mock_get, mock_events_response):
        """Test that only requested assets are returned"""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_events_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        markets = fetch_updown_events(candle_interval="1h", assets=["ethereum"])

        assert len(markets) == 1
        assert "ethereum" in markets[0]["slug"]

    @patch("src.market.discovery.requests.get")
    def test_extracts_token_ids(self, mock_get, mock_events_response):
        """Test that token IDs are correctly extracted"""
        mock_response = MagicMock()
        mock_response.json.return_value = mock_events_response
        mock_response.raise_for_status = MagicMock()
        mock_get.return_value = mock_response

        markets = fetch_updown_events(candle_interval="1h", assets=["bitcoin"])

        assert markets[0]["yes_token"] == "token1"
        assert markets[0]["no_token"] == "token2"

    @patch("src.market.discovery.requests.get")
    def test_handles_api_error(self, mock_get):
        """Test graceful handling of API errors"""
        import requests

        mock_get.side_effect = requests.RequestException("API error")

        markets = fetch_updown_events(candle_interval="1h")

        assert markets == []


class TestFetchRecentUpdownMarkets:
    """Tests for fetch_recent_updown_markets"""

    @patch("src.market.discovery.fetch_updown_events")
    def test_converts_legacy_market_types(self, mock_fetch):
        """Test that legacy market_types are converted to assets"""
        mock_fetch.return_value = []

        fetch_recent_updown_markets(
            market_types=["bitcoin", "ethereum"],
            candle_interval="1h",
        )

        call_args = mock_fetch.call_args
        assert "bitcoin" in call_args.kwargs["assets"]
        assert "ethereum" in call_args.kwargs["assets"]

    @patch("src.market.discovery.fetch_updown_events")
    def test_passes_candle_interval(self, mock_fetch):
        """Test that candle_interval is passed through"""
        mock_fetch.return_value = []

        fetch_recent_updown_markets(candle_interval="15m")

        call_args = mock_fetch.call_args
        assert call_args.kwargs["candle_interval"] == "15m"

    @patch("src.market.discovery.fetch_updown_events")
    def test_filters_expired_markets(self, mock_fetch):
        """Test that expired markets are filtered out"""
        now = datetime.now(UTC)
        expired = (now - timedelta(hours=1)).isoformat()
        future = (now + timedelta(minutes=30)).isoformat()

        mock_fetch.return_value = [
            {
                "condition_id": "expired",
                "slug": "expired-market",
                "question": "Expired",
                "yes_token": "t1",
                "no_token": "t2",
                "end_date": expired,
                "outcomes": ["Up", "Down"],
                "volume_24h": 1000,
                "accepting_orders": True,
            },
            {
                "condition_id": "active",
                "slug": "active-market",
                "question": "Active",
                "yes_token": "t3",
                "no_token": "t4",
                "end_date": future,
                "outcomes": ["Up", "Down"],
                "volume_24h": 1000,
                "accepting_orders": True,
            },
        ]

        manager = fetch_recent_updown_markets(candle_interval="1h")

        # Only non-expired market should be included
        assert len(manager.markets) == 1
        assert "active" in list(manager.markets.keys())[0]

    @patch("src.market.discovery.fetch_updown_events")
    def test_filters_by_volume(self, mock_fetch):
        """Test that low volume markets are filtered out"""
        now = datetime.now(UTC)
        future = (now + timedelta(minutes=30)).isoformat()

        mock_fetch.return_value = [
            {
                "condition_id": "low-vol",
                "slug": "low-volume",
                "question": "Low Volume",
                "yes_token": "t1",
                "no_token": "t2",
                "end_date": future,
                "outcomes": ["Up", "Down"],
                "volume_24h": 10,  # Below default threshold
                "accepting_orders": True,
            },
            {
                "condition_id": "high-vol",
                "slug": "high-volume",
                "question": "High Volume",
                "yes_token": "t3",
                "no_token": "t4",
                "end_date": future,
                "outcomes": ["Up", "Down"],
                "volume_24h": 5000,
                "accepting_orders": True,
            },
        ]

        manager = fetch_recent_updown_markets(
            candle_interval="1h",
            min_volume_24h=100,
        )

        assert len(manager.markets) == 1
        assert "high-vol" in list(manager.markets.keys())[0]
