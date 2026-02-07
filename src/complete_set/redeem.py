"""On-chain redemption of resolved Polymarket positions via ProxyWalletFactory.

CLOB fills settle tokens to the user's proxy wallet (funder address), not
the signer EOA.  All merge / redeem / approval calls therefore need to be
routed through the ProxyWalletFactory contract, which forwards them via the
proxy wallet that actually holds the ERC-1155 conditional tokens.
"""

from __future__ import annotations

import logging

from web3 import Web3

log = logging.getLogger("cs.redeem")

# ── Contract addresses (Polygon mainnet) ──
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
PROXY_WALLET_FACTORY = "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"

# Null parent collection ID (standard for Polymarket top-level conditions)
PARENT_COLLECTION_ID = bytes(32)

# Binary outcome index sets: 0b01 = UP, 0b10 = DOWN
INDEX_SETS = [1, 2]

# CTF tokens use 6 decimals on Polygon (same as USDC)
CTF_DECIMALS = 6

# ── ABIs ──

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

PROXY_FACTORY_ABI = [
    {
        "name": "proxy",
        "type": "function",
        "inputs": [
            {
                "name": "calls",
                "type": "tuple[]",
                "components": [
                    {"name": "typeCode", "type": "uint8"},
                    {"name": "to", "type": "address"},
                    {"name": "value", "type": "uint256"},
                    {"name": "data", "type": "bytes"},
                ],
            }
        ],
        "outputs": [{"name": "", "type": "bytes[]"}],
    }
]

NEG_RISK_MERGE_ABI = [
    {
        "name": "mergePositions",
        "type": "function",
        "inputs": [
            {"name": "_conditionId", "type": "bytes32"},
            {"name": "_amount", "type": "uint256"},
        ],
        "outputs": [],
    }
]

NEG_RISK_REDEEM_ABI = [
    {
        "name": "redeemPositions",
        "type": "function",
        "inputs": [
            {"name": "_conditionId", "type": "bytes32"},
            {"name": "_amounts", "type": "uint256[]"},
        ],
        "outputs": [],
    }
]


# ── Helpers ──

def _compute_position_id(condition_id_hex: str, index_set: int) -> int:
    """Compute ERC1155 token ID for a CTF position."""
    condition_bytes = bytes.fromhex(condition_id_hex.removeprefix("0x"))
    collection_id = Web3.solidity_keccak(
        ["bytes32", "bytes32", "uint256"],
        [PARENT_COLLECTION_ID, condition_bytes, index_set],
    )
    position_id = Web3.solidity_keccak(
        ["address", "bytes32"],
        [Web3.to_checksum_address(USDC_ADDRESS), collection_id],
    )
    return int.from_bytes(position_id, "big")


def _send_proxy_tx(
    w3: Web3,
    account,
    inner_calls: list[tuple],
    chain_id: int,
    gas: int = 500_000,
) -> str:
    """Send a batch of calls through ProxyWalletFactory.proxy().

    Each element of *inner_calls* is (typeCode, to, value, data_bytes).
    Returns the tx hash hex string.
    """
    factory = w3.eth.contract(
        address=Web3.to_checksum_address(PROXY_WALLET_FACTORY),
        abi=PROXY_FACTORY_ABI,
    )
    nonce = w3.eth.get_transaction_count(account.address, "pending")
    gas_price = w3.eth.gas_price

    tx = factory.functions.proxy(inner_calls).build_transaction({
        "from": account.address,
        "chainId": chain_id,
        "nonce": nonce,
        "gas": gas,
        "maxFeePerGas": gas_price * 2,
        "maxPriorityFeePerGas": w3.to_wei(30, "gwei"),
    })

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    log.info("PROXY_TX_SENT tx=%s │ waiting for receipt (timeout=120s)", tx_hash.hex())
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    log.info("PROXY_TX_RECEIPT status=%d │ block=%s │ gasUsed=%s",
             receipt["status"], receipt.get("blockNumber", "?"), receipt.get("gasUsed", "?"))

    if receipt["status"] != 1:
        raise RuntimeError(f"Proxy tx reverted: {tx_hash.hex()}")

    return tx_hash.hex()


