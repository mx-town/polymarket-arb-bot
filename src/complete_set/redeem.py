"""On-chain merge/redeem of Polymarket positions via the Builder Relayer.

Uses the Polymarket Relayer Client for gasless, atomic execution.
The relayer routes transactions through the user's proxy wallet (Safe),
handling nonce management, gas, and batching automatically.
"""

from __future__ import annotations

import logging

from py_builder_relayer_client.models import OperationType, SafeTransaction
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


# ── Helpers ──

def _encode_approval(operator_address: str) -> str:
    """Encode setApprovalForAll(operator, true) on the CTF ERC1155."""
    ctf = Web3().eth.contract(
        address=Web3.to_checksum_address(CTF_ADDRESS), abi=ERC1155_ABI,
    )
    return ctf.encode_abi("setApprovalForAll", [
        Web3.to_checksum_address(operator_address), True,
    ])


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


# ── Public API ──

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
    relay_client,
    condition_id: str,
    amount: int,
    neg_risk: bool = False,
) -> str:
    """Merge hedged UP+DOWN positions back to USDC via the Polymarket Relayer.

    Sends an atomic batch: [setApprovalForAll, mergePositions].
    Approval is idempotent — if already set, it's a gasless no-op.

    amount is in base units (6 decimals).  Returns tx hash hex string.
    """
    if not condition_id:
        raise ValueError("condition_id is empty — cannot merge")

    target_label = "NegRiskAdapter" if neg_risk else "CTF"
    target_address = NEG_RISK_ADAPTER if neg_risk else CTF_ADDRESS
    log.info(
        "MERGE_INIT target=%s │ condition=%s │ amount=%d │ neg_risk=%s",
        target_label, condition_id, amount, neg_risk,
    )

    # Build batch: approval + merge
    approval_data = _encode_approval(target_address)
    merge_target, merge_data = _encode_merge(condition_id, amount, neg_risk)

    transactions = [
        SafeTransaction(
            to=Web3.to_checksum_address(CTF_ADDRESS),
            operation=OperationType.Call,
            data=approval_data,
            value="0",
        ),
        SafeTransaction(
            to=merge_target,
            operation=OperationType.Call,
            data=merge_data,
            value="0",
        ),
    ]

    resp = relay_client.execute(transactions, "merge positions")
    log.info("MERGE_SUBMITTED tx_id=%s │ waiting for confirmation", resp.transaction_id)

    result = resp.wait()
    if result is None:
        raise RuntimeError(
            f"Merge reverted on-chain (tx_id={resp.transaction_id}, "
            f"tx_hash={resp.transaction_hash})"
        )
    tx_hash = resp.transaction_hash
    log.info("MERGE_CONFIRMED tx=%s", tx_hash)
    return tx_hash


def redeem_positions(
    relay_client,
    condition_id: str,
    neg_risk: bool = False,
    amount: int = 0,
) -> str:
    """Redeem resolved positions on-chain via the Polymarket Relayer.

    Returns tx hash hex string.
    """
    if not condition_id:
        raise ValueError("condition_id is empty — cannot redeem")

    target_label = "NegRiskAdapter" if neg_risk else "CTF"
    log.info(
        "REDEEM_INIT target=%s │ condition=%s │ neg_risk=%s │ amount=%d",
        target_label, condition_id, neg_risk, amount,
    )

    redeem_target, redeem_data = _encode_redeem(condition_id, neg_risk, amount)

    transactions = [
        SafeTransaction(
            to=redeem_target,
            operation=OperationType.Call,
            data=redeem_data,
            value="0",
        ),
    ]

    resp = relay_client.execute(transactions, "redeem positions")
    log.info("REDEEM_SUBMITTED tx_id=%s │ waiting for confirmation", resp.transaction_id)

    result = resp.wait()
    if result is None:
        raise RuntimeError(
            f"Redeem reverted on-chain (tx_id={resp.transaction_id}, "
            f"tx_hash={resp.transaction_hash})"
        )
    tx_hash = resp.transaction_hash
    log.info("REDEEM_CONFIRMED tx=%s", tx_hash)
    return tx_hash
