"""
Trading Session Analysis

Analyzes how probability and mean reversion characteristics vary by session:
- Asia (00:00-08:00 UTC): Tokyo/Hong Kong/Singapore
- EU (08:00-13:00 UTC): London
- US (13:00-21:00 UTC): New York
- EU/US Overlap (13:00-17:00 UTC): Highest liquidity period
- Night (21:00-00:00 UTC): Lower activity

Key questions:
1. Does mean reversion strength vary by session?
2. Are extreme moves more common in certain sessions?
3. Should we use different thresholds by session?
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class SessionStats:
    """Statistics for a trading session."""
    session: str
    sample_size: int

    # Win rate statistics
    win_rate: float
    win_rate_ci_low: float
    win_rate_ci_high: float

    # Deviation characteristics
    mean_deviation: float
    std_deviation: float
    mean_abs_deviation: float
    max_abs_deviation: float

    # Directional bias
    pct_up_windows: float  # % of windows that close UP
    deviation_correlation: float

    # Mean reversion metrics
    mean_reversion_strength: float  # How often extreme moves revert
    continuation_strength: float  # How often moves continue


class SessionAnalyzer:
    """
    Analyzes trading session effects on probability surfaces.

    Hypotheses to test:
    1. Asia session may show stronger mean reversion (lower liquidity)
    2. US session may show more momentum continuation (news-driven)
    3. EU/US overlap has best liquidity - tightest prices
    4. Night session may be more random (thin liquidity)

    Usage:
        analyzer = SessionAnalyzer()
        stats = analyzer.analyze(features_df)
    """

    def __init__(
        self,
        min_samples: int = 100,
        extreme_threshold: float = 0.005  # 0.5%
    ):
        self.min_samples = min_samples
        self.extreme_threshold = extreme_threshold

    def _wilson_ci(
        self,
        wins: int,
        n: int,
        confidence: float = 0.95
    ) -> tuple[float, float]:
        """Wilson score confidence interval."""
        if n == 0:
            return (0.0, 1.0)

        z = stats.norm.ppf(1 - (1 - confidence) / 2)
        p_hat = wins / n

        denominator = 1 + z**2 / n
        center = (p_hat + z**2 / (2 * n)) / denominator
        spread = z * np.sqrt((p_hat * (1 - p_hat) + z**2 / (4 * n)) / n) / denominator

        return (max(0.0, center - spread), min(1.0, center + spread))

    def analyze_session(
        self,
        df: pd.DataFrame,
        session: str
    ) -> SessionStats:
        """Analyze a single trading session."""
        session_df = df[df["session"] == session] if session != "all" else df

        if len(session_df) < self.min_samples:
            logger.warning(f"Session {session} has insufficient samples: {len(session_df)}")

        sample_size = len(session_df)
        if sample_size == 0:
            return SessionStats(
                session=session,
                sample_size=0,
                win_rate=0.5,
                win_rate_ci_low=0.0,
                win_rate_ci_high=1.0,
                mean_deviation=0.0,
                std_deviation=0.0,
                mean_abs_deviation=0.0,
                max_abs_deviation=0.0,
                pct_up_windows=0.5,
                deviation_correlation=0.0,
                mean_reversion_strength=0.0,
                continuation_strength=0.0
            )

        # Win rate
        win_rate = session_df["outcome"].mean()
        ci_low, ci_high = self._wilson_ci(
            session_df["outcome"].sum(),
            sample_size
        )

        # Deviation statistics
        mean_deviation = session_df["deviation_pct"].mean()
        std_deviation = session_df["deviation_pct"].std()
        mean_abs_deviation = session_df["deviation_pct"].abs().mean()
        max_abs_deviation = session_df["deviation_pct"].abs().max()

        # Window-level analysis (unique windows only)
        window_df = session_df.drop_duplicates("window_start")
        pct_up_windows = window_df["outcome"].mean() if len(window_df) > 0 else 0.5

        # Deviation correlation with outcome
        deviation_correlation = session_df["deviation_pct"].corr(session_df["outcome"])

        # Mean reversion vs continuation analysis
        # Look at windows with extreme mid-point deviation
        extreme_up = session_df[session_df["deviation_pct"] >= self.extreme_threshold]
        extreme_down = session_df[session_df["deviation_pct"] <= -self.extreme_threshold]

        # Mean reversion: extreme UP that ends DOWN, or extreme DOWN that ends UP
        if len(extreme_up) >= self.min_samples:
            mean_reversion_up = 1 - extreme_up["outcome"].mean()  # % that reversed
        else:
            mean_reversion_up = 0.5

        if len(extreme_down) >= self.min_samples:
            mean_reversion_down = extreme_down["outcome"].mean()  # % that reversed
        else:
            mean_reversion_down = 0.5

        mean_reversion_strength = (mean_reversion_up + mean_reversion_down) / 2

        # Continuation: extreme UP that ends UP, or extreme DOWN that ends DOWN
        continuation_strength = 1 - mean_reversion_strength

        return SessionStats(
            session=session,
            sample_size=sample_size,
            win_rate=win_rate,
            win_rate_ci_low=ci_low,
            win_rate_ci_high=ci_high,
            mean_deviation=mean_deviation,
            std_deviation=std_deviation,
            mean_abs_deviation=mean_abs_deviation,
            max_abs_deviation=max_abs_deviation,
            pct_up_windows=pct_up_windows,
            deviation_correlation=deviation_correlation,
            mean_reversion_strength=mean_reversion_strength,
            continuation_strength=continuation_strength
        )

    def analyze(
        self,
        df: pd.DataFrame
    ) -> dict[str, SessionStats]:
        """Analyze all trading sessions."""
        results = {}

        sessions = ["asia", "eu", "us", "eu_us", "night", "all"]
        for session in sessions:
            stats = self.analyze_session(df, session)
            results[session] = stats

            logger.info(
                f"Session {session}: n={stats.sample_size}, "
                f"win_rate={stats.win_rate:.3f}, "
                f"dev_corr={stats.deviation_correlation:.3f}, "
                f"mean_reversion={stats.mean_reversion_strength:.3f}"
            )

        return results

    def compare_sessions(
        self,
        df: pd.DataFrame,
        time_remaining_filter: Optional[int] = None
    ) -> pd.DataFrame:
        """
        Compare win rates across sessions at different deviation levels.

        Optionally filter to specific time remaining.
        """
        if time_remaining_filter is not None:
            df = df[df["time_remaining"] == time_remaining_filter]

        results = []

        deviation_buckets = [
            ("extreme_down", -float("inf"), -self.extreme_threshold),
            ("moderate_down", -self.extreme_threshold, -0.002),
            ("neutral", -0.002, 0.002),
            ("moderate_up", 0.002, self.extreme_threshold),
            ("extreme_up", self.extreme_threshold, float("inf"))
        ]

        for session in ["asia", "eu", "us", "eu_us", "night"]:
            session_df = df[df["session"] == session]

            for bucket_name, dev_min, dev_max in deviation_buckets:
                bucket_df = session_df[
                    (session_df["deviation_pct"] >= dev_min) &
                    (session_df["deviation_pct"] < dev_max)
                ]

                if len(bucket_df) >= self.min_samples:
                    win_rate = bucket_df["outcome"].mean()
                    ci_low, ci_high = self._wilson_ci(
                        bucket_df["outcome"].sum(),
                        len(bucket_df)
                    )
                else:
                    win_rate = None
                    ci_low = ci_high = None

                results.append({
                    "session": session,
                    "deviation_bucket": bucket_name,
                    "sample_size": len(bucket_df),
                    "win_rate": win_rate,
                    "ci_low": ci_low,
                    "ci_high": ci_high
                })

        return pd.DataFrame(results)

    def hourly_analysis(
        self,
        df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Analyze win rates by hour of day (UTC).

        More granular than session analysis.
        """
        # Extract hour from window_start
        df = df.copy()
        df["hour_utc"] = pd.to_datetime(df["window_start"], unit="ms").dt.hour

        results = []
        for hour in range(24):
            hour_df = df[df["hour_utc"] == hour]

            if len(hour_df) >= self.min_samples:
                win_rate = hour_df["outcome"].mean()
                ci_low, ci_high = self._wilson_ci(
                    hour_df["outcome"].sum(),
                    len(hour_df)
                )
                dev_corr = hour_df["deviation_pct"].corr(hour_df["outcome"])
            else:
                win_rate = None
                ci_low = ci_high = None
                dev_corr = None

            results.append({
                "hour_utc": hour,
                "sample_size": len(hour_df),
                "win_rate": win_rate,
                "ci_low": ci_low,
                "ci_high": ci_high,
                "deviation_correlation": dev_corr
            })

        return pd.DataFrame(results)

    def session_transition_analysis(
        self,
        df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Analyze win rates during session transitions.

        Some windows may span session boundaries - does this affect outcomes?
        """
        # Get unique windows
        window_df = df.drop_duplicates("window_start").copy()

        # Identify windows at session boundaries
        # Asia end (07:00-08:00), EU end (12:00-13:00), US end (20:00-21:00)
        window_df["hour_utc"] = pd.to_datetime(window_df["window_start"], unit="ms").dt.hour

        transition_hours = {
            "asia_to_eu": [7, 8],
            "eu_to_overlap": [12, 13],
            "overlap_to_us": [16, 17],
            "us_to_night": [20, 21],
            "night_to_asia": [23, 0]
        }

        results = []
        for transition_name, hours in transition_hours.items():
            transition_df = window_df[window_df["hour_utc"].isin(hours)]

            if len(transition_df) >= self.min_samples:
                win_rate = transition_df["outcome"].mean()
                ci_low, ci_high = self._wilson_ci(
                    transition_df["outcome"].sum(),
                    len(transition_df)
                )
            else:
                win_rate = None
                ci_low = ci_high = None

            results.append({
                "transition": transition_name,
                "hours": hours,
                "sample_size": len(transition_df),
                "win_rate": win_rate,
                "ci_low": ci_low,
                "ci_high": ci_high
            })

        return pd.DataFrame(results)


def generate_session_report(
    df: pd.DataFrame,
    output_path: Optional[str] = None
) -> str:
    """Generate a formatted session analysis report."""
    analyzer = SessionAnalyzer()

    # Run analyses
    session_stats = analyzer.analyze(df)
    comparison = analyzer.compare_sessions(df)
    hourly = analyzer.hourly_analysis(df)

    # Format report
    lines = []
    lines.append("=" * 60)
    lines.append("TRADING SESSION ANALYSIS REPORT")
    lines.append("=" * 60)
    lines.append("")

    lines.append("1. SESSION SUMMARY")
    lines.append("-" * 40)
    for session, stats in session_stats.items():
        if session == "all":
            continue
        lines.append(f"\n{session.upper()} Session:")
        lines.append(f"  Samples: {stats.sample_size:,}")
        lines.append(f"  Win Rate: {stats.win_rate:.1%} [{stats.win_rate_ci_low:.1%}, {stats.win_rate_ci_high:.1%}]")
        lines.append(f"  Deviation Correlation: {stats.deviation_correlation:.3f}")
        lines.append(f"  Mean Reversion: {stats.mean_reversion_strength:.1%}")
        lines.append(f"  Continuation: {stats.continuation_strength:.1%}")

    lines.append("")
    lines.append("2. WIN RATES BY SESSION AND DEVIATION")
    lines.append("-" * 40)
    pivot = comparison.pivot(index="deviation_bucket", columns="session", values="win_rate")
    lines.append(pivot.to_string())

    lines.append("")
    lines.append("3. HOURLY WIN RATES")
    lines.append("-" * 40)
    valid_hourly = hourly[hourly["win_rate"].notna()][["hour_utc", "win_rate", "sample_size"]]
    lines.append(valid_hourly.to_string(index=False))

    lines.append("")
    lines.append("4. KEY FINDINGS")
    lines.append("-" * 40)

    # Find session with highest mean reversion
    max_mr_session = max(
        [(s, st.mean_reversion_strength) for s, st in session_stats.items() if s != "all"],
        key=lambda x: x[1]
    )
    lines.append(f"  - Strongest mean reversion: {max_mr_session[0]} ({max_mr_session[1]:.1%})")

    # Find session with highest deviation correlation
    max_corr_session = max(
        [(s, st.deviation_correlation) for s, st in session_stats.items() if s != "all"],
        key=lambda x: x[1]
    )
    lines.append(f"  - Most predictive by deviation: {max_corr_session[0]} (r={max_corr_session[1]:.3f})")

    # Find best hour
    best_hour = hourly.loc[hourly["win_rate"].idxmax()] if hourly["win_rate"].notna().any() else None
    if best_hour is not None:
        lines.append(f"  - Best hour (UTC): {int(best_hour['hour_utc']):02d}:00 ({best_hour['win_rate']:.1%} win rate)")

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

    print("SessionAnalyzer module loaded successfully")
