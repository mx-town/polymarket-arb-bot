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

# ERC1155 ABI subset for balance/approval checks
ERC1155_ABI = [
    {
        "name": "balanceOf",
        "type": "function",
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "id", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    },
    {
        "name": "isApprovedForAll",
        "type": "function",
        "inputs": [
            {"name": "account", "type": "address"},
            {"name": "operator", "type": "address"},
        ],
        "outputs": [{"name": "", "type": "bool"}],
        "stateMutability": "view",
    },
    {
        "name": "setApprovalForAll",
        "type": "function",
        "inputs": [
            {"name": "operator", "type": "address"},
            {"name": "approved", "type": "bool"},
        ],
        "outputs": [],
    },
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


def _compute_position_id(condition_id_hex: str, index_set: int) -> int:
    """Compute ERC1155 token ID for a CTF position.

    tokenId = keccak256(collateralToken, collectionId)
    where collectionId = keccak256(conditionId, indexSet) for top-level conditions.
    """
    condition_bytes = bytes.fromhex(condition_id_hex.removeprefix("0x"))
    # collectionId = keccak256(parentCollectionId || conditionId || indexSet)
    collection_id = Web3.solidity_keccak(
        ["bytes32", "bytes32", "uint256"],
        [PARENT_COLLECTION_ID, condition_bytes, index_set],
    )
    # positionId = keccak256(collateralToken || collectionId)
    position_id = Web3.solidity_keccak(
        ["address", "bytes32"],
        [Web3.to_checksum_address(USDC_ADDRESS), collection_id],
    )
    return int.from_bytes(position_id, "big")


def _ensure_ctf_approval(
    w3: Web3, account, ctf_address: str, chain_id: int,
) -> None:
    """Ensure the CTF contract is approved as ERC1155 operator for our tokens."""
    ctf_checksum = Web3.to_checksum_address(ctf_address)
    erc1155 = w3.eth.contract(address=ctf_checksum, abi=ERC1155_ABI)

    approved = erc1155.functions.isApprovedForAll(account.address, ctf_checksum).call()
    if approved:
        return

    log.info("MERGE_APPROVE setting CTF as ERC1155 operator for %s", account.address)
    nonce = w3.eth.get_transaction_count(account.address)
    gas_price = w3.eth.gas_price
    tx = erc1155.functions.setApprovalForAll(ctf_checksum, True).build_transaction({
        "from": account.address,
        "chainId": chain_id,
        "nonce": nonce,
        "gas": 100_000,
        "maxFeePerGas": gas_price * 2,
        "maxPriorityFeePerGas": w3.to_wei(30, "gwei"),
    })
    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=60)
    if receipt["status"] != 1:
        raise RuntimeError(f"setApprovalForAll reverted: {tx_hash.hex()}")
    log.info("MERGE_APPROVED tx=%s", tx_hash.hex())


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

    Pre-flight checks:
    - Verifies the wallet holds enough ERC1155 tokens for both outcomes
    - Ensures setApprovalForAll is set for the CTF contract
    """
    from urllib.parse import urlparse
    parsed = urlparse(rpc_url)
    rpc_display = f"{parsed.scheme}://{parsed.hostname}...{parsed.path[-6:]}" if parsed.path else f"{parsed.scheme}://{parsed.hostname}"

    log.info("MERGE_INIT rpc=%s │ ctf=%s │ condition=%s │ amount=%d",
             rpc_display, CTF_ADDRESS, condition_id, amount)

    if not condition_id:
        raise ValueError("condition_id is empty — cannot merge")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = w3.eth.account.from_key(private_key)
    ctf_checksum = Web3.to_checksum_address(CTF_ADDRESS)

    # ── Pre-flight: check on-chain ERC1155 balances ──
    erc1155 = w3.eth.contract(address=ctf_checksum, abi=ERC1155_ABI)
    up_token_id = _compute_position_id(condition_id, INDEX_SETS[0])
    down_token_id = _compute_position_id(condition_id, INDEX_SETS[1])

    up_balance = erc1155.functions.balanceOf(account.address, up_token_id).call()
    down_balance = erc1155.functions.balanceOf(account.address, down_token_id).call()
    log.info("MERGE_BALANCES up=%d │ down=%d │ needed=%d", up_balance, down_balance, amount)

    if up_balance < amount or down_balance < amount:
        raise RuntimeError(
            f"Insufficient on-chain balance for merge: "
            f"up={up_balance} down={down_balance} needed={amount}. "
            f"Shares may be held by the CTF Exchange, not the wallet directly."
        )

    # ── Pre-flight: ensure ERC1155 approval for CTF contract ──
    _ensure_ctf_approval(w3, account, CTF_ADDRESS, chain_id)

    # ── Execute merge ──
    contract = w3.eth.contract(address=ctf_checksum, abi=MERGE_ABI)
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
