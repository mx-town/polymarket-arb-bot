"""
Probability Surface Model

Computes empirical P(UP) indexed by:
- deviation_pct: Current price deviation from window open
- time_remaining: Minutes until window close
- vol_regime: Low / Medium / High volatility
- session: Trading session (Asia, Europe, US_EU_Overlap, US, Late_US)

Includes confidence intervals and sample size requirements.

Bucket dimensions (per testing_plan):
- Deviation: 0.05% increments from -2% to +2% (80 buckets)
- Time remaining: 30-second increments for 15min = 30 buckets (or 1-min = 15 buckets)
- Volatility: terciles (3 buckets) + "all"
- Session: 5 categories + "all"

Total theoretical buckets: 80 × 30 × 4 × 6 = 57,600 (with "all" fallbacks)
"""

import json
import logging
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)

# Minimum samples for reliable estimates
MIN_SAMPLES_RELIABLE = 30
MIN_SAMPLES_USABLE = 10

# Session categories aligned with feature_extractor
SESSIONS = ["asia", "europe", "us_eu_overlap", "us", "late_us", "all"]
VOL_REGIMES = ["low", "medium", "high", "all"]


@dataclass
class ProbabilityBucket:
    """Statistics for a single bucket in the probability surface."""
    # Bucket definition
    deviation_min: float
    deviation_max: float
    time_remaining: int
    vol_regime: str  # "low", "medium", "high", or "all"
    session: str     # "asia", "europe", "us_eu_overlap", "us", "late_us", or "all"

    # Statistics
    sample_size: int
    win_count: int
    win_rate: float

    # Confidence intervals (Wilson score)
    ci_lower: float
    ci_upper: float
    ci_width: float

    # Reliability flags
    is_reliable: bool   # sample_size >= 30
    is_usable: bool     # sample_size >= 10


@dataclass
class ProbabilityQuery:
    """Query parameters for probability lookup."""
    deviation_pct: float
    time_remaining: int
    vol_regime: Optional[str] = None  # None = use "all"
    session: Optional[str] = None     # None = use "all"


