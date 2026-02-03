"""
Polymarket RTDS (Real-Time Data Stream) WebSocket client.

Connects to wss://ws-live-data.polymarket.com/ws for:
- crypto_prices: Binance spot prices (one symbol per connection)
- crypto_prices_chainlink: Chainlink oracle prices
"""

import json
import threading
import time
from collections.abc import Callable

import websocket

from src.data.streams.base import PriceUpdate, StreamSource
from src.utils.logging import get_logger

logger = get_logger("rtds")

RTDS_WS_URL = "wss://ws-live-data.polymarket.com"


class RTDSStream:
    """
    WebSocket client for Polymarket RTDS.

    Provides both Binance and Chainlink price feeds.
    Note: crypto_prices channel supports only ONE symbol per connection.
    """

    def __init__(
        self,
        on_binance_update: Callable[[PriceUpdate], None] | None = None,
        on_chainlink_update: Callable[[PriceUpdate], None] | None = None,
        symbol: str = "btcusdt",
        reconnect_delay: float = 5.0,
    ):
        """
        Args:
            on_binance_update: Callback for Binance price updates
            on_chainlink_update: Callback for Chainlink price updates
            symbol: Symbol to subscribe for crypto_prices (e.g., "btcusdt")
            reconnect_delay: Seconds to wait before reconnecting
        """
        self.on_binance_update = on_binance_update
        self.on_chainlink_update = on_chainlink_update
        self.symbol = symbol.lower()
        self.reconnect_delay = reconnect_delay

        self.ws: websocket.WebSocketApp | None = None
        self.thread: threading.Thread | None = None
        self.ping_thread: threading.Thread | None = None
        self.running = False
        self.connected = False
        self.reconnect_count = 0

        self._latest_binance_price: float | None = None
        self._latest_binance_ts: int | None = None
        self._latest_chainlink_price: float | None = None
        self._latest_chainlink_ts: int | None = None

    def connect(self) -> None:
        """Connect to RTDS WebSocket."""
        if self.running:
            return

        self.running = True

        # Headers to bypass Cloudflare
        headers = [
            "User-Agent: Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Origin: https://polymarket.com",
            "Sec-WebSocket-Protocol: graphql-transport-ws",
        ]

        logger.info("CONNECTING", f"url={RTDS_WS_URL} headers={headers}")

        self.ws = websocket.WebSocketApp(
            RTDS_WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
            header=headers,
        )

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def _run(self) -> None:
        """Run WebSocket in thread."""
        while self.running:
            try:
                self.ws.run_forever(ping_interval=0)  # We handle ping manually
            except Exception as e:
                logger.error("WS_RUN_ERROR", str(e))

            if self.running:
                self.reconnect_count += 1
                logger.warning("RECONNECTING", f"attempt={self.reconnect_count}")
                time.sleep(self.reconnect_delay)

    def _on_open(self, ws) -> None:
        """Handle connection open and subscribe to channels."""
        self.connected = True
        logger.info("CONNECTED", "RTDS connected")

        # Subscribe to both channels
        self._subscribe()

        # Start ping thread
        self.ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self.ping_thread.start()

    def _subscribe(self) -> None:
        """Subscribe to crypto_prices and crypto_prices_chainlink."""
        # Note: filters must be omitted (not empty string) or API rejects
        msg = {
            "action": "subscribe",
            "subscriptions": [
                {"topic": "crypto_prices", "type": "update"},
                {"topic": "crypto_prices_chainlink", "type": "*"},
            ],
        }
        msg_json = json.dumps(msg)
        logger.info("SENDING_SUBSCRIBE", f"msg={msg_json}")
        self.ws.send(msg_json)
        logger.info("SUBSCRIBED", f"symbol={self.symbol}")

    def _ping_loop(self) -> None:
        """Send periodic pings."""
        while self.running and self.connected:
            try:
                if self.ws:
                    self.ws.send(json.dumps({"action": "ping"}))
                time.sleep(10)
            except Exception as e:
                logger.error("PING_ERROR", str(e))
                break

    def _on_message(self, ws, message: str) -> None:
        """
        Handle incoming RTDS message.

        Expected formats:
        - crypto_prices: {"topic": "crypto_prices", "data": {"symbol": "btcusdt", "price": "42150.50", ...}}
        - crypto_prices_chainlink: {"topic": "crypto_prices_chainlink", "data": {"btc": {"price": "42150.00", "timestamp": ...}}}
        """
        try:
            # Debug: log first few messages
            if not hasattr(self, "_msg_count"):
                self._msg_count = 0
            self._msg_count += 1
            if self._msg_count <= 5:
                logger.info("RAW_MESSAGE", f"count={self._msg_count} msg={message[:200]}")

            # Handle binary or empty messages
            if isinstance(message, bytes):
                logger.debug("BINARY_MSG", f"len={len(message)}")
                return
            if not message or not message.strip():
                return
            if not message.startswith("{") and not message.startswith("["):
                logger.debug("NON_JSON_MSG", f"msg={message[:100]}")
                return

            data = json.loads(message)

            if not isinstance(data, dict):
                logger.debug("NON_DICT_MSG", f"type={type(data)}")
                return

            topic = data.get("topic")
            # Payload is in "payload" key, not "data"
            payload = data.get("payload", {})

            logger.debug("PARSED_MSG", f"topic={topic} keys={list(data.keys())}")

            if topic == "crypto_prices":
                self._handle_binance_update(payload)
            elif topic == "crypto_prices_chainlink":
                self._handle_chainlink_update(payload)

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug("PARSE_ERROR", f"error={e} msg={message[:100]}")

    def _handle_binance_update(self, payload: dict) -> None:
        """Handle crypto_prices (Binance) update."""
        try:
            # Format: {"symbol": "btcusdt", "value": 78542.54, "timestamp": 1770077127000}
            symbol = payload.get("symbol", "").lower()

            # Filter for our symbol only (feed sends all symbols)
            if symbol != self.symbol:
                return

            price = payload.get("value")
            if price is None:
                return

            price = float(price)
            timestamp_ms = int(payload.get("timestamp", time.time() * 1000))

            self._latest_binance_price = price
            self._latest_binance_ts = timestamp_ms

            update = PriceUpdate(
                source=StreamSource.RTDS_BINANCE,
                symbol=self.symbol.upper(),
                price=price,
                timestamp_ms=timestamp_ms,
            )

            if self.on_binance_update:
                self.on_binance_update(update)

        except (KeyError, TypeError, ValueError) as e:
            logger.debug("BINANCE_PARSE_ERROR", f"error={e}")

    def _handle_chainlink_update(self, payload: dict) -> None:
        """Handle crypto_prices_chainlink update."""
        try:
            # Format: {"symbol": "btc/usd", "value": 78483.94, "timestamp": 1770077127000}
            symbol = payload.get("symbol", "").lower()

            # Filter for BTC only
            if symbol != "btc/usd":
                return

            price = payload.get("value")
            if price is None:
                return

            price = float(price)
            timestamp_ms = int(payload.get("timestamp", time.time() * 1000))

            self._latest_chainlink_price = price
            self._latest_chainlink_ts = timestamp_ms

            update = PriceUpdate(
                source=StreamSource.RTDS_CHAINLINK,
                symbol="BTCUSD",
                price=price,
                timestamp_ms=timestamp_ms,
            )

            if self.on_chainlink_update:
                self.on_chainlink_update(update)

        except (KeyError, TypeError, ValueError) as e:
            logger.debug("CHAINLINK_PARSE_ERROR", f"error={e}")

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
        logger.info("CLOSED", "RTDS stream disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self.connected

    @property
    def latest_binance_price(self) -> float | None:
        """Get latest Binance price."""
        return self._latest_binance_price

    @property
    def latest_chainlink_price(self) -> float | None:
        """Get latest Chainlink price."""
        return self._latest_chainlink_price