def _ensure_ctf_approval(
    w3: Web3, account, funder_address: str, chain_id: int,
    operator_address: str = CTF_ADDRESS,
) -> None:
    """Ensure *operator_address* is approved as ERC1155 operator for the proxy wallet."""
    operator_checksum = Web3.to_checksum_address(operator_address)
    funder_checksum = Web3.to_checksum_address(funder_address)
    ctf_checksum = Web3.to_checksum_address(CTF_ADDRESS)
    erc1155 = w3.eth.contract(address=ctf_checksum, abi=ERC1155_ABI)

    approved = erc1155.functions.isApprovedForAll(funder_checksum, operator_checksum).call()
    if approved:
        return

    log.info("MERGE_APPROVE setting %s as ERC1155 operator for proxy %s", operator_checksum, funder_checksum)

    # Encode setApprovalForAll and route through ProxyWalletFactory
    approval_data = erc1155.encode_abi("setApprovalForAll", [operator_checksum, True])
    _send_proxy_tx(
        w3, account,
        [(1, ctf_checksum, 0, bytes.fromhex(approval_data[2:]))],
        chain_id,
        gas=200_000,
    )
    log.info("MERGE_APPROVED %s via proxy factory", operator_checksum)


# ── Public API ──

def merge_positions(
    private_key: str,
    rpc_url: str,
    condition_id: str,
    amount: int,
    funder_address: str = "",
    chain_id: int = 137,
    neg_risk: bool = False,
) -> str:
    """Merge hedged UP+DOWN positions back to USDC via ProxyWalletFactory.

    amount is in base units (6 decimals).  Returns tx hash hex string.

    No pre-flight balance poll — the engine's retry logic (5 attempts, 60s
    cooldown) handles transient settlement delays, matching the Java bot
    approach.

    When *neg_risk* is True, merges through the NegRiskAdapter instead of CTF.
    """
    from urllib.parse import urlparse
    parsed = urlparse(rpc_url)
    rpc_display = f"{parsed.scheme}://{parsed.hostname}...{parsed.path[-6:]}" if parsed.path else f"{parsed.scheme}://{parsed.hostname}"

    target_label = "NegRiskAdapter" if neg_risk else "CTF"
    log.info("MERGE_INIT rpc=%s │ target=%s │ condition=%s │ amount=%d │ funder=%s │ neg_risk=%s",
             rpc_display, target_label, condition_id, amount,
             funder_address[:10] + "..." if funder_address else "EOA", neg_risk)

    if not condition_id:
        raise ValueError("condition_id is empty — cannot merge")

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = w3.eth.account.from_key(private_key)
    condition_bytes = bytes.fromhex(condition_id.removeprefix("0x"))

    # Determine target contract for merge and approval
    if neg_risk:
        target_address = NEG_RISK_ADAPTER
    else:
        target_address = CTF_ADDRESS
    target_checksum = Web3.to_checksum_address(target_address)

    # ── Pre-flight: ensure ERC1155 approval for target contract ──
    if funder_address:
        _ensure_ctf_approval(w3, account, funder_address, chain_id, operator_address=target_address)
    else:
        _ensure_ctf_approval_eoa(w3, account, chain_id, operator_address=target_address)

    # ── Execute merge ──
    if neg_risk:
        adapter = w3.eth.contract(address=target_checksum, abi=NEG_RISK_MERGE_ABI)
        merge_data = adapter.encode_abi("mergePositions", [condition_bytes, amount])
    else:
        ctf_checksum = Web3.to_checksum_address(CTF_ADDRESS)
        ctf_contract = w3.eth.contract(address=ctf_checksum, abi=MERGE_ABI)
        merge_data = ctf_contract.encode_abi("mergePositions", [
            Web3.to_checksum_address(USDC_ADDRESS),
            PARENT_COLLECTION_ID,
            condition_bytes,
            INDEX_SETS,
            amount,
        ])

    if funder_address:
        log.info("MERGE_VIA_PROXY factory=%s │ target=%s", PROXY_WALLET_FACTORY, target_checksum)
        tx_hash = _send_proxy_tx(
            w3, account,
            [(1, target_checksum, 0, bytes.fromhex(merge_data[2:]))],
            chain_id,
        )
    else:
        # Legacy direct EOA path (only for standard markets)
        ctf_checksum = Web3.to_checksum_address(CTF_ADDRESS)
        ctf_contract = w3.eth.contract(address=ctf_checksum, abi=MERGE_ABI)
        tx_hash = _send_merge_direct(w3, account, ctf_contract, condition_bytes, amount, chain_id)

    return tx_hash


