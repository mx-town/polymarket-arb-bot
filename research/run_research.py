#!/usr/bin/env python3
"""
Polymarket Probability Model Research Pipeline

This script orchestrates the full research workflow:
1. Fetch historical Binance data (6+ months of 1-min candles)
2. Extract features for 15-min windows
3. Build probability surface
4. Analyze volatility and session effects
5. Run backtest validation
6. Generate reports and lookup tables

Usage:
    python research/run_research.py --fetch --analyze --validate

Options:
    --fetch       Fetch/update historical data from Binance
    --analyze     Run statistical analysis
    --validate    Run backtest and calibration validation
    --all         Run all steps
    --months N    Number of months of data (default: 6)
    --window N    Window size in minutes (default: 15)
    --symbol SYM  Symbol to analyze (default: BTCUSDT)
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Add parent to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from research.data.binance_historical import BinanceHistoricalFetcher
from research.data.feature_extractor import FeatureExtractor, create_training_dataset
from research.models.probability_surface import (
    ProbabilitySurface,
    analyze_probability_by_deviation,
    analyze_probability_by_time
)
from research.models.edge_calculator import EdgeCalculator
from research.analysis.volatility_analysis import VolatilityAnalyzer, generate_volatility_report
from research.analysis.session_analysis import SessionAnalyzer, generate_session_report
from research.analysis.lag_analysis import LagAnalyzer, generate_lag_report
from research.analysis.validation import (
    BacktestValidator,
    CalibrationAnalyzer,
    generate_validation_report
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(name)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Output directories
OUTPUT_DIR = Path(__file__).parent / "output"
DATA_DIR = Path(__file__).parent / "data" / "raw"
MODELS_DIR = OUTPUT_DIR / "models"
REPORTS_DIR = OUTPUT_DIR / "reports"


def setup_directories():
    """Create output directories if they don't exist."""
    for d in [OUTPUT_DIR, DATA_DIR, MODELS_DIR, REPORTS_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def fetch_data(symbol: str, months: int) -> None:
    """Step 1: Fetch historical data from Binance."""
    logger.info(f"Fetching {months} months of {symbol} data...")

    fetcher = BinanceHistoricalFetcher(data_dir=str(DATA_DIR))
    df = fetcher.fetch(symbol=symbol, months=months)

    logger.info(f"Fetched {len(df):,} candles")
    logger.info(f"Date range: {df['open_time'].min()} to {df['open_time'].max()}")

    return df


def extract_features(df, symbol: str, window_minutes: int):
    """Step 2: Extract features from candle data."""
    logger.info(f"Extracting features for {window_minutes}-minute windows...")

    extractor = FeatureExtractor(window_minutes=window_minutes)
    features_df = extractor.extract_windows(df, symbol)

    # Save features
    features_path = DATA_DIR / f"{symbol}_{window_minutes}m_features.parquet"
    features_df.to_parquet(features_path, index=False)
    logger.info(f"Saved {len(features_df):,} feature observations to {features_path}")

    return features_df


def build_probability_surface(features_df, symbol: str, window_minutes: int):
    """Step 3: Build and save probability surface."""
    logger.info("Building probability surface...")

    surface = ProbabilitySurface(
        deviation_step=0.001,  # 0.1% buckets
        deviation_range=(-0.02, 0.02)  # -2% to +2%
    )
    surface.fit(features_df)

    # Save surface
    surface_path = MODELS_DIR / f"{symbol}_{window_minutes}m_surface.json"
    surface.save(str(surface_path))

    # Export as CSV for easy viewing
    surface_df = surface.to_dataframe()
    csv_path = MODELS_DIR / f"{symbol}_{window_minutes}m_surface.csv"
    surface_df.to_csv(csv_path, index=False)
    logger.info(f"Saved probability surface to {surface_path}")

    # Summary stats
    stats = surface.summary_stats()
    logger.info(f"Surface stats: {stats}")

    return surface


def run_analysis(features_df, surface, symbol: str, window_minutes: int):
    """Step 4: Run statistical analyses."""
    logger.info("Running statistical analyses...")

    # Volatility analysis
    logger.info("Analyzing volatility regimes...")
    vol_report = generate_volatility_report(
        features_df,
        output_path=str(REPORTS_DIR / f"{symbol}_{window_minutes}m_volatility.txt")
    )
    print("\n" + vol_report)

    # Session analysis
    logger.info("Analyzing trading sessions...")
    session_report = generate_session_report(
        features_df,
        output_path=str(REPORTS_DIR / f"{symbol}_{window_minutes}m_sessions.txt")
    )
    print("\n" + session_report)

    # Probability by deviation (at mid-point time)
    mid_time = window_minutes // 2
    dev_analysis = analyze_probability_by_deviation(surface, time_remaining=mid_time)
    dev_path = REPORTS_DIR / f"{symbol}_{window_minutes}m_prob_by_deviation.csv"
    dev_analysis.to_csv(dev_path, index=False)
    logger.info(f"Saved deviation analysis to {dev_path}")

    # Probability by time (at 0.5% deviation)
    time_analysis = analyze_probability_by_time(surface, deviation_pct=0.005)
    time_path = REPORTS_DIR / f"{symbol}_{window_minutes}m_prob_by_time.csv"
    time_analysis.to_csv(time_path, index=False)
    logger.info(f"Saved time analysis to {time_path}")

    return {
        "volatility": vol_report,
        "sessions": session_report,
        "by_deviation": dev_analysis,
        "by_time": time_analysis
    }


def run_validation(features_df, surface, symbol: str, window_minutes: int):
    """Step 5: Run backtest and calibration validation."""
    logger.info("Running validation...")

    # Fee rate based on window size
    fee_rate = 0.0 if window_minutes == 60 else 0.03

    # Backtest
    logger.info("Running backtest...")
    validator = BacktestValidator(
        fee_rate=fee_rate,
        min_edge_threshold=0.05,
        use_kelly_sizing=False
    )
    backtest_result = validator.run(
        features_df,
        position_size=100.0,
        train_fraction=0.7
    )

    # Calibration
    logger.info("Running calibration analysis...")
    calibration_analyzer = CalibrationAnalyzer(n_bins=10)

    # Split for calibration test
    train_size = int(len(features_df) * 0.7)
    train_df = features_df.iloc[:train_size]
    test_df = features_df.iloc[train_size:]

    # Rebuild surface on train only
    train_surface = ProbabilitySurface()
    train_surface.fit(train_df)

    calibration_result = calibration_analyzer.analyze_from_surface(train_surface, test_df)

    # Generate validation report
    validation_report = generate_validation_report(
        backtest_result,
        calibration_result,
        output_path=str(REPORTS_DIR / f"{symbol}_{window_minutes}m_validation.txt")
    )
    print("\n" + validation_report)

    return {
        "backtest": backtest_result,
        "calibration": calibration_result
    }


def generate_lookup_table(surface, symbol: str, window_minutes: int):
    """Generate the final probability lookup table for trading."""
    logger.info("Generating probability lookup table...")

    # Create lookup table as DataFrame
    rows = []

    for time_remaining in range(window_minutes):
        for dev_pct in range(-20, 21):  # -2% to +2% in 0.1% steps
            deviation = dev_pct / 1000  # Convert to decimal

            for vol_regime in ["low", "medium", "high", "all"]:
                prob, ci_low, ci_high, reliable = surface.get_probability(
                    deviation_pct=deviation,
                    time_remaining=time_remaining,
                    vol_regime=vol_regime
                )

                bucket = surface.get_bucket(deviation, time_remaining, vol_regime)
                sample_size = bucket.sample_size if bucket else 0

                rows.append({
                    "deviation_pct": deviation,
                    "time_remaining": time_remaining,
                    "vol_regime": vol_regime,
                    "prob_up": round(prob, 4),
                    "ci_lower": round(ci_low, 4),
                    "ci_upper": round(ci_high, 4),
                    "sample_size": sample_size,
                    "reliable": reliable
                })

    lookup_df = pd.DataFrame(rows)

    # Save lookup table
    lookup_path = MODELS_DIR / f"{symbol}_{window_minutes}m_lookup.csv"
    lookup_df.to_csv(lookup_path, index=False)
    logger.info(f"Saved lookup table ({len(lookup_df):,} rows) to {lookup_path}")

    # Also save as parquet for faster loading
    parquet_path = MODELS_DIR / f"{symbol}_{window_minutes}m_lookup.parquet"
    lookup_df.to_parquet(parquet_path, index=False)

    return lookup_df


def print_summary(features_df, surface, analysis_results, validation_results):
    """Print summary of research findings."""
    print("\n" + "=" * 60)
    print("RESEARCH SUMMARY")
    print("=" * 60)

    # Data summary
    n_windows = features_df["window_start"].nunique()
    n_observations = len(features_df)
    print(f"\nData:")
    print(f"  Windows analyzed: {n_windows:,}")
    print(f"  Total observations: {n_observations:,}")

    # Surface summary
    stats = surface.summary_stats()
    print(f"\nProbability Surface:")
    print(f"  Total buckets: {stats['total_buckets']:,}")
    print(f"  Reliable buckets: {stats['reliable_buckets']:,}")
    print(f"  Mean win rate: {stats['mean_win_rate']:.1%}")

    # Key findings from deviation analysis
    dev_df = analysis_results.get("by_deviation")
    if dev_df is not None and len(dev_df) > 0:
        print(f"\nDeviation Effect:")
        # Find extreme buckets
        extreme_up = dev_df[dev_df["deviation_mid"] > 0.005]
        extreme_down = dev_df[dev_df["deviation_mid"] < -0.005]

        if len(extreme_up) > 0:
            up_wr = extreme_up["win_rate"].mean()
            print(f"  At +0.5% deviation: {up_wr:.1%} UP win rate")
        if len(extreme_down) > 0:
            down_wr = extreme_down["win_rate"].mean()
            print(f"  At -0.5% deviation: {down_wr:.1%} UP win rate")

    # Validation summary
    if validation_results:
        bt = validation_results["backtest"]
        cal = validation_results["calibration"]

        print(f"\nBacktest (after 3% fees):")
        print(f"  Trades: {bt.total_trades:,}")
        print(f"  Win rate: {bt.win_rate:.1%}")
        print(f"  Net P&L: ${bt.net_pnl:,.2f}")
        print(f"  Sharpe: {bt.sharpe_ratio:.2f}")

        print(f"\nCalibration:")
        print(f"  Brier score: {cal.brier_score:.4f}")
        print(f"  Well-calibrated: {'Yes' if cal.is_calibrated else 'No'}")

    print("\n" + "=" * 60)


def main():
    parser = argparse.ArgumentParser(
        description="Polymarket Probability Model Research Pipeline"
    )
    parser.add_argument("--fetch", action="store_true", help="Fetch historical data")
    parser.add_argument("--analyze", action="store_true", help="Run statistical analysis")
    parser.add_argument("--validate", action="store_true", help="Run validation")
    parser.add_argument("--all", action="store_true", help="Run all steps")
    parser.add_argument("--months", type=int, default=6, help="Months of data")
    parser.add_argument("--window", type=int, default=15, help="Window size in minutes")
    parser.add_argument("--symbol", type=str, default="BTCUSDT", help="Symbol to analyze")

    args = parser.parse_args()

    # Default to all if no specific step selected
    if not any([args.fetch, args.analyze, args.validate]):
        args.all = True

    if args.all:
        args.fetch = args.analyze = args.validate = True

    setup_directories()

    # Import pandas here after confirming it's available
    import pandas as pd
    globals()["pd"] = pd

    # Step 1: Fetch data
    fetcher = BinanceHistoricalFetcher(data_dir=str(DATA_DIR))

    if args.fetch:
        candle_df = fetch_data(args.symbol, args.months)
    else:
        candle_df = fetcher.get_data(args.symbol)
        if candle_df is None:
            logger.error(f"No cached data found. Run with --fetch first.")
            return 1

    # Step 2: Extract features
    features_path = DATA_DIR / f"{args.symbol}_{args.window}m_features.parquet"
    if features_path.exists() and not args.fetch:
        features_df = pd.read_parquet(features_path)
        logger.info(f"Loaded {len(features_df):,} cached features")
    else:
        features_df = extract_features(candle_df, args.symbol, args.window)

    # Step 3: Build probability surface
    surface = build_probability_surface(features_df, args.symbol, args.window)

    # Step 4: Run analysis
    analysis_results = {}
    if args.analyze:
        analysis_results = run_analysis(features_df, surface, args.symbol, args.window)

    # Step 5: Run validation
    validation_results = None
    if args.validate:
        validation_results = run_validation(features_df, surface, args.symbol, args.window)

    # Step 6: Generate lookup table
    generate_lookup_table(surface, args.symbol, args.window)

    # Print summary
    print_summary(features_df, surface, analysis_results, validation_results)

    logger.info("Research complete!")
    logger.info(f"Outputs saved to: {OUTPUT_DIR}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
