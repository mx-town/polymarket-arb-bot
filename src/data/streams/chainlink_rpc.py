"""
Chainlink on-chain RPC poller.

Polls the Chainlink BTC/USD aggregator on Polygon every 2 seconds.
Used as fallback/verification for RTDS Chainlink feed.
"""

import threading
import time
from collections.abc import Callable

from src.data.streams.base import PriceUpdate, StreamSource
from src.utils.logging import get_logger

logger = get_logger("chainlink_rpc")

# Chainlink BTC/USD Aggregator on Polygon
CHAINLINK_BTC_USD_ADDRESS = "0xc907E116054Ad103354f2D350FD2514433D57F6f"

# Polygon RPC endpoints (green privacy only, ordered by latency)
POLYGON_RPC_URLS = [
    "https://polygon-bor-rpc.publicnode.com",  # 0.154s, green privacy
    "https://polygon.drpc.org",  # 0.731s, green privacy
]

# ABI for latestRoundData
AGGREGATOR_ABI = [
    {
        "inputs": [],
        "name": "latestRoundData",
        "outputs": [
            {"internalType": "uint80", "name": "roundId", "type": "uint80"},
            {"internalType": "int256", "name": "answer", "type": "int256"},
            {"internalType": "uint256", "name": "startedAt", "type": "uint256"},
            {"internalType": "uint256", "name": "updatedAt", "type": "uint256"},
            {"internalType": "uint80", "name": "answeredInRound", "type": "uint80"},
        ],
        "stateMutability": "view",
        "type": "function",
    },
    {
        "inputs": [],
        "name": "decimals",
        "outputs": [{"internalType": "uint8", "name": "", "type": "uint8"}],
        "stateMutability": "view",
        "type": "function",
    },
]


class ChainlinkRPCPoller:
    """
    Polls Chainlink BTC/USD aggregator on Polygon.

    Uses web3.py to read latestRoundData every poll_interval seconds.
    """

    def __init__(
        self,
        on_update: Callable[[PriceUpdate], None] | None = None,
        poll_interval: float = 2.0,
        rpc_urls: list[str] | None = None,
    ):
        """
        Args:
            on_update: Callback for each price update
            poll_interval: Seconds between polls
            rpc_urls: List of RPC URLs to try
        """
        self.on_update = on_update
        self.poll_interval = poll_interval
        self.rpc_urls = rpc_urls or POLYGON_RPC_URLS

        self.thread: threading.Thread | None = None
        self.running = False
        self.connected = False

        self._web3 = None
        self._contract = None
        self._decimals = 8  # Default for Chainlink
        self._current_rpc_index = 0

        self._latest_price: float | None = None
        self._latest_timestamp_ms: int | None = None
        self._latest_round_id: int | None = None

    def _init_web3(self) -> bool:
        """Initialize web3 connection."""
        try:
            from web3 import Web3

            # Try each RPC URL until one works
            for i, url in enumerate(self.rpc_urls):
                try:
                    w3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 10}))
                    if w3.is_connected():
                        self._web3 = w3
                        self._current_rpc_index = i
                        self._contract = w3.eth.contract(
                            address=Web3.to_checksum_address(CHAINLINK_BTC_USD_ADDRESS),
                            abi=AGGREGATOR_ABI,
                        )
                        # Get decimals
                        self._decimals = self._contract.functions.decimals().call()
                        logger.info("WEB3_CONNECTED", f"rpc={url} decimals={self._decimals}")
                        return True
                except Exception as e:
                    logger.warning("RPC_FAILED", f"url={url} error={e}")
                    continue

            logger.error("ALL_RPC_FAILED", "Could not connect to any Polygon RPC")
            return False

        except ImportError:
            logger.error("WEB3_NOT_INSTALLED", "web3 package required: pip install web3")
            return False

    def connect(self) -> None:
        """Start polling."""
        if self.running:
            return

        if not self._init_web3():
            return

        self.running = True
        self.connected = True

        self.thread = threading.Thread(target=self._poll_loop, daemon=True)
        self.thread.start()

        logger.info("POLLING_STARTED", f"interval={self.poll_interval}s")

    def _poll_loop(self) -> None:
        """Poll Chainlink aggregator."""
        backoff = 0
        consecutive_errors = 0

        while self.running:
            # Apply backoff if needed
            if backoff > 0:
                time.sleep(backoff)
                backoff = 0

            try:
                self._poll_once()
                consecutive_errors = 0
            except Exception as e:
                error_str = str(e)
                consecutive_errors += 1

                # Check for rate limit errors
                if "rate limit" in error_str.lower() or "-32090" in error_str:
                    backoff = min(30, 10 * consecutive_errors)  # Exponential backoff, max 30s
                    logger.warning(
                        "RATE_LIMITED", f"backoff={backoff}s errors={consecutive_errors}"
                    )
                else:
                    logger.error("POLL_ERROR", error_str)
                    # Try to reconnect on non-rate-limit errors
                    if consecutive_errors >= 3:
                        self._init_web3()
                        consecutive_errors = 0

            time.sleep(self.poll_interval)

    def _poll_once(self) -> None:
        """Execute a single poll."""
        if not self._contract:
            return

        try:
            # Call latestRoundData
            result = self._contract.functions.latestRoundData().call()
            round_id, answer, started_at, updated_at, answered_in_round = result

            # Convert price (answer is scaled by 10^decimals)
            price = answer / (10**self._decimals)
            timestamp_ms = updated_at * 1000

            # Skip if same round
            if self._latest_round_id == round_id:
                return

            # Log first few updates
            if not hasattr(self, "_poll_count"):
                self._poll_count = 0
            self._poll_count += 1
            if self._poll_count <= 3:
                logger.info(
                    "POLL_RESULT", f"count={self._poll_count} price=${price:.2f} round={round_id}"
                )

            self._latest_price = price
            self._latest_timestamp_ms = timestamp_ms
            self._latest_round_id = round_id

            update = PriceUpdate(
                source=StreamSource.CHAINLINK_RPC,
                symbol="BTCUSD",
                price=price,
                timestamp_ms=timestamp_ms,
                sequence=round_id,
            )

            if self.on_update:
                self.on_update(update)

        except Exception as e:
            logger.error("POLL_CALL_ERROR", str(e))
            raise

    def disconnect(self) -> None:
        """Stop polling."""
        self.running = False
        self.connected = False
        logger.info("POLLING_STOPPED", "Chainlink RPC poller stopped")

    @property
    def is_connected(self) -> bool:
        """Check if polling is active."""
        return self.connected and self._web3 is not None

    @property
    def latest_price(self) -> float | None:
        """Get latest price."""
        return self._latest_price

    @property
    def latest_timestamp_ms(self) -> int | None:
        """Get latest timestamp."""
        return self._latest_timestamp_ms