class ProbabilitySurface:
    """
    Empirical probability surface for P(UP | deviation, time_remaining, volatility, session).

    The surface is built by bucketing observations and computing win rates.
    Uses Wilson score intervals for confidence bounds.

    Bucket sizes:
    - Deviation: 0.1% bands (-2% to +2%)
    - Time remaining: 1-minute bands
    - Volatility: Low / Medium / High terciles + "all"
    - Session: 5 sessions + "all"

    Usage:
        surface = ProbabilitySurface()
        surface.fit(features_df)
        prob, ci_lower, ci_upper, reliable = surface.get_probability(
            deviation_pct=0.002,
            time_remaining=10,
            vol_regime="medium",
            session="us_eu_overlap"
        )
    """

    def __init__(
        self,
        deviation_step: float = 0.001,  # 0.1% buckets
        deviation_range: tuple[float, float] = (-0.02, 0.02),  # -2% to +2%
        confidence_level: float = 0.95
    ):
        """
        Args:
            deviation_step: Bucket width for deviation (0.001 = 0.1%)
            deviation_range: Min/max deviation to track
            confidence_level: Confidence level for intervals
        """
        self.deviation_step = deviation_step
        self.deviation_range = deviation_range
        self.confidence_level = confidence_level

        # Computed attributes
        self.buckets: dict[tuple, ProbabilityBucket] = {}
        self.deviation_bins: list[float] = []
        self.time_bins: list[int] = []
        self.vol_regimes: list[str] = VOL_REGIMES
        self.sessions: list[str] = SESSIONS

        self._fitted = False

    def _wilson_score_interval(
        self,
        wins: int,
        n: int,
        confidence: float = 0.95
    ) -> tuple[float, float]:
        """
        Calculate Wilson score confidence interval for proportion.

        More accurate than normal approximation for small samples.
        """
        if n == 0:
            return (0.0, 1.0)

        z = stats.norm.ppf(1 - (1 - confidence) / 2)
        p_hat = wins / n

        denominator = 1 + z**2 / n
        center = (p_hat + z**2 / (2 * n)) / denominator
        spread = z * np.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n)) / n) / denominator

        lower = max(0.0, center - spread)
        upper = min(1.0, center + spread)

        return (lower, upper)

    def _round_bucket(self, value: float) -> float:
        """Round bucket boundary to avoid floating point precision issues."""
        return round(value, 10)

    def _get_deviation_bucket(self, deviation: float) -> tuple[float, float]:
        """Get bucket boundaries for a deviation value."""
        if deviation < self.deviation_range[0]:
            return (float("-inf"), self._round_bucket(self.deviation_range[0]))
        if deviation >= self.deviation_range[1]:
            return (self._round_bucket(self.deviation_range[1]), float("inf"))

        bucket_idx = int((deviation - self.deviation_range[0]) / self.deviation_step)
        bucket_min = self._round_bucket(self.deviation_range[0] + bucket_idx * self.deviation_step)
        bucket_max = self._round_bucket(bucket_min + self.deviation_step)

        return (bucket_min, bucket_max)

    def _create_bucket(
        self,
        df: pd.DataFrame,
        dev_min: float,
        dev_max: float,
        time_remaining: int,
        vol_regime: str,
        session: str
    ) -> ProbabilityBucket:
        """Create a probability bucket from filtered data."""
        sample_size = len(df)
        win_count = int(df["outcome"].sum()) if sample_size > 0 else 0
        win_rate = win_count / sample_size if sample_size > 0 else 0.5

        ci_lower, ci_upper = self._wilson_score_interval(
            win_count, sample_size, self.confidence_level
        )

        return ProbabilityBucket(
            deviation_min=dev_min,
            deviation_max=dev_max,
            time_remaining=time_remaining,
            vol_regime=vol_regime,
            session=session,
            sample_size=sample_size,
            win_count=win_count,
            win_rate=win_rate,
            ci_lower=ci_lower,
            ci_upper=ci_upper,
            ci_width=ci_upper - ci_lower,
            is_reliable=sample_size >= MIN_SAMPLES_RELIABLE,
            is_usable=sample_size >= MIN_SAMPLES_USABLE
        )

    def fit(self, df: pd.DataFrame) -> "ProbabilitySurface":
        """
        Fit the probability surface from feature data.

        Args:
            df: Feature DataFrame from FeatureExtractor with columns:
                - deviation_pct
                - time_remaining
                - vol_regime
                - session
                - outcome (0 or 1)
        """
        required_cols = ["deviation_pct", "time_remaining", "vol_regime", "session", "outcome"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"Missing required column: {col}")

        logger.info(f"Fitting probability surface on {len(df):,} observations")

        # Create deviation bins
        self.deviation_bins = np.arange(
            self.deviation_range[0],
            self.deviation_range[1] + self.deviation_step,
            self.deviation_step
        ).tolist()

        # Get unique time values
        self.time_bins = sorted(df["time_remaining"].unique().tolist())

        # Bucket all observations
        self.buckets = {}
        total_buckets = 0

        # Process each combination
        for session in self.sessions:
            for vol_regime in self.vol_regimes:
                for time_remaining in self.time_bins:
                    # Filter by time
                    time_mask = df["time_remaining"] == time_remaining

                    # Filter by volatility
                    if vol_regime == "all":
                        vol_mask = pd.Series(True, index=df.index)
                    else:
                        vol_mask = df["vol_regime"] == vol_regime

                    # Filter by session
                    if session == "all":
                        session_mask = pd.Series(True, index=df.index)
                    else:
                        session_mask = df["session"] == session

                    base_df = df[time_mask & vol_mask & session_mask]

                    # Bucket by deviation
                    for i, dev_min in enumerate(self.deviation_bins[:-1]):
                        dev_max = self.deviation_bins[i + 1]
                        dev_min_key = self._round_bucket(dev_min)
                        dev_max_key = self._round_bucket(dev_max)

                        # Get observations in this bucket
                        dev_mask = (base_df["deviation_pct"] >= dev_min) & \
                                   (base_df["deviation_pct"] < dev_max)
                        bucket_df = base_df[dev_mask]

                        bucket = self._create_bucket(
                            bucket_df, dev_min_key, dev_max_key,
                            time_remaining, vol_regime, session
                        )

                        key = (dev_min_key, dev_max_key, time_remaining, vol_regime, session)
                        self.buckets[key] = bucket
                        total_buckets += 1

        # Add extreme buckets
        self._add_extreme_buckets(df)

        self._fitted = True
        logger.info(f"Created {len(self.buckets):,} probability buckets")

        return self

    def _add_extreme_buckets(self, df: pd.DataFrame):
        """Add buckets for extreme deviations outside the main range."""
        for session in self.sessions:
            for vol_regime in self.vol_regimes:
                for time_remaining in self.time_bins:
                    time_mask = df["time_remaining"] == time_remaining

                    if vol_regime == "all":
                        vol_mask = pd.Series(True, index=df.index)
                    else:
                        vol_mask = df["vol_regime"] == vol_regime

                    if session == "all":
                        session_mask = pd.Series(True, index=df.index)
                    else:
                        session_mask = df["session"] == session

                    base_df = df[time_mask & vol_mask & session_mask]

                    # Lower extreme
                    lower_mask = base_df["deviation_pct"] < self.deviation_range[0]
                    lower_df = base_df[lower_mask]
                    if len(lower_df) > 0:
                        dev_max_key = self._round_bucket(self.deviation_range[0])
                        bucket = self._create_bucket(
                            lower_df, float("-inf"), dev_max_key,
                            time_remaining, vol_regime, session
                        )
                        key = (float("-inf"), dev_max_key, time_remaining, vol_regime, session)
                        self.buckets[key] = bucket

                    # Upper extreme
                    upper_mask = base_df["deviation_pct"] >= self.deviation_range[1]
                    upper_df = base_df[upper_mask]
                    if len(upper_df) > 0:
                        dev_min_key = self._round_bucket(self.deviation_range[1])
                        bucket = self._create_bucket(
                            upper_df, dev_min_key, float("inf"),
                            time_remaining, vol_regime, session
                        )
                        key = (dev_min_key, float("inf"), time_remaining, vol_regime, session)
                        self.buckets[key] = bucket

    def get_probability(
        self,
        deviation_pct: float,
        time_remaining: int,
        vol_regime: Optional[str] = None,
        session: Optional[str] = None
    ) -> tuple[float, float, float, bool]:
        """
        Look up probability of UP outcome.

        Args:
            deviation_pct: Current deviation from window open
            time_remaining: Minutes until window close
            vol_regime: Volatility regime (None = use "all")
            session: Trading session (None = use "all")

        Returns:
            Tuple of (win_rate, ci_lower, ci_upper, is_reliable)
        """
        if not self._fitted:
            raise RuntimeError("Surface not fitted. Call fit() first.")

        if vol_regime is None:
            vol_regime = "all"
        if session is None:
            session = "all"

        # Find the right deviation bucket
        dev_min, dev_max = self._get_deviation_bucket(deviation_pct)

        # Clamp time_remaining to available bins
        if time_remaining not in self.time_bins:
            time_remaining = min(self.time_bins, key=lambda t: abs(t - time_remaining))

        key = (dev_min, dev_max, time_remaining, vol_regime, session)

        if key in self.buckets:
            bucket = self.buckets[key]
            return (bucket.win_rate, bucket.ci_lower, bucket.ci_upper, bucket.is_reliable)

        # Fallback hierarchy: specific session -> "all" session -> specific vol -> "all" vol
        if session != "all":
            return self.get_probability(deviation_pct, time_remaining, vol_regime, "all")
        if vol_regime != "all":
            return self.get_probability(deviation_pct, time_remaining, "all", "all")

        # Default prior
        return (0.5, 0.0, 1.0, False)

    def get_bucket(
        self,
        deviation_pct: float,
        time_remaining: int,
        vol_regime: Optional[str] = None,
        session: Optional[str] = None
    ) -> Optional[ProbabilityBucket]:
        """Get the full bucket object for inspection."""
        if not self._fitted:
            raise RuntimeError("Surface not fitted. Call fit() first.")

        if vol_regime is None:
            vol_regime = "all"
        if session is None:
            session = "all"

        dev_min, dev_max = self._get_deviation_bucket(deviation_pct)

        if time_remaining not in self.time_bins:
            time_remaining = min(self.time_bins, key=lambda t: abs(t - time_remaining))

        key = (dev_min, dev_max, time_remaining, vol_regime, session)
        return self.buckets.get(key)

    def to_dataframe(self) -> pd.DataFrame:
        """Export surface as DataFrame for analysis."""
        if not self._fitted:
            raise RuntimeError("Surface not fitted. Call fit() first.")

        rows = []
        for key, bucket in self.buckets.items():
            rows.append(asdict(bucket))

        return pd.DataFrame(rows)

    def save(self, path: str):
        """Save surface to JSON file."""
        if not self._fitted:
            raise RuntimeError("Surface not fitted. Call fit() first.")

        data = {
            "config": {
                "deviation_step": self.deviation_step,
                "deviation_range": self.deviation_range,
                "confidence_level": self.confidence_level
            },
            "deviation_bins": self.deviation_bins,
            "time_bins": self.time_bins,
            "vol_regimes": self.vol_regimes,
            "sessions": self.sessions,
            "buckets": {
                f"{k[0]}|{k[1]}|{k[2]}|{k[3]}|{k[4]}": asdict(v)
                for k, v in self.buckets.items()
            }
        }

        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(f"Saved probability surface to {path}")

    @classmethod
    def load(cls, path: str) -> "ProbabilitySurface":
        """Load surface from JSON file."""
        with open(path) as f:
            data = json.load(f)

        surface = cls(
            deviation_step=data["config"]["deviation_step"],
            deviation_range=tuple(data["config"]["deviation_range"]),
            confidence_level=data["config"]["confidence_level"]
        )

        surface.deviation_bins = data["deviation_bins"]
        surface.time_bins = data["time_bins"]
        surface.vol_regimes = data.get("vol_regimes", VOL_REGIMES)
        surface.sessions = data.get("sessions", SESSIONS)

        surface.buckets = {}
        for key_str, bucket_dict in data["buckets"].items():
            parts = key_str.split("|")
            # Handle both old format (4 parts) and new format (5 parts)
            if len(parts) == 4:
                # Old format without session
                key = (
                    float(parts[0]) if parts[0] != "-inf" else float("-inf"),
                    float(parts[1]) if parts[1] != "inf" else float("inf"),
                    int(parts[2]),
                    parts[3],
                    "all"  # Default session
                )
                bucket_dict["session"] = "all"
            else:
                key = (
                    float(parts[0]) if parts[0] != "-inf" else float("-inf"),
                    float(parts[1]) if parts[1] != "inf" else float("inf"),
                    int(parts[2]),
                    parts[3],
                    parts[4]
                )
            surface.buckets[key] = ProbabilityBucket(**bucket_dict)

        surface._fitted = True
        logger.info(f"Loaded probability surface from {path}")

        return surface

    def summary_stats(self) -> dict:
        """Get summary statistics of the surface."""
        if not self._fitted:
            raise RuntimeError("Surface not fitted. Call fit() first.")

        df = self.to_dataframe()

        # Filter to "all" regime/session for aggregate stats
        all_filter = (df["vol_regime"] == "all") & (df["session"] == "all")
        all_df = df[all_filter]

        return {
            "total_buckets": len(self.buckets),
            "reliable_buckets": int(df["is_reliable"].sum()),
            "usable_buckets": int(df["is_usable"].sum()),
            "mean_sample_size": float(df["sample_size"].mean()),
            "median_sample_size": float(df["sample_size"].median()),
            "mean_win_rate": float(all_df["win_rate"].mean()) if len(all_df) > 0 else 0.5,
            "mean_ci_width": float(all_df["ci_width"].mean()) if len(all_df) > 0 else 1.0,
            "deviation_range": self.deviation_range,
            "time_bins": len(self.time_bins),
            "vol_regimes": self.vol_regimes,
            "sessions": self.sessions
        }


