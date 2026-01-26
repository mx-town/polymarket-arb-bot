"""
Polymarket CLOB WebSocket client.

Connects to wss://ws-subscriptions-clob.polymarket.com/ws/market
for real-time order book updates.
"""

import json
import time
import threading
from typing import Callable, Optional
from datetime import datetime

import websocket

from src.config import WebSocketConfig
from src.market.state import MarketStateManager
from src.utils.logging import get_logger

logger = get_logger("polymarket_ws")

POLYMARKET_WS_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"


class PolymarketWebSocket:
    """WebSocket client for Polymarket CLOB real-time data"""

    def __init__(
        self,
        config: WebSocketConfig,
        state_manager: MarketStateManager,
        on_update: Optional[Callable[[str], None]] = None,
    ):
        self.config = config
        self.state_manager = state_manager
        self.on_update = on_update  # Callback when market is updated

        self.ws: Optional[websocket.WebSocketApp] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.connected = False
        self.last_ping = 0.0
        self.reconnect_count = 0

    def connect(self):
        """Connect to WebSocket"""
        if self.running:
            return

        self.running = True

        self.ws = websocket.WebSocketApp(
            POLYMARKET_WS_URL,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

        logger.info("CONNECTING", POLYMARKET_WS_URL)

    def _run(self):
        """Run WebSocket in thread"""
        while self.running:
            try:
                self.ws.run_forever(ping_interval=0)  # We handle ping manually
            except Exception as e:
                logger.error("WS_RUN_ERROR", str(e))

            if self.running:
                self.reconnect_count += 1
                logger.warning("RECONNECTING", f"attempt={self.reconnect_count}")
                time.sleep(self.config.reconnect_delay)

    def _on_open(self, ws):
        """Handle connection open"""
        self.connected = True
        logger.info("CONNECTED", "WebSocket connected")

        # Subscribe to all token IDs
        token_ids = self.state_manager.get_all_token_ids()
        if token_ids:
            self._subscribe(token_ids)

        # Start ping thread
        threading.Thread(target=self._ping_loop, daemon=True).start()

    def _subscribe(self, token_ids: list[str]):
        """Subscribe to market channel"""
        msg = {
            "type": "market",
            "assets_ids": token_ids,
        }
        self.ws.send(json.dumps(msg))
        logger.info("SUBSCRIBED", f"tokens={len(token_ids)}")

    def _ping_loop(self):
        """Send periodic pings (Polymarket expects plain string 'ping')"""
        while self.running and self.connected:
            try:
                if self.ws:
                    self.ws.send("ping")
                    self.last_ping = time.time()
                time.sleep(self.config.ping_interval)
            except Exception as e:
                logger.error("PING_ERROR", str(e))
                break

    def _on_message(self, ws, message):
        """Handle incoming message"""
        try:
            # Handle binary messages
            if isinstance(message, bytes):
                logger.debug("BINARY_MSG_RECEIVED", f"len={len(message)}")
                return

            # Handle empty messages (pong responses can be empty)
            if not message or not message.strip():
                return

            # Handle non-JSON text responses
            if not message.startswith('{') and not message.startswith('['):
                if message in ('0', 'pong', 'PONG'):  # heartbeat or pong response
                    return
                logger.warning("SERVER_MESSAGE", message[:100])
                return

            data = json.loads(message)

            # Handle non-dict messages (heartbeats send "0")
            if not isinstance(data, dict):
                logger.debug("HEARTBEAT_RECEIVED", f"value={data}")
                return

            event_type = data.get("event_type")

            # Debug: log first few messages to see what we're receiving
            if not hasattr(self, '_msg_count'):
                self._msg_count = 0
            self._msg_count += 1
            if self._msg_count <= 5:
                logger.info("MSG_RECEIVED", f"count={self._msg_count} event_type={event_type} keys={list(data.keys())[:5]}")

            if event_type == "book":
                self._handle_book(data)
            elif event_type == "price_change":
                self._handle_price_change(data)
            elif event_type == "last_trade_price":
                pass  # Ignore for now
            elif data.get("type") == "pong":
                pass  # Pong received

        except json.JSONDecodeError as e:
            logger.error("PARSE_ERROR", f"error={e} msg_repr={repr(message)[:100]}")
        except Exception as e:
            # Log full message structure for debugging
            logger.error("MESSAGE_HANDLER_ERROR", f"type={type(e).__name__} error={e} keys={list(data.keys()) if isinstance(data, dict) else 'N/A'} msg_preview={str(message)[:200]}")

    def _handle_book(self, data: dict):
        """
        Handle book snapshot.

        {
            "event_type": "book",
            "asset_id": "TOKEN_ID",
            "market": "CONDITION_ID",
            "bids": [["0.52", "1000"], ...],
            "asks": [["0.54", "800"], ...],
            "timestamp": "1706000000000"
        }
        """
        asset_id = data.get("asset_id")
        if not asset_id:
            return

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        # Ensure bids/asks are lists before accessing by index
        if not isinstance(bids, list) or not isinstance(asks, list):
            logger.debug("BOOK_INVALID_FORMAT", f"asset={asset_id} bids_type={type(bids).__name__} asks_type={type(asks).__name__}")
            return

        # Validate nested structure: bids[0] and asks[0] should be lists like ["price", "size"]
        if bids and (not isinstance(bids[0], (list, tuple)) or len(bids[0]) < 2):
            logger.debug("BOOK_INVALID_BID_FORMAT", f"asset={asset_id} bid_entry_type={type(bids[0]).__name__}")
            return
        if asks and (not isinstance(asks[0], (list, tuple)) or len(asks[0]) < 2):
            logger.debug("BOOK_INVALID_ASK_FORMAT", f"asset={asset_id} ask_entry_type={type(asks[0]).__name__}")
            return

        best_bid = float(bids[0][0]) if bids else 0.0
        best_ask = float(asks[0][0]) if asks else 0.0
        bid_size = float(bids[0][1]) if bids else 0.0
        ask_size = float(asks[0][1]) if asks else 0.0

        self.state_manager.update_from_book(
            asset_id, best_bid, best_ask, bid_size, ask_size
        )

        # Notify callback
        market = self.state_manager.get_market_by_token(asset_id)
        if market and self.on_update:
            self.on_update(market.market_id)

    def _handle_price_change(self, data: dict):
        """
        Handle price change.

        {
            "event_type": "price_change",
            "asset_id": "TOKEN_ID",
            "price_changes": [
                {
                    "best_bid": "0.52",
                    "best_ask": "0.54",
                    "last_trade_price": "0.53"
                }
            ]
        }
        """
        asset_id = data.get("asset_id")
        if not asset_id:
            return

        changes = data.get("price_changes", [])
        if not changes or not isinstance(changes, list):
            return

        change = changes[0]
        if not isinstance(change, dict):
            logger.debug("PRICE_CHANGE_INVALID", f"asset={asset_id} change_type={type(change).__name__}")
            return

        best_bid = float(change.get("best_bid", 0))
        best_ask = float(change.get("best_ask", 0))

        if best_bid > 0 and best_ask > 0:
            self.state_manager.update_from_book(asset_id, best_bid, best_ask)

            market = self.state_manager.get_market_by_token(asset_id)
            if market and self.on_update:
                self.on_update(market.market_id)

    def _on_error(self, ws, error):
        """Handle WebSocket error"""
        logger.error("WS_ERROR", str(error))

    def _on_close(self, ws, close_status_code, close_msg):
        """Handle connection close"""
        self.connected = False
        logger.warning("DISCONNECTED", f"code={close_status_code} msg={close_msg}")

    def disconnect(self):
        """Disconnect from WebSocket"""
        self.running = False
        self.connected = False
        if self.ws:
            self.ws.close()
        logger.info("CLOSED", "WebSocket disconnected")

    def add_tokens(self, token_ids: list[str]):
        """Subscribe to additional tokens"""
        if self.connected and token_ids:
            self._subscribe(token_ids)

    @property
    def is_connected(self) -> bool:
        return self.connected