def redeem_positions(
    private_key: str,
    rpc_url: str,
    condition_id: str,
    funder_address: str = "",
    chain_id: int = 137,
    neg_risk: bool = False,
    amount: int = 0,
) -> str:
    """Redeem resolved positions on-chain. Returns tx hash hex string.

    When *neg_risk* is True, redeems through the NegRiskAdapter.
    *amount* is required for NegRisk redeems (passed as [amount, amount]).
    """
    from urllib.parse import urlparse
    parsed = urlparse(rpc_url)
    rpc_display = f"{parsed.scheme}://{parsed.hostname}...{parsed.path[-6:]}" if parsed.path else f"{parsed.scheme}://{parsed.hostname}"

    target_label = "NegRiskAdapter" if neg_risk else "CTF"
    log.info("REDEEM_INIT rpc=%s │ target=%s │ condition=%s │ funder=%s │ neg_risk=%s",
             rpc_display, target_label, condition_id,
             funder_address[:10] + "..." if funder_address else "EOA", neg_risk)

    w3 = Web3(Web3.HTTPProvider(rpc_url))
    account = w3.eth.account.from_key(private_key)

    if not condition_id:
        raise ValueError("condition_id is empty — cannot redeem")
    condition_bytes = bytes.fromhex(condition_id.removeprefix("0x"))

    if neg_risk:
        target_address = NEG_RISK_ADAPTER
    else:
        target_address = CTF_ADDRESS
    target_checksum = Web3.to_checksum_address(target_address)

    if funder_address:
        # Route through ProxyWalletFactory
        if neg_risk:
            adapter = w3.eth.contract(address=target_checksum, abi=NEG_RISK_REDEEM_ABI)
            redeem_data = adapter.encode_abi("redeemPositions", [condition_bytes, [amount, amount]])
        else:
            ctf_checksum = Web3.to_checksum_address(CTF_ADDRESS)
            ctf_contract = w3.eth.contract(address=ctf_checksum, abi=REDEEM_ABI)
            redeem_data = ctf_contract.encode_abi("redeemPositions", [
                Web3.to_checksum_address(USDC_ADDRESS),
                PARENT_COLLECTION_ID,
                condition_bytes,
                INDEX_SETS,
            ])
        log.info("REDEEM_VIA_PROXY factory=%s │ target=%s", PROXY_WALLET_FACTORY, target_checksum)
        return _send_proxy_tx(
            w3, account,
            [(1, target_checksum, 0, bytes.fromhex(redeem_data[2:]))],
            chain_id,
        )

    # Legacy direct EOA path (standard markets only)
    ctf_checksum = Web3.to_checksum_address(CTF_ADDRESS)
    contract = w3.eth.contract(address=ctf_checksum, abi=REDEEM_ABI)

    nonce = w3.eth.get_transaction_count(account.address, "pending")
    gas_price = w3.eth.gas_price

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

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    log.info("REDEEM_SENT tx=%s │ waiting for receipt (timeout=120s)", tx_hash.hex())
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    if receipt["status"] != 1:
        raise RuntimeError(f"Redeem tx reverted: {tx_hash.hex()}")

    return tx_hash.hex()


# ── Legacy EOA helpers (no proxy wallet) ──

def _ensure_ctf_approval_eoa(
    w3: Web3, account, chain_id: int,
    operator_address: str = CTF_ADDRESS,
) -> None:
    """Direct EOA approval — used when no funder/proxy is configured."""
    operator_checksum = Web3.to_checksum_address(operator_address)
    ctf_checksum = Web3.to_checksum_address(CTF_ADDRESS)
    erc1155 = w3.eth.contract(address=ctf_checksum, abi=ERC1155_ABI)

    approved = erc1155.functions.isApprovedForAll(account.address, operator_checksum).call()
    if approved:
        return

    log.info("MERGE_APPROVE setting %s as ERC1155 operator for %s", operator_checksum, account.address)
    nonce = w3.eth.get_transaction_count(account.address, "pending")
    gas_price = w3.eth.gas_price
    tx = erc1155.functions.setApprovalForAll(operator_checksum, True).build_transaction({
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
    log.info("MERGE_APPROVED %s tx=%s", operator_checksum, tx_hash.hex())


def _send_merge_direct(w3, account, contract, condition_bytes, amount, chain_id) -> str:
    """Direct EOA merge — used when no funder/proxy is configured."""
    nonce = w3.eth.get_transaction_count(account.address, "pending")
    gas_price = w3.eth.gas_price

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

    signed = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed.raw_transaction)
    log.info("MERGE_SENT tx=%s │ waiting for receipt (timeout=120s)", tx_hash.hex())
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)

    log.info("MERGE_RECEIPT status=%d │ block=%s │ gasUsed=%s",
             receipt["status"], receipt.get("blockNumber", "?"), receipt.get("gasUsed", "?"))

    if receipt["status"] != 1:
        raise RuntimeError(f"Merge tx reverted: {tx_hash.hex()}")

    return tx_hash.hex()
