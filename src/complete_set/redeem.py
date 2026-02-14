"""On-chain merge/redeem of Polymarket positions via Gnosis Safe.

Sends direct on-chain transactions through the user's Gnosis Safe (1-of-1),
bypassing the rate-limited Builder Relayer entirely.
"""

from __future__ import annotations

import logging
import math
import time
from decimal import Decimal

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3

log = logging.getLogger("cs.redeem")

# ── Contract addresses (Polygon mainnet) ──
CTF_ADDRESS = "0x4D97DCd97eC945f40cF65F87097ACe5EA0476045"
USDC_ADDRESS = "0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174"
NEG_RISK_ADAPTER = "0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296"

# Null parent collection ID (standard for Polymarket top-level conditions)
PARENT_COLLECTION_ID = bytes(32)

# Binary outcome index sets: 0b01 = UP, 0b10 = DOWN
INDEX_SETS = [1, 2]

# CTF tokens use 6 decimals on Polygon (same as USDC)
CTF_DECIMALS = 6

# ── ABIs ──

ERC20_BALANCE_ABI = [
    {
        "name": "balanceOf",
        "type": "function",
        "inputs": [{"name": "account", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
        "stateMutability": "view",
    }
]

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

SAFE_ABI = [
    {
        "name": "execTransaction",
        "type": "function",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
            {"name": "operation", "type": "uint8"},
            {"name": "safeTxGas", "type": "uint256"},
            {"name": "baseGas", "type": "uint256"},
            {"name": "gasPrice", "type": "uint256"},
            {"name": "gasToken", "type": "address"},
            {"name": "refundReceiver", "type": "address"},
            {"name": "signatures", "type": "bytes"},
        ],
        "outputs": [{"name": "success", "type": "bool"}],
    },
    {
        "name": "nonce",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "getTransactionHash",
        "type": "function",
        "stateMutability": "view",
        "inputs": [
            {"name": "to", "type": "address"},
            {"name": "value", "type": "uint256"},
            {"name": "data", "type": "bytes"},
            {"name": "operation", "type": "uint8"},
            {"name": "safeTxGas", "type": "uint256"},
            {"name": "baseGas", "type": "uint256"},
            {"name": "gasPrice", "type": "uint256"},
            {"name": "gasToken", "type": "address"},
            {"name": "refundReceiver", "type": "address"},
            {"name": "_nonce", "type": "uint256"},
        ],
        "outputs": [{"name": "", "type": "bytes32"}],
    },
]


# ── Helpers ──

def _encode_merge(condition_id: str, amount: int, neg_risk: bool) -> tuple[str, str]:
    """Encode merge calldata. Returns (target_address, encoded_data)."""
    condition_bytes = bytes.fromhex(condition_id.removeprefix("0x"))

    if neg_risk:
        target = Web3.to_checksum_address(NEG_RISK_ADAPTER)
        contract = Web3().eth.contract(address=target, abi=NEG_RISK_MERGE_ABI)
        data = contract.encode_abi("mergePositions", [condition_bytes, amount])
    else:
        target = Web3.to_checksum_address(CTF_ADDRESS)
        contract = Web3().eth.contract(address=target, abi=MERGE_ABI)
        data = contract.encode_abi("mergePositions", [
            Web3.to_checksum_address(USDC_ADDRESS),
            PARENT_COLLECTION_ID,
            condition_bytes,
            INDEX_SETS,
            amount,
        ])
    return target, data


def _encode_redeem(condition_id: str, neg_risk: bool, amount: int = 0) -> tuple[str, str]:
    """Encode redeem calldata. Returns (target_address, encoded_data)."""
    condition_bytes = bytes.fromhex(condition_id.removeprefix("0x"))

    if neg_risk:
        target = Web3.to_checksum_address(NEG_RISK_ADAPTER)
        contract = Web3().eth.contract(address=target, abi=NEG_RISK_REDEEM_ABI)
        data = contract.encode_abi("redeemPositions", [condition_bytes, [amount, amount]])
    else:
        target = Web3.to_checksum_address(CTF_ADDRESS)
        contract = Web3().eth.contract(address=target, abi=REDEEM_ABI)
        data = contract.encode_abi("redeemPositions", [
            Web3.to_checksum_address(USDC_ADDRESS),
            PARENT_COLLECTION_ID,
            condition_bytes,
            INDEX_SETS,
        ])
    return target, data


ZERO_ADDR = "0x0000000000000000000000000000000000000000"


def _send_safe_tx(
    w3: Web3,
    account: LocalAccount,
    safe_address: str,
    to: str,
    data: bytes,
    chain_id: int = 137,
    max_gas_price_gwei: int = 200,
) -> str:
    """Execute a call through a Gnosis Safe v1.3.0 (1-of-1 multisig).

    Builds an execTransaction call with the EOA owner's signature,
    then submits it on-chain from the EOA.
    """
    safe_cs = Web3.to_checksum_address(safe_address)
    to_cs = Web3.to_checksum_address(to)
    from_addr = account.address

    safe = w3.eth.contract(address=safe_cs, abi=SAFE_ABI)

    # Get the Safe's current nonce
    safe_nonce = safe.functions.nonce().call()

    # Get the Safe transaction hash to sign
    # operation=0 (Call), safeTxGas=0, baseGas=0, gasPrice=0,
    # gasToken=0x0, refundReceiver=0x0 — EOA pays gas directly
    safe_tx_hash = safe.functions.getTransactionHash(
        to_cs, 0, data, 0,  # to, value, data, operation=CALL
        0, 0, 0,             # safeTxGas, baseGas, gasPrice
        ZERO_ADDR, ZERO_ADDR,  # gasToken, refundReceiver
        safe_nonce,
    ).call()

    # Sign the hash with the EOA (owner of the 1-of-1 Safe)
    signed = Account.unsafe_sign_hash(safe_tx_hash, account.key)
    # Pack signature as r(32) + s(32) + v(1)
    signature = (
        signed.r.to_bytes(32, "big")
        + signed.s.to_bytes(32, "big")
        + signed.v.to_bytes(1, "big")
    )

    # Encode the execTransaction call
    exec_data = safe.encode_abi("execTransaction", [
        to_cs, 0, data, 0,
        0, 0, 0,
        ZERO_ADDR, ZERO_ADDR,
        signature,
    ])

    # Submit the outer transaction from EOA to Safe
    eoa_nonce = w3.eth.get_transaction_count(from_addr, "latest")
    gas_price_raw = w3.eth.gas_price
    gas_price_gwei = gas_price_raw / 1e9
    if gas_price_gwei > max_gas_price_gwei:
        raise RuntimeError(
            f"Gas price {gas_price_gwei:.0f} gwei exceeds cap {max_gas_price_gwei} gwei"
        )
    gas_price = math.ceil(gas_price_raw * 1.50)

    try:
        gas_estimate = w3.eth.estimate_gas({
            "from": from_addr,
            "to": safe_cs,
            "data": exec_data,
            "value": 0,
        })
        gas_limit = max(21_000, math.ceil(gas_estimate * 1.25))
    except Exception as e:
        log.warning("Gas estimate failed, using fallback 500k: %s", e)
        gas_limit = 500_000

    tx = {
        "chainId": chain_id,
        "from": from_addr,
        "to": safe_cs,
        "data": exec_data,
        "value": 0,
        "gas": gas_limit,
        "gasPrice": gas_price,
        "nonce": eoa_nonce,
    }

    signed_tx = account.sign_transaction(tx)
    tx_hash = w3.eth.send_raw_transaction(signed_tx.raw_transaction)
    tx_hash_hex = tx_hash.hex()
    log.info(
        "TX_SENT hash=%s safe_nonce=%d eoa_nonce=%d gas=%d",
        tx_hash_hex, safe_nonce, eoa_nonce, gas_limit,
    )

    # Poll for receipt: 60 attempts x 1s
    for attempt in range(60):
        time.sleep(1)
        try:
            receipt = w3.eth.get_transaction_receipt(tx_hash)
            if receipt is not None:
                if receipt["status"] != 1:
                    raise RuntimeError(
                        f"Transaction reverted on-chain (tx={tx_hash_hex}, "
                        f"gasUsed={receipt['gasUsed']})"
                    )
                log.info("TX_CONFIRMED hash=%s gasUsed=%d", tx_hash_hex, receipt["gasUsed"])
                return tx_hash_hex
        except Exception as e:
            if "reverted" in str(e).lower():
                raise
            if attempt >= 59:
                raise RuntimeError(f"Receipt not found after 60s (tx={tx_hash_hex})") from e

    raise RuntimeError(f"Receipt not found after 60s (tx={tx_hash_hex})")


# ── Approval cache ──
_approved_pairs: set[tuple[str, str]] = set()  # (safe_address, operator)


def _ensure_approval(
    w3: Web3,
    account: LocalAccount,
    safe_address: str,
    operator: str,
    chain_id: int = 137,
    max_gas_price_gwei: int = 200,
) -> None:
    """Check CTF ERC1155 isApprovedForAll and send setApprovalForAll if needed."""
    safe_cs = Web3.to_checksum_address(safe_address)
    operator_cs = Web3.to_checksum_address(operator)
    cache_key = (safe_cs.lower(), operator_cs.lower())

    if cache_key in _approved_pairs:
        return

    ctf = w3.eth.contract(
        address=Web3.to_checksum_address(CTF_ADDRESS), abi=ERC1155_ABI,
    )
    approved = ctf.functions.isApprovedForAll(safe_cs, operator_cs).call()
    if approved:
        _approved_pairs.add(cache_key)
        return

    log.info("APPROVAL_NEEDED safe=%s operator=%s", safe_cs, operator_cs)
    approval_data = ctf.encode_abi("setApprovalForAll", [operator_cs, True])
    inner_data = bytes.fromhex(approval_data.removeprefix("0x"))
    _send_safe_tx(
        w3, account, safe_address,
        CTF_ADDRESS, inner_data, chain_id,
        max_gas_price_gwei=max_gas_price_gwei,
    )
    _approved_pairs.add(cache_key)
    log.info("APPROVAL_GRANTED safe=%s operator=%s", safe_cs, operator_cs)


# ── Public API ──

def get_usdc_balance(rpc_url: str, wallet: str) -> Decimal:
    """Query on-chain USDC balance for a wallet. Returns human-readable Decimal."""
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    usdc = w3.eth.contract(
        address=Web3.to_checksum_address(USDC_ADDRESS), abi=ERC20_BALANCE_ABI,
    )
    raw = usdc.functions.balanceOf(Web3.to_checksum_address(wallet)).call()
    return Decimal(raw) / Decimal(10 ** CTF_DECIMALS)


def get_ctf_balances(
    rpc_url: str, wallet: str, up_token_id: str, down_token_id: str,
) -> tuple[int, int]:
    """Query on-chain CTF ERC1155 balances for UP and DOWN positions.
    Returns (up_balance, down_balance) in base units (6 decimals).
    """
    w3 = Web3(Web3.HTTPProvider(rpc_url))
    ctf = w3.eth.contract(
        address=Web3.to_checksum_address(CTF_ADDRESS), abi=ERC1155_ABI,
    )
    wallet_cs = Web3.to_checksum_address(wallet)
    up_bal = ctf.functions.balanceOf(wallet_cs, int(up_token_id)).call()
    down_bal = ctf.functions.balanceOf(wallet_cs, int(down_token_id)).call()
    return up_bal, down_bal


def merge_positions(
    w3: Web3,
    account: LocalAccount,
    safe_address: str,
    condition_id: str,
    amount: int,
    neg_risk: bool = False,
    chain_id: int = 137,
    max_gas_price_gwei: int = 200,
) -> str:
    """Merge hedged UP+DOWN positions back to USDC via Gnosis Safe.

    amount is in base units (6 decimals).  Returns tx hash hex string.
    """
    if not condition_id:
        raise ValueError("condition_id is empty — cannot merge")

    target_label = "NegRiskAdapter" if neg_risk else "CTF"
    log.info(
        "MERGE_INIT target=%s │ condition=%s │ amount=%d │ neg_risk=%s",
        target_label, condition_id, amount, neg_risk,
    )

    # Ensure CTF approval for the merge target
    operator = NEG_RISK_ADAPTER if neg_risk else CTF_ADDRESS
    _ensure_approval(
        w3, account, safe_address, operator, chain_id,
        max_gas_price_gwei=max_gas_price_gwei,
    )

    merge_target, merge_data = _encode_merge(condition_id, amount, neg_risk)
    inner_data = bytes.fromhex(merge_data.removeprefix("0x"))
    tx_hash = _send_safe_tx(
        w3, account, safe_address, merge_target, inner_data, chain_id,
        max_gas_price_gwei=max_gas_price_gwei,
    )
    log.info("MERGE_CONFIRMED tx=%s", tx_hash)
    return tx_hash


def redeem_positions(
    w3: Web3,
    account: LocalAccount,
    safe_address: str,
    condition_id: str,
    neg_risk: bool = False,
    amount: int = 0,
    chain_id: int = 137,
    max_gas_price_gwei: int = 200,
) -> str:
    """Redeem resolved positions on-chain via Gnosis Safe.

    Returns tx hash hex string.
    """
    if not condition_id:
        raise ValueError("condition_id is empty — cannot redeem")

    target_label = "NegRiskAdapter" if neg_risk else "CTF"
    log.info(
        "REDEEM_INIT target=%s │ condition=%s │ neg_risk=%s │ amount=%d",
        target_label, condition_id, neg_risk, amount,
    )

    # Ensure CTF approval for the redeem target
    operator = NEG_RISK_ADAPTER if neg_risk else CTF_ADDRESS
    _ensure_approval(
        w3, account, safe_address, operator, chain_id,
        max_gas_price_gwei=max_gas_price_gwei,
    )

    redeem_target, redeem_data = _encode_redeem(condition_id, neg_risk, amount)
    inner_data = bytes.fromhex(redeem_data.removeprefix("0x"))
    tx_hash = _send_safe_tx(
        w3, account, safe_address, redeem_target, inner_data, chain_id,
        max_gas_price_gwei=max_gas_price_gwei,
    )
    log.info("REDEEM_CONFIRMED tx=%s", tx_hash)
    return tx_hash
