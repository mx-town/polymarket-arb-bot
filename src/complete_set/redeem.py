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

MERGE_ABI = [
    {
        "name": "mergePositions",
        "type": "function",
        "inputs": [
            {"name": "collateralToken", "type": "address"},
            {"name": "parentCollectionId", "type": "bytes32"},
            {"name": "conditionId", "type": "bytes32"},
            {"name": "indexSets", "type": "uint256[]"},
            {"name": "amount", "type": "uint256"},
        ],
        "outputs": [],
    }
]

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
    # Mask RPC URL for logging (show host only)
    from urllib.parse import urlparse
    parsed = urlparse(rpc_url)
    rpc_display = f"{parsed.scheme}://{parsed.hostname}...{parsed.path[-6:]}" if parsed.path else f"{parsed.scheme}://{parsed.hostname}"

    log.info("REDEEM_INIT rpc=%s │ ctf=%s │ condition=%s", rpc_display, CTF_ADDRESS, condition_id)

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = w3.eth.account.from_key(private_key)
    log.info("REDEEM_WALLET address=%s │ chain=%d", account.address, chain_id)

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CTF_ADDRESS),
        abi=REDEEM_ABI,
    )

    if not condition_id:
        raise ValueError("condition_id is empty — cannot redeem")
    condition_bytes = bytes.fromhex(condition_id.removeprefix("0x"))

    nonce = w3.eth.get_transaction_count(account.address)
    gas_price = w3.eth.gas_price
    log.info("REDEEM_TX_PARAMS nonce=%d │ gas=300000 │ gasPrice=%d │ maxFee=%d │ priorityFee=%d gwei",
             nonce, gas_price, gas_price * 2, 30)

    tx = contract.functions.redeemPositions(
        Web3.to_checksum_address(USDC_ADDRESS),
        PARENT_COLLECTION_ID,
        condition_bytes,
        INDEX_SETS,
    ).build_transaction({
        "from": account.address,
        "chainId": chain_id,
        "nonce": nonce,
        "gas": 300_000,
        "maxFeePerGas": gas_price * 2,
        "maxPriorityFeePerGas": w3.to_wei(30, "gwei"),
    })

    log.info("REDEEM_BUILT to=%s │ data=%s...%s │ value=%s",
             tx.get("to", "?"), tx.get("data", "")[:18], tx.get("data", "")[-8:], tx.get("value", 0))

    signed = account.sign_transaction(tx)
    log.info("REDEEM_SIGNED sending raw tx...")
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    log.info("REDEEM_SENT tx=%s │ waiting for receipt (timeout=120s)", tx_hash.hex())
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    log.info("REDEEM_RECEIPT status=%d │ block=%s │ gasUsed=%s",
             receipt["status"], receipt.get("blockNumber", "?"), receipt.get("gasUsed", "?"))

    if receipt["status"] != 1:
        raise RuntimeError(f"Redeem tx reverted: {tx_hash.hex()}")

    return tx_hash.hex()


# CTF tokens use 6 decimals on Polygon (same as USDC)
CTF_DECIMALS = 6


def merge_positions(
    private_key: str,
    rpc_url: str,
    condition_id: str,
    amount: int,
    chain_id: int = 137,
) -> str:
    """Merge hedged UP+DOWN positions back to USDC on-chain.

    amount is in base units (6 decimals). Merges equal amounts of both
    outcome tokens back into USDC collateral, freeing locked capital.
    Returns tx hash hex string.
    """
    from urllib.parse import urlparse
    parsed = urlparse(rpc_url)
    rpc_display = f"{parsed.scheme}://{parsed.hostname}...{parsed.path[-6:]}" if parsed.path else f"{parsed.scheme}://{parsed.hostname}"

    log.info("MERGE_INIT rpc=%s │ ctf=%s │ condition=%s │ amount=%d",
             rpc_display, CTF_ADDRESS, condition_id, amount)

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = w3.eth.account.from_key(private_key)
    log.info("MERGE_WALLET address=%s │ chain=%d", account.address, chain_id)

    contract = w3.eth.contract(
        address=Web3.to_checksum_address(CTF_ADDRESS),
        abi=MERGE_ABI,
    )

    if not condition_id:
        raise ValueError("condition_id is empty — cannot merge")
    condition_bytes = bytes.fromhex(condition_id.removeprefix("0x"))

    nonce = w3.eth.get_transaction_count(account.address)
    gas_price = w3.eth.gas_price
    log.info("MERGE_TX_PARAMS nonce=%d │ gas=300000 │ gasPrice=%d", nonce, gas_price)

    tx = contract.functions.mergePositions(
        Web3.to_checksum_address(USDC_ADDRESS),
        PARENT_COLLECTION_ID,
        condition_bytes,
        INDEX_SETS,
        amount,
    ).build_transaction({
        "from": account.address,
        "chainId": chain_id,
        "nonce": nonce,
        "gas": 300_000,
        "maxFeePerGas": gas_price * 2,
        "maxPriorityFeePerGas": w3.to_wei(30, "gwei"),
    })

    log.info("MERGE_BUILT to=%s │ data=%s...%s",
             tx.get("to", "?"), tx.get("data", "")[:18], tx.get("data", "")[-8:])

    signed = account.sign_transaction(tx)
    log.info("MERGE_SIGNED sending raw tx...")
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    log.info("MERGE_SENT tx=%s │ waiting for receipt (timeout=120s)", tx_hash.hex())
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    log.info("MERGE_RECEIPT status=%d │ block=%s │ gasUsed=%s",
             receipt["status"], receipt.get("blockNumber", "?"), receipt.get("gasUsed", "?"))

    if receipt["status"] != 1:
        raise RuntimeError(f"Merge tx reverted: {tx_hash.hex()}")

    return tx_hash.hex()