def analyze_probability_by_deviation(
    surface: ProbabilitySurface,
    time_remaining: int = 7,
    session: str = "all"
) -> pd.DataFrame:
    """
    Analyze how probability varies with deviation at a fixed time.

    Useful for visualizing the "tilt" in probability as price moves.
    """
    df = surface.to_dataframe()

    # Filter to specific time, "all" vol regime, and specified session
    filtered = df[
        (df["time_remaining"] == time_remaining) &
        (df["vol_regime"] == "all") &
        (df["session"] == session) &
        (df["deviation_min"] > -0.02) &
        (df["deviation_max"] < 0.02)
    ].copy()

    filtered["deviation_mid"] = (filtered["deviation_min"] + filtered["deviation_max"]) / 2
    filtered = filtered.sort_values("deviation_mid")

    return filtered[["deviation_mid", "win_rate", "ci_lower", "ci_upper",
                     "sample_size", "is_reliable"]]


def analyze_probability_by_time(
    surface: ProbabilitySurface,
    deviation_pct: float = 0.005,
    session: str = "all"
) -> pd.DataFrame:
    """
    Analyze how probability varies with time at a fixed deviation.

    Useful for visualizing how certainty increases as window closes.
    """
    results = []

    for time_remaining in surface.time_bins:
        prob, ci_lower, ci_upper, reliable = surface.get_probability(
            deviation_pct=deviation_pct,
            time_remaining=time_remaining,
            vol_regime="all",
            session=session
        )
        bucket = surface.get_bucket(deviation_pct, time_remaining, "all", session)

        results.append({
            "time_remaining": time_remaining,
            "win_rate": prob,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "sample_size": bucket.sample_size if bucket else 0,
            "is_reliable": reliable
        })

    return pd.DataFrame(results).sort_values("time_remaining", ascending=False)


def analyze_probability_by_session(
    surface: ProbabilitySurface,
    deviation_pct: float = 0.005,
    time_remaining: int = 7
) -> pd.DataFrame:
    """
    Analyze how probability varies by trading session.

    Useful for identifying session-specific patterns.
    """
    results = []

    for session in surface.sessions:
        if session == "all":
            continue

        prob, ci_lower, ci_upper, reliable = surface.get_probability(
            deviation_pct=deviation_pct,
            time_remaining=time_remaining,
            vol_regime="all",
            session=session
        )
        bucket = surface.get_bucket(deviation_pct, time_remaining, "all", session)

        results.append({
            "session": session,
            "win_rate": prob,
            "ci_lower": ci_lower,
            "ci_upper": ci_upper,
            "sample_size": bucket.sample_size if bucket else 0,
            "is_reliable": reliable
        })

    return pd.DataFrame(results)


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s"
    )

    print("ProbabilitySurface module loaded successfully")
    print("Use with FeatureExtractor output to build probability model")
    print(f"Sessions: {SESSIONS}")
    print(f"Volatility regimes: {VOL_REGIMES}")
