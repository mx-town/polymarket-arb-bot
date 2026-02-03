"""
CLI entry point for data capture and model management.

Usage:
    arb-capture init                    # Download data + build model
    arb-capture rebuild                 # Rebuild model from existing data
    arb-capture observe [--duration N]  # Run live observation with model
    arb-capture verify                  # 5-min stream health check
    arb-capture --debug <command>       # Enable verbose logging
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

from src.data.capture.enricher import SnapshotEnricher
from src.data.capture.synchronizer import StreamSynchronizer, SynchronizerConfig
from src.data.capture.verify import print_results, verify_streams
from src.data.streams.base import StreamSource
from src.data.streams.binance_direct import BinanceDirectStream
from src.data.streams.chainlink_rpc import ChainlinkRPCPoller
from src.data.streams.clob_adapter import SimpleCLOBStream
from src.data.streams.rtds import RTDSStream
from src.market.discovery import fetch_updown_events
from src.utils.logging import get_logger, setup_logging

logger = get_logger("capture_cli")

# Default paths
RAW_DATA_DIR = "research/data/raw"
MODELS_DIR = "research/models"
OBSERVATIONS_DIR = "research/data/observations"
SURFACE_PATH = "research/models/probability_surface.json"
CANDLE_PATH = "research/data/raw/BTCUSDT_1m.parquet"
FEATURES_PATH = "research/data/raw/BTCUSDT_15m_features.parquet"


# =============================================================================
# Command: init
# =============================================================================


def cmd_init(args) -> int:
    """Download data and build model (first-time setup)."""
    logger.info("INIT_START", f"months={args.months}")

    # 1. Create directories
    for dir_path in [RAW_DATA_DIR, MODELS_DIR, OBSERVATIONS_DIR]:
        Path(dir_path).mkdir(parents=True, exist_ok=True)
        logger.info("DIR_CREATED", dir_path)

    # 2. Download Binance data
    logger.info("DOWNLOAD_START", "Fetching Binance 1-minute candles...")
    try:
        from research.data.binance_historical import BinanceHistoricalFetcher

        fetcher = BinanceHistoricalFetcher(
            symbols=["BTCUSDT"],
            months_back=args.months,
            data_dir=RAW_DATA_DIR,
        )
        df = fetcher.get_data("BTCUSDT")
        if df is None or len(df) == 0:
            logger.error("DOWNLOAD_FAILED", "No data returned")
            return 1
        logger.info("DOWNLOAD_COMPLETE", f"candles={len(df):,}")
    except Exception as e:
        logger.error("DOWNLOAD_ERROR", str(e))
        return 1

    # 3. Extract features
    logger.info("EXTRACT_START", "Extracting 15-minute window features...")
    try:
        from research.data.feature_extractor import FeatureExtractor

        extractor = FeatureExtractor(window_minutes=15)
        features_df = extractor.extract_windows(df, "BTCUSDT")
        features_df.to_parquet(FEATURES_PATH, index=False)
        logger.info("EXTRACT_COMPLETE", f"observations={len(features_df):,} windows={features_df['window_start'].nunique():,}")
    except Exception as e:
        logger.error("EXTRACT_ERROR", str(e))
        return 1

    # 4. Build probability surface
    logger.info("MODEL_START", "Building probability surface...")
    try:
        from research.models.probability_surface import ProbabilitySurface

        surface = ProbabilitySurface()
        surface.fit(features_df)
        surface.save(SURFACE_PATH)
        stats = surface.summary_stats()
        logger.info("MODEL_COMPLETE", f"buckets={stats['total_buckets']} reliable={stats['reliable_buckets']}")
    except Exception as e:
        logger.error("MODEL_ERROR", str(e))
        return 1

    print(f"\n{'='*60}")
    print("INITIALIZATION COMPLETE")
    print(f"{'='*60}")
    print(f"  Raw data:     {CANDLE_PATH}")
    print(f"  Features:     {FEATURES_PATH}")
    print(f"  Model:        {SURFACE_PATH}")
    print(f"\nRun 'arb-capture observe' to start live observation.")
    print(f"{'='*60}\n")

    return 0


# =============================================================================
# Command: rebuild
# =============================================================================


def cmd_rebuild(args) -> int:
    """Rebuild model from existing data."""
    import pandas as pd

    # Check if raw data exists
    if not Path(CANDLE_PATH).exists():
        logger.error("NO_DATA", f"Raw data not found at {CANDLE_PATH}")
        print("Run 'arb-capture init' first to download data.")
        return 1

    logger.info("REBUILD_START", "Rebuilding model from existing data...")

    # 1. Load raw data
    logger.info("LOAD_DATA", CANDLE_PATH)
    df = pd.read_parquet(CANDLE_PATH)
    logger.info("DATA_LOADED", f"candles={len(df):,}")

    # 2. Extract features
    logger.info("EXTRACT_START", "Extracting features...")
    try:
        from research.data.feature_extractor import FeatureExtractor

        extractor = FeatureExtractor(window_minutes=15)
        features_df = extractor.extract_windows(df, "BTCUSDT")
        features_df.to_parquet(FEATURES_PATH, index=False)
        logger.info("EXTRACT_COMPLETE", f"observations={len(features_df):,}")
    except Exception as e:
        logger.error("EXTRACT_ERROR", str(e))
        return 1

    # 3. Build model
    logger.info("MODEL_START", "Building probability surface...")
    try:
        from research.models.probability_surface import ProbabilitySurface

        surface = ProbabilitySurface()
        surface.fit(features_df)
        surface.save(SURFACE_PATH)
        stats = surface.summary_stats()
        logger.info("MODEL_COMPLETE", f"buckets={stats['total_buckets']} reliable={stats['reliable_buckets']}")
    except Exception as e:
        logger.error("MODEL_ERROR", str(e))
        return 1

    print(f"\n{'='*60}")
    print("MODEL REBUILT")
    print(f"{'='*60}")
    print(f"  Features:     {FEATURES_PATH}")
    print(f"  Model:        {SURFACE_PATH}")
    print(f"{'='*60}\n")

    return 0


# =============================================================================
# Command: observe
# =============================================================================


def cmd_observe(args) -> int:
    """Run live observation with model predictions."""
    # Check if model exists
    if not Path(SURFACE_PATH).exists():
        logger.warning("NO_MODEL", f"Model not found at {SURFACE_PATH}")
        print("Run 'arb-capture init' or 'arb-capture rebuild' first.")
        print("Continuing without model predictions...\n")

    return run_capture(
        duration_sec=args.duration,
        output_dir=args.output,
        snapshot_interval_ms=args.interval,
        observation_mode=True,
        surface_path=SURFACE_PATH,
    )


# =============================================================================
# Command: verify
# =============================================================================


def cmd_verify(args) -> int:
    """Test stream connections."""
    logger.info("VERIFY_START", f"duration={args.duration}s")
    results = verify_streams(duration_sec=args.duration)
    success = print_results(results)
    return 0 if success else 1


# =============================================================================
# Internal: run_capture (used by observe)
# =============================================================================


def run_capture(
    duration_sec: int,
    output_dir: str,
    snapshot_interval_ms: int = 100,
    observation_mode: bool = False,
    surface_path: str | None = None,
) -> int:
    """
    Run data capture for specified duration.

    Args:
        duration_sec: How long to capture (seconds)
        output_dir: Directory for output files
        snapshot_interval_ms: Interval between snapshots
        observation_mode: If True, enrich snapshots with model predictions
        surface_path: Path to probability surface model (for observation mode)

    Returns:
        Exit code (0 for success)
    """
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parquet_path = os.path.join(output_dir, f"snapshots_{timestamp}.parquet")
    report_path = os.path.join(output_dir, f"lag_report_{timestamp}.txt")

    mode_str = "observation" if observation_mode else "raw"
    logger.info("CAPTURE_START", f"duration={duration_sec}s output={output_dir} mode={mode_str}")

    # Set up enricher for observation mode
    enricher = None
    if observation_mode:
        enricher = SnapshotEnricher(surface_path=surface_path)
        if enricher.surface is None:
            logger.warning("OBSERVATION_MODE", "Running without model - no surface loaded")

    # Snapshot callback with optional enrichment
    def on_snapshot(snapshot):
        if enricher is not None:
            enricher.enrich(snapshot)

    # Set up synchronizer
    config = SynchronizerConfig(
        snapshot_interval_ms=snapshot_interval_ms,
        ring_buffer_size=100000,
    )
    sync = StreamSynchronizer(config=config, on_snapshot=on_snapshot)

    # Connect streams
    binance_stream = BinanceDirectStream(on_update=sync.on_price_update)
    rtds_stream = RTDSStream(
        on_binance_update=sync.on_price_update,
        on_chainlink_update=sync.on_price_update,
    )
    chainlink_poller = ChainlinkRPCPoller(on_update=sync.on_price_update)

    # Discover 15m markets for CLOB
    token_ids = []
    try:
        markets = fetch_updown_events(candle_interval="15m", assets=["bitcoin"], max_markets=10)
        for m in markets:
            token_ids.append(m["yes_token"])
            token_ids.append(m["no_token"])
        logger.info("MARKETS_FOUND", f"count={len(markets)} tokens={len(token_ids)}")
    except Exception as e:
        logger.warning("MARKET_DISCOVERY_FAILED", str(e))

    clob_stream = (
        SimpleCLOBStream(token_ids=token_ids, on_update=sync.on_clob_update) if token_ids else None
    )

    # Graceful shutdown handler
    shutdown_requested = False

    def signal_handler(signum, frame):
        nonlocal shutdown_requested
        logger.info("SHUTDOWN_REQUESTED", f"signal={signum}")
        shutdown_requested = True

    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)

    # Start everything
    sync.start()
    binance_stream.connect()
    rtds_stream.connect()
    chainlink_poller.connect()
    if clob_stream:
        clob_stream.connect()

    # Wait for streams to connect
    time.sleep(5)

    # Run capture
    start_time = time.time()
    last_export_time = start_time
    export_interval = 3600

    while not shutdown_requested and (time.time() - start_time) < duration_sec:
        elapsed = int(time.time() - start_time)
        remaining = duration_sec - elapsed

        # Progress update every 60 seconds
        if elapsed % 60 == 0 and elapsed > 0:
            stats = sync.get_stats()
            lag_stats = sync.get_lag_stats()
            counts = {s.name: stats[s].update_count for s in StreamSource}
            logger.info(
                "PROGRESS",
                f"elapsed={elapsed}s remaining={remaining}s counts={counts} lag_p50={lag_stats.get('p50')}ms",
            )

        # Periodic export (every hour)
        if time.time() - last_export_time >= export_interval:
            hourly_path = os.path.join(
                output_dir, f"snapshots_{timestamp}_hour{elapsed // 3600}.parquet"
            )
            sync.export_to_parquet(hourly_path)
            last_export_time = time.time()

        time.sleep(1)

    # Stop everything
    sync.stop()
    binance_stream.disconnect()
    rtds_stream.disconnect()
    chainlink_poller.disconnect()
    if clob_stream:
        clob_stream.disconnect()

    # Final export
    exported = sync.export_to_parquet(parquet_path)

    # Generate report
    stats = sync.get_stats()
    lag_stats = sync.get_lag_stats()

    report_lines = [
        "=" * 60,
        "LAG MEASUREMENT REPORT",
        f"Generated: {datetime.now().isoformat()}",
        f"Duration: {duration_sec}s",
        f"Mode: {mode_str}",
        "=" * 60,
        "",
        "STREAM STATISTICS",
        "-" * 40,
    ]

    for source in StreamSource:
        s = stats[source]
        report_lines.append(f"{source.name}:")
        report_lines.append(f"  Updates: {s.update_count}")
        if s.updates_per_sec:
            report_lines.append(f"  Rate: {s.updates_per_sec:.2f}/sec")
        if s.min_price and s.max_price:
            report_lines.append(f"  Price range: ${s.min_price:.2f} - ${s.max_price:.2f}")
        report_lines.append("")

    report_lines.extend(
        [
            "CLOB STATISTICS",
            "-" * 40,
            f"Updates: {sync.get_clob_update_count()}",
            "",
            "LAG STATISTICS (Binance -> Chainlink)",
            "-" * 40,
            f"Sample count: {lag_stats.get('count', 0)}",
            f"P50: {lag_stats.get('p50')}ms",
            f"P95: {lag_stats.get('p95')}ms",
            f"P99: {lag_stats.get('p99')}ms",
            f"Min: {lag_stats.get('min')}ms",
            f"Max: {lag_stats.get('max')}ms",
            "",
            "=" * 60,
            f"Exported {exported} snapshots to {parquet_path}",
            "=" * 60,
        ]
    )

    report_content = "\n".join(report_lines)
    with open(report_path, "w") as f:
        f.write(report_content)

    print(report_content)
    logger.info("CAPTURE_COMPLETE", f"snapshots={exported} report={report_path}")

    return 0


# =============================================================================
# Main entry point
# =============================================================================


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Polymarket Arbitrage Data Tools",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Commands:
  init      Download data and build probability model (first-time setup)
  rebuild   Rebuild model from existing data
  observe   Run live observation with model predictions
  verify    Test stream connections (5-minute health check)

Examples:
  arb-capture init                     # First-time setup
  arb-capture observe --duration 3600  # 1-hour observation
  arb-capture --debug verify           # Verbose stream test
""",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug logging",
    )

    subparsers = parser.add_subparsers(dest="command", metavar="command")

    # init
    init_parser = subparsers.add_parser("init", help="Download data and build model")
    init_parser.add_argument(
        "--months",
        type=int,
        default=6,
        help="Months of historical data to download (default: 6)",
    )

    # rebuild
    subparsers.add_parser("rebuild", help="Rebuild model from existing data")

    # observe
    observe_parser = subparsers.add_parser("observe", help="Run live observation with model")
    observe_parser.add_argument(
        "--duration",
        type=int,
        default=3600,
        help="Observation duration in seconds (default: 3600 = 1 hour)",
    )
    observe_parser.add_argument(
        "--output",
        type=str,
        default=OBSERVATIONS_DIR,
        help=f"Output directory (default: {OBSERVATIONS_DIR})",
    )
    observe_parser.add_argument(
        "--interval",
        type=int,
        default=100,
        help="Snapshot interval in ms (default: 100)",
    )

    # verify
    verify_parser = subparsers.add_parser("verify", help="Test stream connections")
    verify_parser.add_argument(
        "--duration",
        type=int,
        default=300,
        help="Verification duration in seconds (default: 300 = 5 minutes)",
    )

    args = parser.parse_args()

    # Set up logging
    setup_logging(verbose=args.debug)

    # Handle no command
    if args.command is None:
        parser.print_help()
        return 1

    # Dispatch to command
    if args.command == "init":
        return cmd_init(args)
    elif args.command == "rebuild":
        return cmd_rebuild(args)
    elif args.command == "observe":
        return cmd_observe(args)
    elif args.command == "verify":
        return cmd_verify(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
