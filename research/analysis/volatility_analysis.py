"""
Volatility Regime Analysis

Analyzes how probability surfaces change across volatility regimes:
- Does the surface flatten in high-vol regimes?
- Are extreme deviations less predictive when volatility is high?
- Does the "momentum continuation" effect vary with volatility?
"""

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd
from scipy import stats

logger = logging.getLogger(__name__)


@dataclass
class VolatilityRegimeStats:
    """Statistics for a single volatility regime."""
    regime: str  # "low", "medium", "high"
    sample_size: int
    win_rate: float
    win_rate_std: float

    # Deviation sensitivity
    deviation_correlation: float  # Correlation between deviation and outcome
    mean_abs_deviation: float

    # Probability surface characteristics
    surface_slope: float  # How much win rate changes per 1% deviation
    surface_flatness: float  # Variance of win rates across buckets

    # Statistical significance
    chi_square_stat: float
    chi_square_p_value: float


class VolatilityAnalyzer:
    """
    Analyzes the impact of volatility on probability surfaces.

    Key questions:
    1. Does high volatility reduce predictability?
    2. Should we use different thresholds in different regimes?
    3. Does momentum continuation work better in low/high vol?

    Usage:
        analyzer = VolatilityAnalyzer()
        report = analyzer.analyze(features_df, surface)
    """

    def __init__(
        self,
        min_samples_per_bucket: int = 20,
        deviation_bins: int = 20
    ):
        self.min_samples = min_samples_per_bucket
        self.deviation_bins = deviation_bins

    def analyze_regime(
        self,
        df: pd.DataFrame,
        regime: str
    ) -> VolatilityRegimeStats:
        """Analyze a single volatility regime."""
        regime_df = df[df["vol_regime"] == regime] if regime != "all" else df

        if len(regime_df) == 0:
            return VolatilityRegimeStats(
                regime=regime,
                sample_size=0,
                win_rate=0.5,
                win_rate_std=0.0,
                deviation_correlation=0.0,
                mean_abs_deviation=0.0,
                surface_slope=0.0,
                surface_flatness=0.0,
                chi_square_stat=0.0,
                chi_square_p_value=1.0
            )

        sample_size = len(regime_df)
        win_rate = regime_df["outcome"].mean()
        win_rate_std = regime_df["outcome"].std()

        # Deviation correlation
        deviation_correlation = regime_df["deviation_pct"].corr(regime_df["outcome"])
        mean_abs_deviation = regime_df["deviation_pct"].abs().mean()

        # Surface characteristics
        # Bin by deviation and compute win rate in each bin
        regime_df = regime_df.copy()
        regime_df["deviation_bin"] = pd.cut(
            regime_df["deviation_pct"],
            bins=self.deviation_bins,
            labels=False
        )

        bin_win_rates = regime_df.groupby("deviation_bin")["outcome"].agg(["mean", "count"])
        bin_win_rates = bin_win_rates[bin_win_rates["count"] >= self.min_samples]

        if len(bin_win_rates) >= 2:
            # Surface slope: linear regression of win rate vs deviation bin
            x = np.arange(len(bin_win_rates))
            y = bin_win_rates["mean"].values
            slope, _, _, _, _ = stats.linregress(x, y)
            surface_slope = slope

            # Surface flatness: variance of win rates
            surface_flatness = bin_win_rates["mean"].var()
        else:
            surface_slope = 0.0
            surface_flatness = 0.0

        # Chi-square test: is outcome distribution different from uniform?
        observed = [regime_df["outcome"].sum(), len(regime_df) - regime_df["outcome"].sum()]
        expected = [len(regime_df) / 2, len(regime_df) / 2]
        chi2, p_value = stats.chisquare(observed, expected)

        return VolatilityRegimeStats(
            regime=regime,
            sample_size=sample_size,
            win_rate=win_rate,
            win_rate_std=win_rate_std,
            deviation_correlation=deviation_correlation,
            mean_abs_deviation=mean_abs_deviation,
            surface_slope=surface_slope,
            surface_flatness=surface_flatness,
            chi_square_stat=chi2,
            chi_square_p_value=p_value
        )

    def analyze(
        self,
        df: pd.DataFrame
    ) -> dict[str, VolatilityRegimeStats]:
        """
        Full volatility analysis across all regimes.

        Returns dict mapping regime name to stats.
        """
        results = {}

        for regime in ["low", "medium", "high", "all"]:
            stats = self.analyze_regime(df, regime)
            results[regime] = stats

            logger.info(
                f"Regime {regime}: n={stats.sample_size}, "
                f"win_rate={stats.win_rate:.3f}, "
                f"dev_corr={stats.deviation_correlation:.3f}"
            )

        return results

    def compare_regimes(
        self,
        df: pd.DataFrame,
        deviation_threshold: float = 0.005
    ) -> pd.DataFrame:
        """
        Compare win rates across regimes at different deviation levels.

        Answers: Does high vol flatten the relationship between
        deviation and win probability?
        """
        results = []

        # Deviation buckets
        deviation_buckets = [
            ("strongly_down", -float("inf"), -deviation_threshold),
            ("slightly_down", -deviation_threshold, 0),
            ("slightly_up", 0, deviation_threshold),
            ("strongly_up", deviation_threshold, float("inf"))
        ]

        for regime in ["low", "medium", "high"]:
            regime_df = df[df["vol_regime"] == regime]

            for bucket_name, dev_min, dev_max in deviation_buckets:
                bucket_df = regime_df[
                    (regime_df["deviation_pct"] >= dev_min) &
                    (regime_df["deviation_pct"] < dev_max)
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
                    "vol_regime": regime,
                    "deviation_bucket": bucket_name,
                    "sample_size": len(bucket_df),
                    "win_rate": win_rate,
                    "ci_low": ci_low,
                    "ci_high": ci_high
                })

        return pd.DataFrame(results)

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

    def regime_transition_analysis(
        self,
        df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Analyze what happens when volatility regime changes mid-window.

        Some windows may start in low vol and end in high vol.
        Does this affect predictability?
        """
        # This requires tracking volatility at window start vs window end
        # For now, return regime distribution per time bucket

        results = []
        for time_remaining in sorted(df["time_remaining"].unique()):
            time_df = df[df["time_remaining"] == time_remaining]

            regime_counts = time_df["vol_regime"].value_counts(normalize=True)

            results.append({
                "time_remaining": time_remaining,
                "pct_low_vol": regime_counts.get("low", 0),
                "pct_medium_vol": regime_counts.get("medium", 0),
                "pct_high_vol": regime_counts.get("high", 0),
                "total_samples": len(time_df)
            })

        return pd.DataFrame(results)

    def optimal_thresholds_by_regime(
        self,
        df: pd.DataFrame,
        target_win_rate: float = 0.55
    ) -> dict[str, float]:
        """
        Find optimal deviation threshold for each volatility regime.

        Returns the minimum |deviation| at which win rate exceeds target.
        """
        thresholds = {}

        for regime in ["low", "medium", "high"]:
            regime_df = df[df["vol_regime"] == regime].copy()

            # Sort by absolute deviation
            regime_df["abs_deviation"] = regime_df["deviation_pct"].abs()
            regime_df = regime_df.sort_values("abs_deviation")

            # Find threshold where cumulative win rate exceeds target
            # Look at strongly directional windows only (deviation > 0 for UP)
            up_df = regime_df[regime_df["deviation_pct"] > 0].copy()

            for threshold in np.arange(0.001, 0.02, 0.001):
                filtered = up_df[up_df["deviation_pct"] >= threshold]
                if len(filtered) >= self.min_samples:
                    win_rate = filtered["outcome"].mean()
                    if win_rate >= target_win_rate:
                        thresholds[regime] = threshold
                        break
            else:
                thresholds[regime] = None  # No threshold found

            logger.info(f"Regime {regime}: optimal threshold = {thresholds[regime]}")

        return thresholds


def generate_volatility_report(
    df: pd.DataFrame,
    output_path: Optional[str] = None
) -> str:
    """Generate a formatted volatility analysis report."""
    analyzer = VolatilityAnalyzer()

    # Run analyses
    regime_stats = analyzer.analyze(df)
    comparison = analyzer.compare_regimes(df)
    thresholds = analyzer.optimal_thresholds_by_regime(df)

    # Format report
    lines = []
    lines.append("=" * 60)
    lines.append("VOLATILITY REGIME ANALYSIS REPORT")
    lines.append("=" * 60)
    lines.append("")

    lines.append("1. REGIME SUMMARY")
    lines.append("-" * 40)
    for regime, stats in regime_stats.items():
        lines.append(f"\n{regime.upper()} Volatility:")
        lines.append(f"  Samples: {stats.sample_size:,}")
        lines.append(f"  Win Rate: {stats.win_rate:.1%}")
        lines.append(f"  Deviation Correlation: {stats.deviation_correlation:.3f}")
        lines.append(f"  Surface Slope: {stats.surface_slope:.4f}")
        lines.append(f"  Chi-square p-value: {stats.chi_square_p_value:.4f}")

    lines.append("")
    lines.append("2. WIN RATES BY DEVIATION BUCKET")
    lines.append("-" * 40)
    lines.append(comparison.to_string(index=False))

    lines.append("")
    lines.append("3. OPTIMAL THRESHOLDS BY REGIME")
    lines.append("-" * 40)
    for regime, threshold in thresholds.items():
        if threshold:
            lines.append(f"  {regime}: {threshold:.1%} deviation")
        else:
            lines.append(f"  {regime}: No threshold found")

    lines.append("")
    lines.append("4. KEY FINDINGS")
    lines.append("-" * 40)

    # Determine key findings
    low_stats = regime_stats["low"]
    high_stats = regime_stats["high"]

    if low_stats.deviation_correlation > high_stats.deviation_correlation + 0.05:
        lines.append("  - Deviation is MORE predictive in low volatility")
    elif high_stats.deviation_correlation > low_stats.deviation_correlation + 0.05:
        lines.append("  - Deviation is MORE predictive in high volatility")
    else:
        lines.append("  - Deviation predictiveness is similar across regimes")

    if high_stats.surface_flatness < low_stats.surface_flatness * 0.5:
        lines.append("  - Probability surface FLATTENS in high volatility")
    else:
        lines.append("  - Probability surface shape is consistent across regimes")

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

    print("VolatilityAnalyzer module loaded successfully")
