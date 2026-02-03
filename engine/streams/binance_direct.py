"""
Binance direct WebSocket client for btcusdt@trade stream.

Sub-second trade updates for leading indicator signal.
"""

import json
import threading
import time
from collections.abc import Callable

import websocket

from engine.streams.base import PriceUpdate, StreamSource
from trading.utils.logging import get_logger

logger = get_logger("binance_direct")

BINANCE_WS_URL = "wss://stream.binance.com:9443/ws/btcusdt@trade"


class BinanceDirectStream:
    """
    WebSocket client for Binance btcusdt@trade stream.

    Provides sub-second BTC price updates for lag detection.
    """

    def __init__(
        self,
        on_update: Callable[[PriceUpdate], None] | None = None,
        reconnect_delay: float = 5.0,
    ):
        """
        Args:
            on_update: Callback for each price update
            reconnect_delay: Seconds to wait before reconnecting
        """
        self.on_update = on_update
        self.reconnect_delay = reconnect_delay

        self.ws: websocket.WebSocketApp | None = None
        self.thread: threading.Thread | None = None
        self.running = False
        self.connected = False
        self.reconnect_count = 0

        self._latest_price: float | None = None
        self._latest_timestamp_ms: int | None = None

    def connect(self) -> None:
        """Connect to Binance WebSocket."""
        if self.running:
            return

        self.running = True

        self.ws = websocket.WebSocketApp(
            BINANCE_WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

        logger.info("CONNECTING", BINANCE_WS_URL)

    def _run(self) -> None:
        """Run WebSocket in thread."""
        while self.running:
            try:
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                logger.error("WS_RUN_ERROR", str(e))

            if self.running:
                self.reconnect_count += 1
                logger.warning("RECONNECTING", f"attempt={self.reconnect_count}")
                time.sleep(self.reconnect_delay)

    def _on_open(self, ws) -> None:
        """Handle connection open."""
        self.connected = True
        logger.info("CONNECTED", "Binance direct stream connected")

    def _on_message(self, ws, message: str) -> None:
        """
        Handle incoming trade message.

        Trade message format:
        {
            "e": "trade",
            "E": 1706000000000,  # Event time
            "s": "BTCUSDT",      # Symbol
            "t": 123456789,      # Trade ID
            "p": "42150.50",     # Price
            "q": "0.5",          # Quantity
            "b": 100,            # Buyer order ID
            "a": 101,            # Seller order ID
            "T": 1706000000000,  # Trade time
            "m": true            # Is buyer maker
        }
        """
        try:
            data = json.loads(message)

            if not isinstance(data, dict):
                return

            if data.get("e") != "trade":
                return

            price = float(data["p"])
            trade_time = data["T"]

            # Log first few updates
            if not hasattr(self, "_trade_count"):
                self._trade_count = 0
            self._trade_count += 1
            if self._trade_count <= 3:
                logger.info("TRADE_RECEIVED", f"count={self._trade_count} price=${price:.2f}")

            self._latest_price = price
            self._latest_timestamp_ms = trade_time

            update = PriceUpdate(
                source=StreamSource.BINANCE_DIRECT,
                symbol="BTCUSDT",
                price=price,
                timestamp_ms=trade_time,
                sequence=data.get("t"),
            )

            if self.on_update:
                self.on_update(update)

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error("PARSE_ERROR", f"error={e}")

    def _on_error(self, ws, error) -> None:
        """Handle WebSocket error."""
        logger.error("WS_ERROR", str(error))

    def _on_close(self, ws, close_status_code, close_msg) -> None:
        """Handle connection close."""
        self.connected = False
        logger.warning("DISCONNECTED", f"code={close_status_code} msg={close_msg}")

    def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        self.running = False
        self.connected = False
        if self.ws:
            self.ws.close()
        logger.info("CLOSED", "Binance direct stream disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self.connected

    @property
    def latest_price(self) -> float | None:
        """Get latest price."""
        return self._latest_price

    @property
    def latest_timestamp_ms(self) -> int | None:
        """Get latest timestamp."""
        return self._latest_timestamp_ms
