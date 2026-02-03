"""
CLOB adapter for order book updates.

Wraps the existing polymarket_ws.py to provide OrderBookUpdate dataclass.
"""

import threading
import time
from collections.abc import Callable

from engine.streams.base import OrderBookUpdate
from trading.market.state import MarketStateManager
from trading.utils.logging import get_logger

logger = get_logger("clob_adapter")


class CLOBAdapter:
    """
    Adapter for Polymarket CLOB WebSocket.

    Wraps MarketStateManager and emits OrderBookUpdate on changes.
    """

    def __init__(
        self,
        state_manager: MarketStateManager,
        on_update: Callable[[OrderBookUpdate], None] | None = None,
    ):
        """
        Args:
            state_manager: MarketStateManager tracking market state
            on_update: Callback for order book updates
        """
        self.state_manager = state_manager
        self.on_update = on_update

        self._ws = None
        self._previous_states: dict[str, tuple[float, float]] = {}

    def connect(self, ws_config) -> None:
        """
        Connect to CLOB WebSocket.

        Args:
            ws_config: WebSocketConfig for connection settings
        """
        from trading.data.polymarket_ws import PolymarketWebSocket

        self._ws = PolymarketWebSocket(
            config=ws_config,
            state_manager=self.state_manager,
            on_update=self._on_market_update,
        )
        self._ws.connect()
        logger.info("CONNECTED", "CLOB adapter connected")

    def _on_market_update(self, market_id: str) -> None:
        """Handle market update from PolymarketWebSocket."""
        if not self.on_update:
            return

        market = self.state_manager.get_market(market_id)
        if not market:
            return

        timestamp_ms = int(time.time() * 1000)

        # Emit update for UP token
        if market.up_bid is not None and market.up_ask is not None:
            # Check if changed
            prev_up = self._previous_states.get(f"{market_id}_up")
            current_up = (market.up_bid, market.up_ask)
            if prev_up != current_up:
                self._previous_states[f"{market_id}_up"] = current_up
                update = OrderBookUpdate(
                    token_id=market.up_token_id,
                    best_bid=market.up_bid,
                    best_ask=market.up_ask,
                    bid_size=market.up_bid_size or 0.0,
                    ask_size=market.up_ask_size or 0.0,
                    timestamp_ms=timestamp_ms,
                )
                self.on_update(update)

        # Emit update for DOWN token
        if market.down_bid is not None and market.down_ask is not None:
            prev_down = self._previous_states.get(f"{market_id}_down")
            current_down = (market.down_bid, market.down_ask)
            if prev_down != current_down:
                self._previous_states[f"{market_id}_down"] = current_down
                update = OrderBookUpdate(
                    token_id=market.down_token_id,
                    best_bid=market.down_bid,
                    best_ask=market.down_ask,
                    bid_size=market.down_bid_size or 0.0,
                    ask_size=market.down_ask_size or 0.0,
                    timestamp_ms=timestamp_ms,
                )
                self.on_update(update)

    def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        if self._ws:
            self._ws.disconnect()
        logger.info("DISCONNECTED", "CLOB adapter disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._ws is not None and self._ws.is_connected

    def add_tokens(self, token_ids: list[str]) -> None:
        """Subscribe to additional tokens."""
        if self._ws:
            self._ws.add_tokens(token_ids)


class SimpleCLOBStream:
    """
    Simplified CLOB stream for standalone capture.

    Connects directly to CLOB WebSocket without full MarketStateManager.
    """

    def __init__(
        self,
        token_ids: list[str],
        on_update: Callable[[OrderBookUpdate], None] | None = None,
        reconnect_delay: float = 5.0,
    ):
        """
        Args:
            token_ids: List of token IDs to subscribe to
            on_update: Callback for order book updates
            reconnect_delay: Seconds before reconnect
        """

        self.token_ids = token_ids
        self.on_update = on_update
        self.reconnect_delay = reconnect_delay

        self.ws = None
        self.thread: threading.Thread | None = None
        self.ping_thread: threading.Thread | None = None
        self.running = False
        self.connected = False
        self.reconnect_count = 0

        self._latest_books: dict[str, OrderBookUpdate] = {}
        self._first_book_logged: set[str] = set()  # Track first book per asset

    def connect(self) -> None:
        """Connect to CLOB WebSocket."""
        import websocket

        if self.running:
            return

        self.running = True

        self.ws = websocket.WebSocketApp(
            "wss://ws-subscriptions-clob.polymarket.com/ws/market",
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

        logger.info("CONNECTING", "wss://ws-subscriptions-clob.polymarket.com/ws/market")

    def _run(self) -> None:
        """Run WebSocket in thread."""
        while self.running:
            try:
                self.ws.run_forever(ping_interval=0)
            except Exception as e:
                logger.error("WS_RUN_ERROR", str(e))

            if self.running:
                self.reconnect_count += 1
                logger.warning("RECONNECTING", f"attempt={self.reconnect_count}")
                time.sleep(self.reconnect_delay)

    def _on_open(self, ws) -> None:
        """Handle connection open."""
        import json

        self.connected = True
        logger.info("CONNECTED", "SimpleCLOB connected")

        # Subscribe to tokens (type must be uppercase "MARKET")
        msg = {"assets_ids": self.token_ids, "type": "MARKET"}
        ws.send(json.dumps(msg))
        logger.info("SUBSCRIBED", f"tokens={len(self.token_ids)}")
        logger.debug("SUBSCRIBE_MSG", json.dumps(msg)[:200])

        # Start ping thread
        self.ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self.ping_thread.start()

    def _ping_loop(self) -> None:
        """Send periodic pings."""
        while self.running and self.connected:
            try:
                if self.ws:
                    self.ws.send("ping")
                time.sleep(5)
            except Exception as e:
                logger.error("PING_ERROR", str(e))
                break

    def _on_message(self, ws, message: str) -> None:
        """Handle incoming message."""
        import json

        try:
            if isinstance(message, bytes):
                logger.debug("RAW_BYTES", f"len={len(message)}")
                return
            if not message or not message.strip():
                return
            if not message.startswith("{") and not message.startswith("["):
                logger.debug("RAW_NON_JSON", message[:100])
                return

            # Log raw message for debugging
            logger.debug("RAW_MSG", message[:300])

            data = json.loads(message)

            # Handle batched events (array of messages)
            messages = data if isinstance(data, list) else [data]

            for msg in messages:
                if not isinstance(msg, dict):
                    continue

                event_type = msg.get("event_type")
                timestamp_ms = int(time.time() * 1000)

                if event_type == "book":
                    logger.debug("EVENT_BOOK", f"asset={msg.get('asset_id', '')[:16]}...")
                    self._handle_book(msg, timestamp_ms)
                elif event_type == "price_change":
                    logger.debug(
                        "EVENT_PRICE_CHANGE", f"changes={len(msg.get('price_changes', []))}"
                    )
                    self._handle_price_change(msg, timestamp_ms)
                elif event_type == "last_trade_price":
                    logger.debug(
                        "EVENT_TRADE",
                        f"asset={msg.get('asset_id', '')[:16]}... price={msg.get('price')}",
                    )
                elif event_type:
                    logger.debug("EVENT_OTHER", f"type={event_type}")

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.debug("PARSE_ERROR", f"error={e} msg={message[:100]}")

    def _handle_book(self, data: dict, timestamp_ms: int) -> None:
        """Handle book snapshot.

        Book format from API:
        {
            "bids": [{"price": "0.48", "size": "30"}, ...],
            "asks": [{"price": "0.52", "size": "25"}, ...]
        }
        """
        asset_id = data.get("asset_id")
        if not asset_id:
            return

        bids = data.get("bids", [])
        asks = data.get("asks", [])

        if not isinstance(bids, list) or not isinstance(asks, list):
            return

        # Parse best bid - handle both dict {"price": x} and list [price, size] formats
        best_bid = 0.0
        bid_size = 0.0
        if bids:
            lvl = bids[0]
            if isinstance(lvl, dict):
                best_bid = float(lvl.get("price", 0))
                bid_size = float(lvl.get("size", 0))
            elif isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
                best_bid = float(lvl[0])
                bid_size = float(lvl[1])

        # Parse best ask
        best_ask = 0.0
        ask_size = 0.0
        if asks:
            lvl = asks[0]
            if isinstance(lvl, dict):
                best_ask = float(lvl.get("price", 0))
                ask_size = float(lvl.get("size", 0))
            elif isinstance(lvl, (list, tuple)) and len(lvl) >= 2:
                best_ask = float(lvl[0])
                ask_size = float(lvl[1])

        # Log first book for each asset at INFO level
        if asset_id not in self._first_book_logged:
            self._first_book_logged.add(asset_id)
            logger.info(
                "BOOK_RECEIVED",
                f"asset={asset_id[:16]}... bid={best_bid:.3f} ask={best_ask:.3f}",
            )
        else:
            logger.debug(
                "BOOK_PARSED",
                f"asset={asset_id[:16]}... bid={best_bid:.3f} ask={best_ask:.3f} "
                f"bid_size={bid_size:.1f} ask_size={ask_size:.1f}",
            )

        update = OrderBookUpdate(
            token_id=asset_id,
            best_bid=best_bid,
            best_ask=best_ask,
            bid_size=bid_size,
            ask_size=ask_size,
            timestamp_ms=timestamp_ms,
        )

        self._latest_books[asset_id] = update
        if self.on_update:
            self.on_update(update)

    def _handle_price_change(self, data: dict, timestamp_ms: int) -> None:
        """Handle price change.

        Price change format from API:
        {
            "price_changes": [
                {"asset_id": "...", "best_bid": "0.5", "best_ask": "0.52", "side": "BUY", ...}
            ]
        }
        """
        changes = data.get("price_changes", [])
        if not changes or not isinstance(changes, list):
            return

        for change in changes:
            if not isinstance(change, dict):
                continue

            asset_id = change.get("asset_id")
            if not asset_id:
                continue

            best_bid = float(change.get("best_bid", 0))
            best_ask = float(change.get("best_ask", 0))

            if best_bid > 0 and best_ask > 0:
                # Get previous sizes or default to 0
                prev = self._latest_books.get(asset_id)
                bid_size = prev.bid_size if prev else 0.0
                ask_size = prev.ask_size if prev else 0.0

                logger.debug(
                    "PRICE_CHANGE_PARSED",
                    f"asset={asset_id[:16]}... bid={best_bid:.3f} ask={best_ask:.3f} "
                    f"side={change.get('side', 'N/A')}",
                )

                update = OrderBookUpdate(
                    token_id=asset_id,
                    best_bid=best_bid,
                    best_ask=best_ask,
                    bid_size=bid_size,
                    ask_size=ask_size,
                    timestamp_ms=timestamp_ms,
                )

                self._latest_books[asset_id] = update
                if self.on_update:
                    self.on_update(update)

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
        logger.info("CLOSED", "SimpleCLOB disconnected")

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self.connected

    def get_book(self, token_id: str) -> OrderBookUpdate | None:
        """Get latest order book for a token."""
        return self._latest_books.get(token_id)
