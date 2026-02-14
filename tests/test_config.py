"""Tests for config loading and validation."""

from decimal import Decimal

import pytest

from complete_set.config import CompleteSetConfig, load_complete_set_config


class TestLoadConfig:
    def test_defaults(self):
        cfg = load_complete_set_config({})
        assert cfg.min_merge_shares == Decimal("10")
        assert cfg.max_gas_price_gwei == 200
        assert cfg.min_merge_profit_usd == Decimal("0.02")

    def test_custom_values(self):
        raw = {
            "complete_set": {
                "bankroll_usd": 50,
                "min_edge": 0.02,
                "min_merge_shares": 15,
                "max_gas_price_gwei": 100,
                "min_merge_profit_usd": 0.05,
            }
        }
        cfg = load_complete_set_config(raw)
        assert cfg.bankroll_usd == Decimal("50")
        assert cfg.min_edge == Decimal("0.02")
        assert cfg.min_merge_shares == Decimal("15")
        assert cfg.max_gas_price_gwei == 100
        assert cfg.min_merge_profit_usd == Decimal("0.05")

    def test_missing_section_uses_defaults(self):
        cfg = load_complete_set_config({"other_section": {}})
        assert cfg.enabled is True
        assert cfg.dry_run is True

    def test_assets_tuple(self):
        raw = {"complete_set": {"assets": ["bitcoin", "ethereum"]}}
        cfg = load_complete_set_config(raw)
        assert cfg.assets == ("bitcoin", "ethereum")

    def test_mean_reversion_defaults(self):
        cfg = CompleteSetConfig()
        assert cfg.mean_reversion_enabled is False
        assert cfg.mr_deviation_threshold == Decimal("0.0004")

    def test_volume_imbalance_defaults(self):
        cfg = CompleteSetConfig()
        assert cfg.volume_imbalance_enabled is False
        assert cfg.volume_imbalance_threshold == Decimal("0.15")


class TestValidateConfig:
    """T3-4: Config validation at startup."""

    def test_defaults_pass(self):
        """Default config should pass validation."""
        from complete_set.config import validate_config
        cfg = CompleteSetConfig()
        validate_config(cfg)  # should not raise

    def test_negative_bankroll(self):
        from complete_set.config import validate_config
        cfg = CompleteSetConfig(bankroll_usd=Decimal("-10"))
        with pytest.raises(ValueError, match="bankroll_usd"):
            validate_config(cfg)

    def test_edge_out_of_range(self):
        from complete_set.config import validate_config
        cfg = CompleteSetConfig(min_edge=Decimal("0.60"))
        with pytest.raises(ValueError, match="min_edge"):
            validate_config(cfg)

    def test_inverted_time_window(self):
        from complete_set.config import validate_config
        cfg = CompleteSetConfig(min_seconds_to_end=500, max_seconds_to_end=100)
        with pytest.raises(ValueError, match="max_seconds_to_end"):
            validate_config(cfg)

    def test_inverted_sh_window(self):
        from complete_set.config import validate_config
        cfg = CompleteSetConfig(sh_entry_start_sec=500, sh_entry_end_sec=600)
        with pytest.raises(ValueError, match="sh_entry_start_sec"):
            validate_config(cfg)

    def test_mr_validation_when_enabled(self):
        from complete_set.config import validate_config
        cfg = CompleteSetConfig(
            mean_reversion_enabled=True,
            mr_deviation_threshold=Decimal("0"),
        )
        with pytest.raises(ValueError, match="mr_deviation_threshold"):
            validate_config(cfg)

    def test_mr_validation_skipped_when_disabled(self):
        from complete_set.config import validate_config
        cfg = CompleteSetConfig(
            mean_reversion_enabled=False,
            mr_deviation_threshold=Decimal("0"),
        )
        validate_config(cfg)  # should not raise

    def test_multiple_errors_collected(self):
        from complete_set.config import validate_config
        cfg = CompleteSetConfig(
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
        """load_complete_set_config should call validate_config."""
        with pytest.raises(ValueError, match="bankroll_usd"):
            load_complete_set_config({"complete_set": {"bankroll_usd": -5}})
