"""
Repricing Lag Analysis

Measures how long after a price move Polymarket reprices:
- Distribution of lag times (median, 90th percentile)
- Lag variation by move size
- Lag variation by time of day
- Detection of repricing patterns

Note: This module requires Polymarket historical price data which may need
to be collected separately or approximated from current bot observations.
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class LagDistribution:
    """Statistics about repricing lag distribution."""
    sample_size: int

    # Central tendency
    mean_lag_ms: float
    median_lag_ms: float
    mode_lag_ms: float

    # Percentiles
    p50_lag_ms: float
    p75_lag_ms: float
    p90_lag_ms: float
    p95_lag_ms: float
    p99_lag_ms: float

    # Spread
    std_lag_ms: float
    iqr_lag_ms: float
    min_lag_ms: float
    max_lag_ms: float


@dataclass
class LagEvent:
    """A single repricing lag observation."""
    timestamp: int  # When price move occurred (Binance)
    symbol: str
    move_size_pct: float  # Size of the price move
    move_direction: str  # "up" or "down"

    # Polymarket response
    polymarket_lag_ms: float  # Time until Polymarket repriced
    polymarket_move_pct: float  # How much Polymarket moved

    # Context
    time_remaining_sec: int  # Seconds until window close
    session: str


class LagAnalyzer:
    """
    Analyzes repricing lag between spot markets and Polymarket.

    The lag is critical for:
    1. Timing entries in lag arbitrage strategy
    2. Setting max_lag_window_ms configuration
    3. Understanding when edge exists vs is priced in

    Usage:
        analyzer = LagAnalyzer()

        # Method 1: Analyze from collected lag events
        dist = analyzer.analyze_lag_distribution(lag_events_df)

        # Method 2: Estimate from features (synthetic)
        estimated_lag = analyzer.estimate_lag_from_features(
            move_size=0.005,
            time_remaining=300,
            session="us"
        )
    """

    def __init__(
        self,
        min_move_threshold: float = 0.001,  # 0.1% minimum move
        max_lag_threshold_ms: int = 30000,  # Cap at 30 seconds
    ):
        self.min_move_threshold = min_move_threshold
        self.max_lag_threshold = max_lag_threshold_ms

    def analyze_lag_distribution(
        self,
        df: pd.DataFrame
    ) -> LagDistribution:
        """
        Analyze distribution of lag times from collected data.

        Args:
            df: DataFrame with columns:
                - polymarket_lag_ms: Observed lag in milliseconds

        Returns:
            LagDistribution with full statistics
        """
        if len(df) == 0 or "polymarket_lag_ms" not in df.columns:
            return LagDistribution(
                sample_size=0,
                mean_lag_ms=2000,  # Default estimate
                median_lag_ms=2000,
                mode_lag_ms=2000,
                p50_lag_ms=2000,
                p75_lag_ms=3000,
                p90_lag_ms=5000,
                p95_lag_ms=7000,
                p99_lag_ms=10000,
                std_lag_ms=1500,
                iqr_lag_ms=2000,
                min_lag_ms=500,
                max_lag_ms=10000
            )

        # Filter valid lags
        lags = df["polymarket_lag_ms"].dropna()
        lags = lags[(lags > 0) & (lags <= self.max_lag_threshold)]

        if len(lags) == 0:
            return self._default_distribution()

        # Calculate statistics
        percentiles = np.percentile(lags, [50, 75, 90, 95, 99])

        # Mode (most common lag bucket)
        lag_bins = pd.cut(lags, bins=20)
        mode_bin = lag_bins.value_counts().idxmax()
        mode_lag = (mode_bin.left + mode_bin.right) / 2

        return LagDistribution(
            sample_size=len(lags),
            mean_lag_ms=lags.mean(),
            median_lag_ms=lags.median(),
            mode_lag_ms=mode_lag,
            p50_lag_ms=percentiles[0],
            p75_lag_ms=percentiles[1],
            p90_lag_ms=percentiles[2],
            p95_lag_ms=percentiles[3],
            p99_lag_ms=percentiles[4],
            std_lag_ms=lags.std(),
            iqr_lag_ms=percentiles[1] - percentiles[0],
            min_lag_ms=lags.min(),
            max_lag_ms=lags.max()
        )

    def _default_distribution(self) -> LagDistribution:
        """Return default lag distribution when no data available."""
        return LagDistribution(
            sample_size=0,
            mean_lag_ms=2000,
            median_lag_ms=2000,
            mode_lag_ms=2000,
            p50_lag_ms=2000,
            p75_lag_ms=3000,
            p90_lag_ms=5000,
            p95_lag_ms=7000,
            p99_lag_ms=10000,
            std_lag_ms=1500,
            iqr_lag_ms=2000,
            min_lag_ms=500,
            max_lag_ms=10000
        )

    def analyze_lag_by_move_size(
        self,
        df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Analyze how lag varies with move size.

        Hypothesis: Larger moves may be repriced faster (more obvious signal)
        or slower (market makers hesitate).
        """
        if "move_size_pct" not in df.columns or "polymarket_lag_ms" not in df.columns:
            return pd.DataFrame()

        df = df.copy()
        df["abs_move"] = df["move_size_pct"].abs()

        # Bin by move size
        move_bins = [0, 0.001, 0.002, 0.003, 0.005, 0.01, float("inf")]
        move_labels = ["<0.1%", "0.1-0.2%", "0.2-0.3%", "0.3-0.5%", "0.5-1%", ">1%"]

        df["move_bin"] = pd.cut(df["abs_move"], bins=move_bins, labels=move_labels)

        results = df.groupby("move_bin").agg({
            "polymarket_lag_ms": ["mean", "median", "std", "count"]
        }).round(0)

        results.columns = ["mean_lag", "median_lag", "std_lag", "count"]

        return results.reset_index()

    def analyze_lag_by_session(
        self,
        df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Analyze how lag varies by trading session.

        Hypothesis: Lower liquidity sessions may have longer lags.
        """
        if "session" not in df.columns or "polymarket_lag_ms" not in df.columns:
            return pd.DataFrame()

        results = df.groupby("session").agg({
            "polymarket_lag_ms": ["mean", "median", "std", "count"]
        }).round(0)

        results.columns = ["mean_lag", "median_lag", "std_lag", "count"]

        return results.reset_index()

    def analyze_lag_by_time_remaining(
        self,
        df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Analyze how lag varies with time until window close.

        Hypothesis: Markets may reprice faster as expiry approaches.
        """
        if "time_remaining_sec" not in df.columns or "polymarket_lag_ms" not in df.columns:
            return pd.DataFrame()

        df = df.copy()

        # Bin by time remaining
        time_bins = [0, 60, 120, 300, 600, 900, float("inf")]
        time_labels = ["<1m", "1-2m", "2-5m", "5-10m", "10-15m", ">15m"]

        df["time_bin"] = pd.cut(df["time_remaining_sec"], bins=time_bins, labels=time_labels)

        results = df.groupby("time_bin").agg({
            "polymarket_lag_ms": ["mean", "median", "std", "count"]
        }).round(0)

        results.columns = ["mean_lag", "median_lag", "std_lag", "count"]

        return results.reset_index()

    def estimate_lag_from_features(
        self,
        move_size: float,
        time_remaining: int,
        session: str,
        historical_dist: Optional[LagDistribution] = None
    ) -> dict:
        """
        Estimate expected lag based on features.

        This is a simple model that can be refined with more data.
        Returns estimated lag range.
        """
        if historical_dist is None:
            historical_dist = self._default_distribution()

        # Base estimate from historical median
        base_lag = historical_dist.median_lag_ms

        # Adjustments (these are rough estimates - refine with data)

        # Larger moves may be repriced faster
        move_factor = 1.0
        if abs(move_size) > 0.005:
            move_factor = 0.8  # 20% faster
        elif abs(move_size) < 0.002:
            move_factor = 1.2  # 20% slower

        # Near expiry may be faster
        time_factor = 1.0
        if time_remaining < 60:
            time_factor = 0.7  # 30% faster
        elif time_remaining < 120:
            time_factor = 0.85  # 15% faster

        # Session effects (rough estimates)
        session_factors = {
            "asia": 1.2,    # Slower (less liquidity)
            "eu": 1.0,
            "us": 0.9,      # Faster (high liquidity)
            "eu_us": 0.85,  # Fastest (overlap)
            "night": 1.3    # Slowest
        }
        session_factor = session_factors.get(session, 1.0)

        estimated_lag = base_lag * move_factor * time_factor * session_factor

        return {
            "estimated_lag_ms": estimated_lag,
            "min_lag_ms": estimated_lag * 0.5,
            "max_lag_ms": estimated_lag * 2.0,
            "confidence": "low" if historical_dist.sample_size < 100 else "medium"
        }

    def optimal_lag_window(
        self,
        historical_dist: Optional[LagDistribution] = None,
        target_capture_rate: float = 0.90
    ) -> int:
        """
        Determine optimal max_lag_window_ms configuration.

        Args:
            historical_dist: Historical lag distribution
            target_capture_rate: What % of repricing events to capture (0.90 = 90%)

        Returns:
            Recommended max_lag_window_ms value
        """
        if historical_dist is None:
            historical_dist = self._default_distribution()

        # Use the appropriate percentile
        if target_capture_rate >= 0.99:
            return int(historical_dist.p99_lag_ms)
        elif target_capture_rate >= 0.95:
            return int(historical_dist.p95_lag_ms)
        elif target_capture_rate >= 0.90:
            return int(historical_dist.p90_lag_ms)
        elif target_capture_rate >= 0.75:
            return int(historical_dist.p75_lag_ms)
        else:
            return int(historical_dist.median_lag_ms)


class LagDataCollector:
    """
    Utility for collecting lag observations from live trading.

    Integrates with the bot to record lag events for analysis.
    """

    def __init__(self, output_path: str = "research/data/lag_events.parquet"):
        self.output_path = output_path
        self.events: list[dict] = []

    def record_event(
        self,
        binance_timestamp: int,
        binance_price: float,
        binance_prev_price: float,
        polymarket_timestamp: int,
        polymarket_price_up: float,
        polymarket_prev_price_up: float,
        time_remaining_sec: int,
        session: str,
        symbol: str = "BTCUSDT"
    ):
        """Record a lag observation."""
        move_size = (binance_price - binance_prev_price) / binance_prev_price
        move_direction = "up" if move_size > 0 else "down"

        polymarket_move = polymarket_price_up - polymarket_prev_price_up
        lag_ms = polymarket_timestamp - binance_timestamp

        event = {
            "timestamp": binance_timestamp,
            "symbol": symbol,
            "move_size_pct": move_size,
            "move_direction": move_direction,
            "polymarket_lag_ms": lag_ms,
            "polymarket_move_pct": polymarket_move,
            "time_remaining_sec": time_remaining_sec,
            "session": session
        }

        self.events.append(event)

    def save(self):
        """Save collected events to parquet."""
        if len(self.events) == 0:
            logger.warning("No lag events to save")
            return

        df = pd.DataFrame(self.events)
        df.to_parquet(self.output_path, index=False)
        logger.info(f"Saved {len(self.events)} lag events to {self.output_path}")

    def load(self) -> pd.DataFrame:
        """Load previously collected events."""
        try:
            return pd.read_parquet(self.output_path)
        except FileNotFoundError:
            logger.warning(f"No lag data found at {self.output_path}")
            return pd.DataFrame()


def generate_lag_report(
    df: pd.DataFrame,
    output_path: Optional[str] = None
) -> str:
    """Generate a formatted lag analysis report."""
    analyzer = LagAnalyzer()

    # Run analyses
    distribution = analyzer.analyze_lag_distribution(df)
    by_move = analyzer.analyze_lag_by_move_size(df)
    by_session = analyzer.analyze_lag_by_session(df)
    by_time = analyzer.analyze_lag_by_time_remaining(df)

    optimal_window = analyzer.optimal_lag_window(distribution)

    # Format report
    lines = []
    lines.append("=" * 60)
    lines.append("REPRICING LAG ANALYSIS REPORT")
    lines.append("=" * 60)
    lines.append("")

    lines.append("1. OVERALL LAG DISTRIBUTION")
    lines.append("-" * 40)
    lines.append(f"  Sample Size: {distribution.sample_size:,}")
    lines.append(f"  Mean Lag: {distribution.mean_lag_ms:.0f} ms")
    lines.append(f"  Median Lag: {distribution.median_lag_ms:.0f} ms")
    lines.append(f"  Mode Lag: {distribution.mode_lag_ms:.0f} ms")
    lines.append(f"  Std Dev: {distribution.std_lag_ms:.0f} ms")
    lines.append("")
    lines.append("  Percentiles:")
    lines.append(f"    50th: {distribution.p50_lag_ms:.0f} ms")
    lines.append(f"    75th: {distribution.p75_lag_ms:.0f} ms")
    lines.append(f"    90th: {distribution.p90_lag_ms:.0f} ms")
    lines.append(f"    95th: {distribution.p95_lag_ms:.0f} ms")
    lines.append(f"    99th: {distribution.p99_lag_ms:.0f} ms")

    if len(by_move) > 0:
        lines.append("")
        lines.append("2. LAG BY MOVE SIZE")
        lines.append("-" * 40)
        lines.append(by_move.to_string(index=False))

    if len(by_session) > 0:
        lines.append("")
        lines.append("3. LAG BY SESSION")
        lines.append("-" * 40)
        lines.append(by_session.to_string(index=False))

    if len(by_time) > 0:
        lines.append("")
        lines.append("4. LAG BY TIME REMAINING")
        lines.append("-" * 40)
        lines.append(by_time.to_string(index=False))

    lines.append("")
    lines.append("5. RECOMMENDATIONS")
    lines.append("-" * 40)
    lines.append(f"  Optimal max_lag_window_ms (90% capture): {optimal_window} ms")
    lines.append(f"  Conservative setting (95% capture): {analyzer.optimal_lag_window(distribution, 0.95)} ms")
    lines.append(f"  Aggressive setting (75% capture): {analyzer.optimal_lag_window(distribution, 0.75)} ms")

    report = "\n".join(lines)

    if output_path:
        with open(output_path, "w") as f:
            f.write(report)
        logger.info(f"Report saved to {output_path}")

    return report


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    print("LagAnalyzer module loaded successfully")
    print("\nDefault lag distribution (no data):")
    analyzer = LagAnalyzer()
    dist = analyzer._default_distribution()
    print(f"  Median: {dist.median_lag_ms} ms")
    print(f"  90th percentile: {dist.p90_lag_ms} ms")
