"""
Data streams for live data collection.

Provides unified interfaces for:
- Binance direct trades (btcusdt@trade)
- Polymarket RTDS (crypto_prices + chainlink)
- Chainlink on-chain RPC polling
- CLOB order book adapter
"""

from engine.streams.base import OrderBookUpdate, PriceUpdate

__all__ = ["PriceUpdate", "OrderBookUpdate"]
