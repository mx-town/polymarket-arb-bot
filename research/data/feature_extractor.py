"""
Feature Extraction Pipeline

Transforms raw 1-minute candle data into labeled windows with features:
- deviation_pct: (current_price - open_price) / open_price
- time_remaining: Minutes until window close
- realized_vol: Std dev of 1-min returns over trailing period
- session: Asia / EU / US / Overlap
- outcome: UP = 1, DOWN = 0
"""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class TradingSession(Enum):
    """Trading session classification based on UTC hour."""
    ASIA = "asia"              # 00:00 - 08:00 UTC
    EUROPE = "europe"          # 08:00 - 13:00 UTC
    US_EU_OVERLAP = "us_eu_overlap"  # 13:00 - 17:00 UTC (peak volatility)
    US = "us"                  # 17:00 - 21:00 UTC
    LATE_US = "late_us"        # 21:00 - 00:00 UTC


class VolatilityRegime(Enum):
    """Volatility tercile classification."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class WindowFeatures:
    """Features extracted for a single time window observation."""
    # Identification
    window_start: int       # Unix timestamp ms
    window_end: int         # Unix timestamp ms
    symbol: str
    window_minutes: int     # 15 or 60

    # Primary features
    deviation_pct: float    # (current - open) / open
    time_remaining: int     # Minutes until window close
    realized_vol: float     # Trailing volatility

    # Momentum features (new)
    velocity: float         # Price change rate ($/sec over lookback)
    acceleration: float     # Rate of velocity change
    candle_phase: float     # Position in window (0.0 = open, 1.0 = close)

    # Categorical features
    session: TradingSession
    vol_regime: Optional[VolatilityRegime]

    # Outcome (for training)
    outcome: Optional[int]  # 1 = UP, 0 = DOWN (None if in-progress)
    final_close: Optional[float]
    window_open: float

    # Metadata
    current_price: float
    high: float
    low: float
    minute_index: int       # Which minute within the window (0-14 or 0-59)


class FeatureExtractor:
    """
    Extracts features from 1-minute candle data for probability model training.

    Creates labeled windows aligned to Polymarket market schedules:
    - 15-minute windows: :00, :15, :30, :45 start times
    - 1-hour windows: :00 start times

    For each minute within a window, generates:
    - deviation_pct: How far price has moved from window open
    - time_remaining: Minutes until window close
    - realized_vol: Rolling volatility estimate
    - session: Trading session classification
    - outcome: UP (1) if close >= open, DOWN (0) otherwise
    """

    def __init__(
        self,
        window_minutes: int = 15,
        vol_lookback_minutes: int = 15,
        vol_percentiles: tuple[float, float] = (33.3, 66.7)
    ):
        """
        Args:
            window_minutes: Window size (15 or 60)
            vol_lookback_minutes: Minutes for volatility calculation
            vol_percentiles: Percentiles for low/medium/high regime boundaries
        """
        self.window_minutes = window_minutes
        self.vol_lookback = vol_lookback_minutes
        self.vol_percentiles = vol_percentiles

    def _get_session(self, hour_utc: int) -> TradingSession:
        """Classify hour into trading session."""
        if 0 <= hour_utc < 8:
            return TradingSession.ASIA
        elif 8 <= hour_utc < 13:
            return TradingSession.EUROPE
        elif 13 <= hour_utc < 17:
            return TradingSession.US_EU_OVERLAP
        elif 17 <= hour_utc < 21:
            return TradingSession.US
        else:
            return TradingSession.LATE_US

    def _calculate_volatility(
        self,
        df: pd.DataFrame,
        end_idx: int,
        lookback: int
    ) -> float:
        """Calculate realized volatility from 1-min returns."""
        start_idx = max(0, end_idx - lookback)
        if start_idx >= end_idx:
            return 0.0

        window = df.iloc[start_idx:end_idx + 1]
        if len(window) < 2:
            return 0.0

        # 1-minute log returns
        returns = np.log(window["close"] / window["close"].shift(1)).dropna()
        if len(returns) == 0:
            return 0.0

        # Annualized volatility (but we keep it in per-minute units for interpretability)
        return returns.std()

    def _calculate_velocity(
        self,
        prices: list[float],
        timestamps: list[int],
        lookback_sec: int = 300  # 5 minutes default
    ) -> float:
        """
        Calculate price velocity ($/second) over lookback window.

        Args:
            prices: List of prices (most recent last)
            timestamps: List of timestamps in ms (most recent last)
            lookback_sec: Lookback window in seconds

        Returns:
            Velocity in $/second (positive = price rising)
        """
        if len(prices) < 2:
            return 0.0

        lookback_ms = lookback_sec * 1000
        current_time = timestamps[-1]
        current_price = prices[-1]

        # Find price at start of lookback window
        start_price = None
        start_time = None
        for i in range(len(timestamps) - 1, -1, -1):
            if current_time - timestamps[i] >= lookback_ms:
                start_price = prices[i]
                start_time = timestamps[i]
                break

        if start_price is None or start_time is None:
            # Use earliest available if lookback not fully available
            start_price = prices[0]
            start_time = timestamps[0]

        time_delta_sec = (current_time - start_time) / 1000
        if time_delta_sec <= 0:
            return 0.0

        return (current_price - start_price) / time_delta_sec

    def _calculate_acceleration(
        self,
        velocities: list[float],
        timestamps: list[int],
        lookback_sec: int = 300
    ) -> float:
        """
        Calculate acceleration (change in velocity over time).

        Args:
            velocities: List of velocity values (most recent last)
            timestamps: List of timestamps in ms
            lookback_sec: Lookback window in seconds

        Returns:
            Acceleration in $/sec^2
        """
        if len(velocities) < 2:
            return 0.0

        lookback_ms = lookback_sec * 1000
        current_time = timestamps[-1]
        current_velocity = velocities[-1]

        # Find velocity at start of lookback window
        start_velocity = None
        start_time = None
        for i in range(len(timestamps) - 1, -1, -1):
            if current_time - timestamps[i] >= lookback_ms:
                start_velocity = velocities[i]
                start_time = timestamps[i]
                break

        if start_velocity is None or start_time is None:
            start_velocity = velocities[0]
            start_time = timestamps[0]

        time_delta_sec = (current_time - start_time) / 1000
        if time_delta_sec <= 0:
            return 0.0

        return (current_velocity - start_velocity) / time_delta_sec

    def _align_to_window_start(self, timestamp_ms: int) -> int:
        """Align timestamp to window boundary."""
        dt = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)

        if self.window_minutes == 15:
            # Align to :00, :15, :30, :45
            minute_aligned = (dt.minute // 15) * 15
        elif self.window_minutes == 60:
            # Align to :00
            minute_aligned = 0
        else:
            raise ValueError(f"Unsupported window size: {self.window_minutes}")

        aligned = dt.replace(minute=minute_aligned, second=0, microsecond=0)
        return int(aligned.timestamp() * 1000)

    def extract_windows(
        self,
        df: pd.DataFrame,
        symbol: str = "BTCUSDT"
    ) -> pd.DataFrame:
        """
        Extract all window observations from candle data.

        Returns DataFrame with one row per (window, minute) observation,
        containing all features needed for probability model.
        """
        if len(df) < self.window_minutes:
            logger.warning(f"Insufficient data: {len(df)} candles")
            return pd.DataFrame()

        # Sort by time
        df = df.sort_values("open_time").reset_index(drop=True)

        # Pre-compute volatility for all rows
        df["vol"] = df["close"].pct_change().rolling(self.vol_lookback).std()

        features_list = []

        # Find window boundaries
        first_time = df["open_time"].iloc[0]
        last_time = df["open_time"].iloc[-1]

        window_start = self._align_to_window_start(first_time)
        window_end_delta = self.window_minutes * 60 * 1000

        windows_processed = 0

        while window_start + window_end_delta <= last_time:
            window_end = window_start + window_end_delta

            # Get candles within this window
            mask = (df["open_time"] >= window_start) & (df["open_time"] < window_end)
            window_df = df[mask]

            if len(window_df) == 0:
                window_start += window_end_delta
                continue

            # Window open price (first candle's open)
            window_open = window_df.iloc[0]["open"]
            # Window close price (last candle's close)
            final_close = window_df.iloc[-1]["close"]
            # Outcome: UP (1) if close >= open
            outcome = 1 if final_close >= window_open else 0

            # Session from window start hour
            start_dt = datetime.fromtimestamp(window_start / 1000, tz=timezone.utc)
            session = self._get_session(start_dt.hour)

            # Extract features for each minute in the window
            # Track prices and timestamps for velocity calculation
            prices_so_far = []
            times_so_far = []
            velocities_so_far = []

            for i, (idx, row) in enumerate(window_df.iterrows()):
                time_remaining = self.window_minutes - i - 1
                current_price = row["close"]
                current_time = row["open_time"]
                deviation_pct = (current_price - window_open) / window_open

                # Candle phase: 0.0 at open, 1.0 at close
                candle_phase = i / max(1, self.window_minutes - 1)

                # Track for velocity/acceleration
                prices_so_far.append(current_price)
                times_so_far.append(current_time)

                # Calculate velocity (use 5-minute lookback, but adapt to available data)
                velocity = self._calculate_velocity(
                    prices_so_far, times_so_far, lookback_sec=300
                )
                velocities_so_far.append(velocity)

                # Calculate acceleration
                acceleration = self._calculate_acceleration(
                    velocities_so_far, times_so_far, lookback_sec=300
                )

                # Get volatility from pre-computed column
                realized_vol = row["vol"] if pd.notna(row["vol"]) else 0.0

                features = WindowFeatures(
                    window_start=window_start,
                    window_end=window_end,
                    symbol=symbol,
                    window_minutes=self.window_minutes,
                    deviation_pct=deviation_pct,
                    time_remaining=time_remaining,
                    realized_vol=realized_vol,
                    velocity=velocity,
                    acceleration=acceleration,
                    candle_phase=candle_phase,
                    session=session,
                    vol_regime=None,  # Set later after computing percentiles
                    outcome=outcome,
                    final_close=final_close,
                    window_open=window_open,
                    current_price=current_price,
                    high=window_df.iloc[:i+1]["high"].max(),
                    low=window_df.iloc[:i+1]["low"].min(),
                    minute_index=i
                )
                features_list.append(features)

            windows_processed += 1
            window_start += window_end_delta

            if windows_processed % 1000 == 0:
                logger.info(f"Processed {windows_processed} windows")

        logger.info(f"Extracted {len(features_list)} observations from {windows_processed} windows")

        # Convert to DataFrame
        features_df = pd.DataFrame([
            {
                "window_start": f.window_start,
                "window_end": f.window_end,
                "symbol": f.symbol,
                "window_minutes": f.window_minutes,
                "deviation_pct": f.deviation_pct,
                "time_remaining": f.time_remaining,
                "realized_vol": f.realized_vol,
                "velocity": f.velocity,
                "acceleration": f.acceleration,
                "candle_phase": f.candle_phase,
                "session": f.session.value,
                "outcome": f.outcome,
                "final_close": f.final_close,
                "window_open": f.window_open,
                "current_price": f.current_price,
                "high": f.high,
                "low": f.low,
                "minute_index": f.minute_index
            }
            for f in features_list
        ])

        # Compute volatility regimes
        if len(features_df) > 0:
            features_df = self._add_vol_regimes(features_df)

        return features_df

    def _add_vol_regimes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Add volatility regime classification."""
        # Calculate percentiles from non-zero volatilities
        valid_vols = df[df["realized_vol"] > 0]["realized_vol"]
        if len(valid_vols) == 0:
            df["vol_regime"] = VolatilityRegime.MEDIUM.value
            return df

        low_threshold = np.percentile(valid_vols, self.vol_percentiles[0])
        high_threshold = np.percentile(valid_vols, self.vol_percentiles[1])

        def classify_vol(vol):
            if vol <= low_threshold:
                return VolatilityRegime.LOW.value
            elif vol >= high_threshold:
                return VolatilityRegime.HIGH.value
            else:
                return VolatilityRegime.MEDIUM.value

        df["vol_regime"] = df["realized_vol"].apply(classify_vol)

        logger.info(
            f"Volatility thresholds: low<{low_threshold:.6f}, high>{high_threshold:.6f}"
        )

        return df

    def get_window_outcomes(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Get summary of window outcomes only (one row per window).

        Useful for basic win-rate analysis.
        """
        # Take only the first minute of each window
        outcomes = df[df["minute_index"] == 0].copy()
        outcomes["window_return"] = (
            (outcomes["final_close"] - outcomes["window_open"]) /
            outcomes["window_open"]
        )
        return outcomes[["window_start", "symbol", "session", "vol_regime",
                         "window_return", "outcome"]]


def create_training_dataset(
    candle_df: pd.DataFrame,
    symbol: str = "BTCUSDT",
    window_minutes: int = 15
) -> pd.DataFrame:
    """
    Convenience function to create full training dataset from candle data.

    Args:
        candle_df: Raw 1-minute candle data from Binance
        symbol: Symbol name
        window_minutes: Window size (15 or 60)

    Returns:
        DataFrame with all features and outcomes
    """
    extractor = FeatureExtractor(window_minutes=window_minutes)
    return extractor.extract_windows(candle_df, symbol)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    # Test with sample data
    from binance_historical import BinanceHistoricalFetcher

    fetcher = BinanceHistoricalFetcher()
    df = fetcher.get_data("BTCUSDT")

    if df is not None and len(df) > 0:
        extractor = FeatureExtractor(window_minutes=15)
        features_df = extractor.extract_windows(df, "BTCUSDT")

        print(f"\nFeature Dataset Summary:")
        print(f"  Total observations: {len(features_df):,}")
        print(f"  Unique windows: {features_df['window_start'].nunique():,}")
        print(f"\nOutcome distribution:")
        print(features_df['outcome'].value_counts(normalize=True))
        print(f"\nSession distribution:")
        print(features_df['session'].value_counts(normalize=True))
        print(f"\nVolatility regime distribution:")
        print(features_df['vol_regime'].value_counts(normalize=True))
    else:
        print("No data available. Run binance_historical.py first to fetch data.")
