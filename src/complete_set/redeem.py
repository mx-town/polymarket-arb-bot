"""On-chain redemption of resolved Polymarket positions via ConditionalTokens contract."""

from __future__ import annotations

import logging

from web3 import Web3

log = logging.getLogger("cs.redeem")

# ConditionalTokens (CTF) contract on Polygon
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"

# USDC on Polygon (collateral token)
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"

# Null parent collection ID (standard for Polymarket top-level conditions)
PARENT_COLLECTION_ID = bytes(32)

# Binary outcome index sets: 0b01 = UP, 0b10 = DOWN
INDEX_SETS = [1, 2]

REDEEM_ABI = [
    {
        "name": "redeemPositions",
        "type": "function",
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
        ],
        "outputs": [],
    }
]


def redeem_positions(
    private_key: str,
    rpc_url: str,
    condition_id: str,
    chain_id: int = 137,
) -> str:
    """Redeem resolved positions on-chain. Returns tx hash hex string."""
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = w3.eth.account.from_key(private_key)

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CTF_ADDRESS),
        abi=REDEEM_ABI,
    )

    if not condition_id:
        raise ValueError("condition_id is empty — cannot redeem")
    condition_bytes = bytes.fromhex(condition_id.removeprefix("0x"))

    tx = contract.functions.redeemPositions(
        Web3.to_checksum_address(USDC_ADDRESS),
        PARENT_COLLECTION_ID,
        condition_bytes,
        INDEX_SETS,
    ).build_transaction({
        "from": account.address,
        "chainId": chain_id,
        "nonce": w3.eth.get_transaction_count(account.address),
        "gas": 300_000,
        "maxFeePerGas": w3.eth.gas_price * 2,
        "maxPriorityFeePerGas": w3.to_wei(30, "gwei"),
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt["status"] != 1:
        raise RuntimeError(f"Redeem tx reverted: {tx_hash.hex()}")

    return tx_hash.hex()
