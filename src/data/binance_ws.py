"""
Binance WebSocket client for real-time spot price data.

Connects to aggTrade streams for BTC and ETH.
Used for lag arbitrage: detecting spot moves before Polymarket reprices.
"""

import json
import time
import threading
from typing import Callable, Optional, List
from dataclasses import dataclass
from datetime import datetime

import websocket

from src.utils.logging import get_logger

logger = get_logger("binance_ws")


@dataclass
class AggTrade:
    """Aggregated trade from Binance"""

    symbol: str  # e.g., "BTCUSDT"
    price: float
    quantity: float
    trade_time: int  # Unix ms
    is_buyer_maker: bool  # True = sell pressure, False = buy pressure

    @property
    def direction(self) -> str:
        """Trade direction: 'buy' or 'sell'"""
        return "sell" if self.is_buyer_maker else "buy"

    @property
    def timestamp(self) -> datetime:
        return datetime.fromtimestamp(self.trade_time / 1000)


class BinanceWebSocket:
    """
    WebSocket client for Binance aggTrade streams.

    Streams:
    - wss://stream.binance.com:9443/ws/btcusdt@aggTrade
    - wss://stream.binance.com:9443/ws/ethusdt@aggTrade

    Or combined:
    - wss://stream.binance.com:9443/stream?streams=btcusdt@aggTrade/ethusdt@aggTrade
    """

    BINANCE_WS_BASE = "wss://stream.binance.com:9443"

    def __init__(
        self,
        symbols: List[str] = None,
        on_trade: Optional[Callable[[AggTrade], None]] = None,
        reconnect_delay: float = 5.0,
    ):
        """
        Args:
            symbols: List of symbols to track (e.g., ["BTCUSDT", "ETHUSDT"])
            on_trade: Callback for each trade
            reconnect_delay: Seconds to wait before reconnecting
        """
        self.symbols = symbols or ["BTCUSDT", "ETHUSDT"]
        self.on_trade = on_trade
        self.reconnect_delay = reconnect_delay

        self.ws: Optional[websocket.WebSocketApp] = None
        self.thread: Optional[threading.Thread] = None
        self.running = False
        self.connected = False
        self.reconnect_count = 0

        # Track latest prices
        self.latest_prices: dict[str, float] = {}
        self.latest_trades: dict[str, AggTrade] = {}

    def _build_url(self) -> str:
        """Build WebSocket URL for combined streams"""
        streams = "/".join(f"{s.lower()}@aggTrade" for s in self.symbols)
        return f"{self.BINANCE_WS_BASE}/stream?streams={streams}"

    def connect(self):
        """Connect to Binance WebSocket"""
        if self.running:
            return

        self.running = True
        url = self._build_url()

        self.ws = websocket.WebSocketApp(
            url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )

        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

        logger.info("CONNECTING", url)

    def _run(self):
        """Run WebSocket in thread"""
        while self.running:
            try:
                # Binance sends pings automatically, we just need to respond
                self.ws.run_forever(ping_interval=20, ping_timeout=10)
            except Exception as e:
                logger.error("WS_RUN_ERROR", str(e))

            if self.running:
                self.reconnect_count += 1
                logger.warning("RECONNECTING", f"attempt={self.reconnect_count}")
                time.sleep(self.reconnect_delay)

    def _on_open(self, ws):
        """Handle connection open"""
        self.connected = True
        logger.info("CONNECTED", f"symbols={self.symbols}")

    def _on_message(self, ws, message: str):
        """
        Handle incoming message.

        Combined stream format:
        {
            "stream": "btcusdt@aggTrade",
            "data": {
                "e": "aggTrade",
                "E": 1706000000000,  # Event time
                "s": "BTCUSDT",      # Symbol
                "a": 123456789,      # Aggregate trade ID
                "p": "42150.50",     # Price
                "q": "0.5",          # Quantity
                "f": 100,            # First trade ID
                "l": 105,            # Last trade ID
                "T": 1706000000000,  # Trade time
                "m": true            # Is buyer maker
            }
        }
        """
        try:
            msg = json.loads(message)

            # Combined stream format
            if "stream" in msg and "data" in msg:
                data = msg["data"]
            else:
                data = msg

            if data.get("e") != "aggTrade":
                return

            trade = AggTrade(
                symbol=data["s"],
                price=float(data["p"]),
                quantity=float(data["q"]),
                trade_time=data["T"],
                is_buyer_maker=data["m"],
            )

            # Update latest
            self.latest_prices[trade.symbol] = trade.price
            self.latest_trades[trade.symbol] = trade

            # Callback
            if self.on_trade:
                self.on_trade(trade)

        except (json.JSONDecodeError, KeyError) as e:
            logger.error("PARSE_ERROR", f"error={e}")

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
        logger.info("CLOSED", "Binance WebSocket disconnected")

    def get_price(self, symbol: str) -> Optional[float]:
        """Get latest price for a symbol"""
        return self.latest_prices.get(symbol.upper())

    def get_latest_trade(self, symbol: str) -> Optional[AggTrade]:
        """Get latest trade for a symbol"""
        return self.latest_trades.get(symbol.upper())

    @property
    def is_connected(self) -> bool:
        return self.connected
