"""Balance tracking — USDC balance polling and transfer history scanning."""

from __future__ import annotations

import logging
import os
from typing import Any

from web3 import Web3

log = logging.getLogger("obs.balance")

# USDC.e contract on Polygon (6 decimals)
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# Known Polymarket addresses for transfer classification
POLYMARKET_ADDRESSES = {
    "0x4bFb41d5B3570DeFd03C39a9A4D8dE6Bd8B8982E".lower(),  # CTF Exchange
    "0xC5d563A36AE78145C45a50134d48A1215220f80a".lower(),  # NegRiskCTFExchange
    "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296".lower(),  # NegRiskAdapter
    "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045".lower(),  # Conditional Tokens
}

# Transfer(address indexed from, address indexed to, uint256 value)
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"

# ERC-20 ABI (minimal — just balanceOf)
USDC_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]


class BalanceTracker:
    """Tracks USDC balance and transfer history for a proxy address."""

    def __init__(self, proxy_address: str) -> None:
        self._proxy = Web3.to_checksum_address(proxy_address)
        self._proxy_lower = proxy_address.lower()
        self._rpc_url = os.environ.get("POLYGON_RPC_URL", "")

        if not self._rpc_url:
            log.warning("POLYGON_RPC_URL not set — balance tracking disabled")
            self._w3 = None
            self._usdc_contract = None
        else:
            self._w3 = Web3(Web3.HTTPProvider(self._rpc_url))
            if not self._w3.is_connected():
                log.error("RPC_CONNECT_FAIL │ url=%s", self._rpc_url)
                self._w3 = None
                self._usdc_contract = None
            else:
                usdc_checksum = Web3.to_checksum_address(USDC_ADDRESS)
                self._usdc_contract = self._w3.eth.contract(
                    address=usdc_checksum,
                    abi=USDC_ABI,
                )
                log.info(
                    "BALANCE_TRACKER_INIT │ proxy=%s │ usdc=%s",
                    self._proxy[:10],
                    usdc_checksum[:10],
                )

    def poll_balance(self, position_data: list[dict[str, Any]]) -> tuple[float, float]:
        """Poll USDC balance and compute total position value.

        Args:
            position_data: List of position dicts with 'current_value' field.

        Returns:
            (usdc_balance, total_position_value) — both in USD.
        """
        if not self._w3 or not self._usdc_contract:
            return 0.0, 0.0

        try:
            # On-chain USDC balance (6 decimals)
            raw_balance = self._usdc_contract.functions.balanceOf(self._proxy).call()
            usdc_balance = raw_balance / 1e6
        except Exception as exc:
            log.warning("BALANCE_POLL_FAIL │ %s", exc)
            return 0.0, 0.0

        # Sum current_value from positions
        total_position_value = sum(pos.get("current_value", 0.0) for pos in position_data)

        log.debug(
            "BALANCE_POLL │ usdc=%.2f │ positions=%.2f │ total=%.2f",
            usdc_balance,
            total_position_value,
            usdc_balance + total_position_value,
        )

        return usdc_balance, total_position_value

    def scan_transfers(self, from_block: int, to_block: int) -> list[dict[str, Any]]:
        """Scan USDC transfer events involving the proxy address.

        Args:
            from_block: Starting block number (inclusive).
            to_block: Ending block number (inclusive).

        Returns:
            List of transfer dicts with keys:
                - ts: block timestamp (Unix seconds)
                - tx_hash: transaction hash
                - from_address: sender address (lowercase)
                - to_address: recipient address (lowercase)
                - amount: USDC amount (float)
                - block_number: block number
                - transfer_type: "rebate" | "withdrawal" | "deposit" | "unknown"
        """
        if not self._w3 or not self._usdc_contract:
            return []

        try:
            usdc_checksum = Web3.to_checksum_address(USDC_ADDRESS)

            # Build filter for Transfer events involving proxy (from OR to)
            # eth_getLogs with topic[1]=from OR topic[2]=to
            logs = self._w3.eth.get_logs(
                {
                    "fromBlock": from_block,
                    "toBlock": to_block,
                    "address": usdc_checksum,
                    "topics": [
                        TRANSFER_TOPIC,
                        # Use None to match any sender, then filter in Python
                    ],
                }
            )
        except Exception as exc:
            log.warning(
                "TRANSFER_SCAN_FAIL │ from=%d to=%d │ %s",
                from_block,
                to_block,
                exc,
            )
            return []

        transfers: list[dict[str, Any]] = []
        for entry in logs:
            tx_hash = entry["transactionHash"].hex()
            block_number = entry["blockNumber"]

            # Decode topics: topic[0] = event sig, topic[1] = from, topic[2] = to
            topics = entry["topics"]
            if len(topics) < 3:
                continue

            from_addr = _extract_address(topics[1])
            to_addr = _extract_address(topics[2])

            # Filter: only include transfers where proxy is from or to
            if from_addr != self._proxy_lower and to_addr != self._proxy_lower:
                continue

            # Decode amount from data field (uint256, 32 bytes)
            data = entry["data"]
            if not data or data == "0x":
                continue
            amount_raw = int(data.hex(), 16)
            amount = amount_raw / 1e6

            # Classify transfer type
            transfer_type = self._classify_transfer(from_addr, to_addr)

            # Fetch block timestamp
            try:
                block = self._w3.eth.get_block(block_number)
                ts = int(block["timestamp"])
            except Exception:
                ts = 0

            transfers.append(
                {
                    "ts": ts,
                    "tx_hash": tx_hash,
                    "from_address": from_addr,
                    "to_address": to_addr,
                    "amount": amount,
                    "block_number": block_number,
                    "transfer_type": transfer_type,
                }
            )

        if transfers:
            log.info(
                "TRANSFER_SCAN │ blocks=%d-%d │ found=%d",
                from_block,
                to_block,
                len(transfers),
            )

        return transfers

    def _classify_transfer(self, from_addr: str, to_addr: str) -> str:
        """Classify a transfer based on from/to addresses.

        Returns:
            "rebate" — from Polymarket address to proxy
            "withdrawal" — from proxy to external address
            "deposit" — from external address to proxy
            "unknown" — other
        """
        is_from_proxy = from_addr == self._proxy_lower
        is_to_proxy = to_addr == self._proxy_lower
        is_from_polymarket = from_addr in POLYMARKET_ADDRESSES
        is_to_polymarket = to_addr in POLYMARKET_ADDRESSES

        # Rebate: Polymarket → proxy
        if is_from_polymarket and is_to_proxy:
            return "rebate"

        # Withdrawal: proxy → external
        if is_from_proxy and not is_to_polymarket:
            return "withdrawal"

        # Deposit: external → proxy
        if is_to_proxy and not is_from_polymarket:
            return "deposit"

        return "unknown"


def _extract_address(topic: bytes) -> str:
    """Extract address from a 32-byte indexed topic.

    EVM pads addresses (20 bytes) to 32 bytes for indexed parameters.
    Address is in the last 20 bytes.
    """
    # topic is bytes, take last 20 bytes and convert to hex
    if len(topic) != 32:
        return ""
    addr_bytes = topic[-20:]
    return "0x" + addr_bytes.hex().lower()
