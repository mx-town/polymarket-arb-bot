"""
Binance Historical Data Fetcher

Fetches historical 1-minute candles from Binance API for probability model research.
Supports rate limiting, checkpointing, and incremental updates.
"""

import os
import time
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from dataclasses import dataclass, asdict

import requests
import pandas as pd

logger = logging.getLogger(__name__)

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"
RATE_LIMIT_DELAY = 0.1  # 100ms between requests (safe for Binance limits)
MAX_CANDLES_PER_REQUEST = 1000


@dataclass
class CandleData:
    """Single candle data point."""
    open_time: int  # Unix timestamp ms
    open: float
    high: float
    low: float
    close: float
    volume: float
    close_time: int
    quote_volume: float
    trades: int
    taker_buy_base: float
    taker_buy_quote: float


class BinanceHistoricalFetcher:
    """
    Fetches and stores historical candle data from Binance.

    Features:
    - Fetches 1-minute candles for BTC/USDT (primary) and other symbols
    - Supports incremental updates (only fetches missing data)
    - Checkpoints progress for resumable downloads
    - Rate limiting to avoid API bans

    Usage:
        fetcher = BinanceHistoricalFetcher(data_dir="research/data/raw")
        df = fetcher.fetch("BTCUSDT", months=6)
    """

    def __init__(self, data_dir: str = "research/data/raw"):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.session = requests.Session()

    def _get_cache_path(self, symbol: str, interval: str = "1m") -> Path:
        """Get path for cached data file."""
        return self.data_dir / f"{symbol}_{interval}.parquet"

    def _get_checkpoint_path(self, symbol: str, interval: str = "1m") -> Path:
        """Get path for download checkpoint."""
        return self.data_dir / f"{symbol}_{interval}_checkpoint.json"

    def _fetch_klines(
        self,
        symbol: str,
        interval: str,
        start_time: int,
        end_time: int,
        limit: int = MAX_CANDLES_PER_REQUEST
    ) -> list[CandleData]:
        """Fetch candles from Binance API."""
        params = {
            "symbol": symbol,
            "interval": interval,
            "startTime": start_time,
            "endTime": end_time,
            "limit": limit
        }

        response = self.session.get(BINANCE_KLINES_URL, params=params)
        response.raise_for_status()

        candles = []
        for row in response.json():
            candles.append(CandleData(
                open_time=int(row[0]),
                open=float(row[1]),
                high=float(row[2]),
                low=float(row[3]),
                close=float(row[4]),
                volume=float(row[5]),
                close_time=int(row[6]),
                quote_volume=float(row[7]),
                trades=int(row[8]),
                taker_buy_base=float(row[9]),
                taker_buy_quote=float(row[10])
            ))

        return candles

    def fetch(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1m",
        months: int = 6,
        end_date: Optional[datetime] = None
    ) -> pd.DataFrame:
        """
        Fetch historical candle data.

        Args:
            symbol: Trading pair (e.g., BTCUSDT)
            interval: Candle interval (1m for this research)
            months: Number of months of history to fetch
            end_date: End date (defaults to now)

        Returns:
            DataFrame with columns: open_time, open, high, low, close, volume, etc.
        """
        if end_date is None:
            end_date = datetime.utcnow()

        start_date = end_date - timedelta(days=months * 30)

        start_ms = int(start_date.timestamp() * 1000)
        end_ms = int(end_date.timestamp() * 1000)

        # Check for existing data
        cache_path = self._get_cache_path(symbol, interval)
        checkpoint_path = self._get_checkpoint_path(symbol, interval)

        existing_df = None
        if cache_path.exists():
            existing_df = pd.read_parquet(cache_path)
            logger.info(f"Loaded {len(existing_df)} existing candles from cache")

            # Only fetch data after the last candle
            last_time = existing_df["open_time"].max()
            if last_time >= end_ms - 60000:  # Within 1 minute of end
                logger.info("Cache is up to date")
                return existing_df

            start_ms = last_time + 60000  # Start 1 minute after last candle

        # Load checkpoint if exists
        if checkpoint_path.exists():
            with open(checkpoint_path) as f:
                checkpoint = json.load(f)
                start_ms = max(start_ms, checkpoint.get("last_time", start_ms))

        # Calculate total candles to fetch
        total_minutes = (end_ms - start_ms) // 60000
        logger.info(f"Fetching {total_minutes:,} candles for {symbol} ({interval})")

        all_candles = []
        current_ms = start_ms
        fetch_count = 0

        while current_ms < end_ms:
            try:
                candles = self._fetch_klines(
                    symbol=symbol,
                    interval=interval,
                    start_time=current_ms,
                    end_time=end_ms,
                    limit=MAX_CANDLES_PER_REQUEST
                )

                if not candles:
                    break

                all_candles.extend(candles)
                current_ms = candles[-1].open_time + 60000
                fetch_count += 1

                # Progress logging every 10 requests
                if fetch_count % 10 == 0:
                    progress = (current_ms - start_ms) / (end_ms - start_ms) * 100
                    logger.info(
                        f"Progress: {progress:.1f}% - {len(all_candles):,} candles fetched"
                    )

                    # Save checkpoint
                    with open(checkpoint_path, "w") as f:
                        json.dump({"last_time": current_ms}, f)

                # Rate limiting
                time.sleep(RATE_LIMIT_DELAY)

            except requests.exceptions.RequestException as e:
                logger.error(f"API error: {e}, retrying in 5s...")
                time.sleep(5)
                continue

        # Convert to DataFrame
        if all_candles:
            new_df = pd.DataFrame([asdict(c) for c in all_candles])

            # Merge with existing data
            if existing_df is not None:
                df = pd.concat([existing_df, new_df], ignore_index=True)
                df = df.drop_duplicates(subset=["open_time"]).sort_values("open_time")
            else:
                df = new_df

            # Save to cache
            df.to_parquet(cache_path, index=False)
            logger.info(f"Saved {len(df):,} candles to {cache_path}")

            # Remove checkpoint
            if checkpoint_path.exists():
                checkpoint_path.unlink()

            return df

        return existing_df if existing_df is not None else pd.DataFrame()

    def get_data(self, symbol: str = "BTCUSDT", interval: str = "1m") -> Optional[pd.DataFrame]:
        """Load cached data without fetching."""
        cache_path = self._get_cache_path(symbol, interval)
        if cache_path.exists():
            return pd.read_parquet(cache_path)
        return None

    def get_data_range(
        self,
        symbol: str = "BTCUSDT",
        interval: str = "1m",
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> pd.DataFrame:
        """Load cached data filtered by date range."""
        df = self.get_data(symbol, interval)
        if df is None:
            return pd.DataFrame()

        if start_date:
            start_ms = int(start_date.timestamp() * 1000)
            df = df[df["open_time"] >= start_ms]

        if end_date:
            end_ms = int(end_date.timestamp() * 1000)
            df = df[df["open_time"] <= end_ms]

        return df


def fetch_all_symbols(months: int = 6) -> dict[str, pd.DataFrame]:
    """Convenience function to fetch data for all supported symbols."""
    symbols = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "XRPUSDT", "BNBUSDT"]
    fetcher = BinanceHistoricalFetcher()

    results = {}
    for symbol in symbols:
        logger.info(f"Fetching {symbol}...")
        results[symbol] = fetcher.fetch(symbol, months=months)

    return results


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # Fetch 6 months of BTC data
    fetcher = BinanceHistoricalFetcher()
    df = fetcher.fetch("BTCUSDT", months=6)

    print(f"\nDataset Summary:")
    print(f"  Total candles: {len(df):,}")
    print(f"  Date range: {pd.to_datetime(df['open_time'].min(), unit='ms')} to "
          f"{pd.to_datetime(df['open_time'].max(), unit='ms')}")
    print(f"  Price range: ${df['low'].min():,.2f} - ${df['high'].max():,.2f}")
