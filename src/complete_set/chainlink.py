"""Chainlink BTC/USD price feed reader — Polygon mainnet.

Reads latestRoundData() from the Chainlink aggregator to get the exact same
BTC reference price that Polymarket uses for settlement.

Contract: 0xc907E116054Ad103354f2D350FD2514433D57F6f (BTC/USD on Polygon)
Heartbeat: 27s, deviation trigger: 0.1%
"""

from __future__ import annotations

import logging
import os
from decimal import Decimal

from web3 import Web3

log = logging.getLogger("cs.chainlink")

CHAINLINK_BTC_USD_POLYGON = "0xc907E116054Ad103354f2D350FD2514433D57F6f"
CHAINLINK_DECIMALS = 8

# Minimal ABI — only latestRoundData()
AGGREGATOR_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"name": "roundId", "type": "uint80"},
            {"name": "answer", "type": "int256"},
            {"name": "startedAt", "type": "uint256"},
            {"name": "updatedAt", "type": "uint256"},
            {"name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    }
]


def fetch_chainlink_btc_price(rpc_url: str = "") -> Decimal:
    """Read the latest BTC/USD price from Chainlink on Polygon.

    Returns the price as a Decimal (e.g. Decimal("69509.95000000")).
    Returns Decimal("0") on failure.
    """
    url = rpc_url or os.environ.get("POLYGON_RPC_URL", "")
    if not url:
        log.warning("CHAINLINK │ no RPC URL configured")
        return Decimal("0")

    try:
        w3 = Web3(Web3.HTTPProvider(url))
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(CHAINLINK_BTC_USD_POLYGON),
            abi=AGGREGATOR_ABI,
        )
        (_round_id, answer, _started_at, updated_at, _answered_in_round) = (
            contract.functions.latestRoundData().call()
        )
        price = Decimal(answer) / Decimal(10 ** CHAINLINK_DECIMALS)
        log.debug("CHAINLINK │ BTC/USD=%s │ updated=%d", price, updated_at)
        return price
    except Exception as e:
        log.warning("CHAINLINK │ failed to read price: %s", e)
        return Decimal("0")
