"""Tests for redeem.py — gas cap, approval check."""

from unittest.mock import MagicMock, patch

import pytest

from shared.redeem import (
    _approved_pairs,
    _ensure_approval,
    _send_safe_tx,
)


class TestGasPriceCap:
    def test_raises_when_gas_over_cap(self):
        """Gas price above cap should raise RuntimeError."""
        w3 = MagicMock()
        account = MagicMock()
        account.address = "0x" + "aa" * 20

        # 300 gwei = 300_000_000_000 wei
        w3.eth.gas_price = 300_000_000_000

        safe = MagicMock()
        safe.functions.nonce.return_value.call.return_value = 0
        safe.functions.getTransactionHash.return_value.call.return_value = b"\x00" * 32
        safe.encode_abi.return_value = "0x" + "00" * 32
        w3.eth.contract.return_value = safe
        w3.eth.get_transaction_count.return_value = 0

        with patch("shared.redeem.Account") as mock_account:
            mock_account.unsafe_sign_hash.return_value = MagicMock(
                r=1, s=2, v=27,
            )
            with pytest.raises(RuntimeError, match="exceeds cap"):
                _send_safe_tx(
                    w3, account, "0x" + "bb" * 20,
                    "0x" + "cc" * 20, b"\x00",
                    max_gas_price_gwei=200,
                )

    def test_passes_when_gas_under_cap(self):
        """Gas price under cap should proceed (will fail later, but not on gas check)."""
        w3 = MagicMock()
        account = MagicMock()
        account.address = "0x" + "aa" * 20

        # 50 gwei — well under 200 gwei cap
        w3.eth.gas_price = 50_000_000_000

        safe = MagicMock()
        safe.functions.nonce.return_value.call.return_value = 0
        safe.functions.getTransactionHash.return_value.call.return_value = b"\x00" * 32
        safe.encode_abi.return_value = "0x" + "00" * 32
        w3.eth.contract.return_value = safe
        w3.eth.get_transaction_count.return_value = 0
        w3.eth.estimate_gas.return_value = 100_000

        # Mock sign + send
        account.sign_transaction.return_value = MagicMock(raw_transaction=b"\x00")
        w3.eth.send_raw_transaction.return_value = b"\x01" * 32

        # Mock receipt
        w3.eth.get_transaction_receipt.return_value = {
            "status": 1,
            "gasUsed": 100_000,
        }

        with patch("shared.redeem.Account") as mock_account:
            mock_account.unsafe_sign_hash.return_value = MagicMock(
                r=1, s=2, v=27,
            )
            result = _send_safe_tx(
                w3, account, "0x" + "bb" * 20,
                "0x" + "cc" * 20, b"\x00",
                max_gas_price_gwei=200,
            )
            assert result.tx_hash is not None


class TestApprovalCheck:
    def setup_method(self):
        _approved_pairs.clear()

    def test_skips_when_already_approved(self):
        """Should not call contract when already in cache."""
        w3 = MagicMock()
        account = MagicMock()
        safe = "0x" + "aa" * 20
        operator = "0x" + "bb" * 20

        # Pre-populate cache
        from web3 import Web3
        safe_cs = Web3.to_checksum_address(safe)
        op_cs = Web3.to_checksum_address(operator)
        _approved_pairs.add((safe_cs.lower(), op_cs.lower()))

        _ensure_approval(w3, account, safe, operator)
        # No contract calls should have been made
        w3.eth.contract.assert_not_called()

    def test_checks_and_caches_when_approved(self):
        """Should check isApprovedForAll and cache if True."""
        w3 = MagicMock()
        account = MagicMock()
        safe = "0x" + "aa" * 20
        operator = "0x" + "bb" * 20

        ctf = MagicMock()
        ctf.functions.isApprovedForAll.return_value.call.return_value = True
        w3.eth.contract.return_value = ctf

        _ensure_approval(w3, account, safe, operator)

        ctf.functions.isApprovedForAll.assert_called_once()
        from web3 import Web3
        safe_cs = Web3.to_checksum_address(safe)
        op_cs = Web3.to_checksum_address(operator)
        assert (safe_cs.lower(), op_cs.lower()) in _approved_pairs

    def test_sends_approval_when_not_approved(self):
        """Should send setApprovalForAll tx when isApprovedForAll returns False."""
        w3 = MagicMock()
        account = MagicMock()
        account.address = "0x" + "dd" * 20
        safe = "0x" + "aa" * 20
        operator = "0x" + "bb" * 20

        ctf = MagicMock()
        ctf.functions.isApprovedForAll.return_value.call.return_value = False
        ctf.encode_abi.return_value = "0x" + "00" * 32
        w3.eth.contract.return_value = ctf

        # Mock _send_safe_tx to avoid actual tx
        with patch("shared.redeem._send_safe_tx") as mock_send:
            mock_send.return_value = "0xfaketx"
            _ensure_approval(w3, account, safe, operator)

        mock_send.assert_called_once()
        from web3 import Web3
        safe_cs = Web3.to_checksum_address(safe)
        op_cs = Web3.to_checksum_address(operator)
        assert (safe_cs.lower(), op_cs.lower()) in _approved_pairs
