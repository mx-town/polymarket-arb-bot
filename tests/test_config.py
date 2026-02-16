"""Tests for config loading and validation."""

from decimal import Decimal

import pytest

from rebate_maker.config import RebateMakerConfig, load_rebate_maker_config


class TestLoadConfig:
    def test_defaults(self):
        cfg = load_rebate_maker_config({})
        assert cfg.min_merge_shares == Decimal("10")
        assert cfg.max_gas_price_gwei == 200
        assert cfg.min_merge_profit_usd == Decimal("0.02")

    def test_custom_values(self):
        raw = {
            "rebate_maker": {
                "bankroll_usd": 50,
                "min_edge": 0.02,
                "min_merge_shares": 15,
                "max_gas_price_gwei": 100,
                "min_merge_profit_usd": 0.05,
            }
        }
        cfg = load_rebate_maker_config(raw)
        assert cfg.bankroll_usd == Decimal("50")
        assert cfg.min_edge == Decimal("0.02")
        assert cfg.min_merge_shares == Decimal("15")
        assert cfg.max_gas_price_gwei == 100
        assert cfg.min_merge_profit_usd == Decimal("0.05")

    def test_missing_section_uses_defaults(self):
        cfg = load_rebate_maker_config({"other_section": {}})
        assert cfg.enabled is True
        assert cfg.dry_run is True

    def test_assets_tuple(self):
        raw = {"rebate_maker": {"assets": ["bitcoin", "ethereum"]}}
        cfg = load_rebate_maker_config(raw)
        assert cfg.assets == ("bitcoin", "ethereum")



class TestValidateConfig:
    """T3-4: Config validation at startup."""

    def test_defaults_pass(self):
        """Default config should pass validation."""
        from rebate_maker.config import validate_config
        cfg = RebateMakerConfig()
        validate_config(cfg)  # should not raise

    def test_negative_bankroll(self):
        from rebate_maker.config import validate_config
        cfg = RebateMakerConfig(bankroll_usd=Decimal("-10"))
        with pytest.raises(ValueError, match="bankroll_usd"):
            validate_config(cfg)

    def test_edge_out_of_range(self):
        from rebate_maker.config import validate_config
        cfg = RebateMakerConfig(min_edge=Decimal("0.60"))
        with pytest.raises(ValueError, match="min_edge"):
            validate_config(cfg)

    def test_inverted_time_window(self):
        from rebate_maker.config import validate_config
        cfg = RebateMakerConfig(min_seconds_to_end=500, max_seconds_to_end=100)
        with pytest.raises(ValueError, match="max_seconds_to_end"):
            validate_config(cfg)


    def test_multiple_errors_collected(self):
        from rebate_maker.config import validate_config
        cfg = RebateMakerConfig(
            bankroll_usd=Decimal("-1"),
            min_edge=Decimal("0.60"),
            refresh_millis=50,
        )
        with pytest.raises(ValueError) as exc_info:
            validate_config(cfg)
        msg = str(exc_info.value)
        assert "bankroll_usd" in msg
        assert "min_edge" in msg
        assert "refresh_millis" in msg

    def test_load_validates(self):
        """load_rebate_maker_config should call validate_config."""
        with pytest.raises(ValueError, match="bankroll_usd"):
            load_rebate_maker_config({"rebate_maker": {"bankroll_usd": -5}})
