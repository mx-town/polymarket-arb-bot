"""On-chain analysis — merge detection and maker/taker role decoding."""

from __future__ import annotations

import logging
import os
from typing import Any

import requests

from observer.models import C_GREEN, C_RESET, ObservedMerge

log = logging.getLogger("obs.onchain")

ETHERSCAN_API = "https://api.polygonscan.com/api"
BURN_ADDRESS = "0x0000000000000000000000000000000000000000"

# OrderFilled event signature (Polymarket CTF Exchange)
ORDER_FILLED_TOPIC = "0xd0a08e8c493f9c94f29311604c9de1b4e8c8d4c06bd0c789af57f2d65bfec0f6"


class MergeDetector:
    """Detects ERC-1155 burns (merges) and decodes maker/taker from OrderFilled logs."""

    def __init__(self, proxy_address: str, page_size: int = 50) -> None:
        self._proxy = proxy_address.lower()
        self._page_size = page_size
        self._seen_merge_tx: set[str] = set()
        self._etherscan_key = os.environ.get("ETHERSCAN_API_KEY", "")
        self._rpc_url = os.environ.get("POLYGON_RPC_URL", "")

        if not self._etherscan_key:
            log.warning("ETHERSCAN_API_KEY not set — merge detection disabled")
        if not self._rpc_url:
            log.warning("POLYGON_RPC_URL not set — maker/taker decoding disabled")

    def poll_merges(self) -> list[ObservedMerge]:
        """Poll Etherscan for ERC-1155 burns from the proxy address."""
        if not self._etherscan_key:
            return []

        try:
            resp = requests.get(
                ETHERSCAN_API,
                params={
                    "module": "account",
                    "action": "token1155tx",
                    "address": self._proxy,
                    "page": 1,
                    "offset": self._page_size,
                    "sort": "desc",
                    "apikey": self._etherscan_key,
                },
                timeout=10,
            )
            resp.raise_for_status()
            data = resp.json()
        except (requests.ConnectionError, requests.Timeout) as exc:
            log.warning("MERGE_POLL_FAIL │ %s", exc)
            return []
        except Exception as exc:
            log.debug("MERGE_POLL_ERROR │ %s", exc)
            return []

        if data.get("status") != "1":
            return []

        merges: list[ObservedMerge] = []
        for tx in data.get("result", []):
            tx_hash = tx.get("hash", "")
            to_addr = tx.get("to", "").lower()

            # Merge = burn (to == zero address)
            if to_addr != BURN_ADDRESS:
                continue
            if tx_hash in self._seen_merge_tx:
                continue

            self._seen_merge_tx.add(tx_hash)
            merge = ObservedMerge(
                timestamp=int(tx.get("timeStamp", 0)),
                tx_hash=tx_hash,
                token_id=tx.get("tokenID", ""),
                shares=float(tx.get("tokenValue", 0)),
                block_number=int(tx.get("blockNumber", 0)),
            )
            merges.append(merge)
            log.info(
                "%sMERGE%s │ shares=%.1f │ token=%s │ block=%d │ tx=%s",
                C_GREEN,
                C_RESET,
                merge.shares,
                merge.token_id[:16],
                merge.block_number,
                merge.tx_hash[:10],
            )

        return merges

    def decode_role(self, tx_hash: str) -> str:
        """Decode maker/taker role from OrderFilled event in a transaction receipt.

        Returns "MAKER", "TAKER", or "" if unable to decode.
        """
        if not self._rpc_url:
            return ""

        try:
            receipt = self._get_receipt(tx_hash)
            if not receipt:
                return ""

            logs = receipt.get("result", {}).get("logs", [])
            for entry in logs:
                topics = entry.get("topics", [])
                if len(topics) < 4:
                    continue
                if topics[0] != ORDER_FILLED_TOPIC:
                    continue

                # topic[2] = maker address (indexed, 32-byte padded)
                maker = _extract_address(topics[2])
                # topic[3] = taker address (indexed, 32-byte padded)
                taker = _extract_address(topics[3])

                if maker == self._proxy:
                    return "MAKER"
                if taker == self._proxy:
                    return "TAKER"

            return ""
        except Exception as exc:
            log.debug("ROLE_DECODE_FAIL │ tx=%s │ %s", tx_hash[:10], exc)
            return ""

    def decode_fill_details(self, tx_hash: str) -> dict[str, Any]:
        """Decode full OrderFilled event data including amounts and fee.

        Returns dict with: role, maker_amount, taker_amount, fee, maker_asset_id, taker_asset_id.
        Empty dict on failure.
        """
        if not self._rpc_url:
            return {}

        try:
            receipt = self._get_receipt(tx_hash)
            if not receipt:
                return {}

            logs = receipt.get("result", {}).get("logs", [])
            for entry in logs:
                topics = entry.get("topics", [])
                if len(topics) < 4:
                    continue
                if topics[0] != ORDER_FILLED_TOPIC:
                    continue

                maker = _extract_address(topics[2])
                taker = _extract_address(topics[3])
                role = ""
                if maker == self._proxy:
                    role = "MAKER"
                elif taker == self._proxy:
                    role = "TAKER"

                if not role:
                    continue

                # Decode data: makerAssetId, takerAssetId, makerAmountFilled, takerAmountFilled, fee
                data_hex = entry.get("data", "0x")
                details = _decode_order_filled_data(data_hex)
                details["role"] = role
                return details

            return {}
        except Exception as exc:
            log.debug("FILL_DECODE_FAIL │ tx=%s │ %s", tx_hash[:10], exc)
            return {}

    def _get_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        """Fetch transaction receipt via JSON-RPC."""
        try:
            resp = requests.post(
                self._rpc_url,
                json={
                    "jsonrpc": "2.0",
                    "method": "eth_getTransactionReceipt",
                    "params": [tx_hash],
                    "id": 1,
                },
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except (requests.ConnectionError, requests.Timeout) as exc:
            log.warning("RPC_FAIL │ %s", exc)
            return None
        except Exception as exc:
            log.debug("RPC_ERROR │ %s", exc)
            return None

    @property
    def seen_merge_count(self) -> int:
        return len(self._seen_merge_tx)


def _extract_address(topic: str) -> str:
    """Extract a lowercase address from a 32-byte hex-encoded indexed topic."""
    # topic is 0x + 64 hex chars, address is last 40 chars
    if len(topic) < 42:
        return ""
    return "0x" + topic[-40:].lower()


def _decode_order_filled_data(data_hex: str) -> dict[str, Any]:
    """Decode the non-indexed data from an OrderFilled event.

    Layout (5 x uint256, each 32 bytes = 64 hex chars):
        [0] makerAssetId
        [1] takerAssetId
        [2] makerAmountFilled
        [3] takerAmountFilled
        [4] fee
    """
    result: dict[str, Any] = {}
    if not data_hex or data_hex == "0x":
        return result

    # Strip 0x prefix
    raw = data_hex[2:] if data_hex.startswith("0x") else data_hex

    if len(raw) < 320:  # 5 * 64
        return result

    try:
        result["maker_asset_id"] = str(int(raw[0:64], 16))
        result["taker_asset_id"] = str(int(raw[64:128], 16))
        # Amounts are in wei-like units (6 decimals for USDC, raw for shares)
        result["maker_amount"] = int(raw[128:192], 16)
        result["taker_amount"] = int(raw[192:256], 16)
        result["fee"] = int(raw[256:320], 16)
    except (ValueError, IndexError) as exc:
        log.debug("DATA_DECODE_FAIL │ %s", exc)

    return result
