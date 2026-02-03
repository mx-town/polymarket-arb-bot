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
        logger.info(
            "EXTRACT_COMPLETE",
            f"observations={len(features_df):,} windows={features_df['window_start'].nunique():,}",
        )
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
        logger.info(
            "MODEL_COMPLETE",
            f"buckets={stats['total_buckets']} reliable={stats['reliable_buckets']}",
        )
    except Exception as e:
        logger.error("MODEL_ERROR", str(e))
        return 1

    print(f"\n{'=' * 60}")
    print("INITIALIZATION COMPLETE")
    print(f"{'=' * 60}")
    print(f"  Raw data:     {CANDLE_PATH}")
    print(f"  Features:     {FEATURES_PATH}")
    print(f"  Model:        {SURFACE_PATH}")
    print("\nRun 'arb-capture observe' to start live observation.")
    print(f"{'=' * 60}\n")

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
        logger.info(
            "MODEL_COMPLETE",
            f"buckets={stats['total_buckets']} reliable={stats['reliable_buckets']}",
        )
    except Exception as e:
        logger.error("MODEL_ERROR", str(e))
        return 1

    print(f"\n{'=' * 60}")
    print("MODEL REBUILT")
    print(f"{'=' * 60}")
    print(f"  Features:     {FEATURES_PATH}")
    print(f"  Model:        {SURFACE_PATH}")
    print(f"{'=' * 60}\n")

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
# Command: analyse
# =============================================================================


def cmd_analyse(args) -> int:
    """Analyse captured observation data."""
    import glob

    import pandas as pd

    # Find observation files
    pattern = os.path.join(args.input, "snapshots_*.parquet")
    files = sorted(glob.glob(pattern))

    if not files:
        print(f"No observation files found in {args.input}")
        print("Run 'arb-capture observe' first to capture data.")
        return 1

    # Use most recent file or specified file
    if args.file:
        parquet_path = args.file
    else:
        parquet_path = files[-1]  # Most recent

    print(f"{'=' * 70}")
    print("OBSERVATION ANALYSIS")
    print(f"{'=' * 70}")
    print(f"File: {parquet_path}")
    print()

    df = pd.read_parquet(parquet_path)
    valid = df[df["binance_direct_price"].notna()]

    # Basic stats
    duration_ms = df["timestamp_ms"].max() - df["timestamp_ms"].min()
    duration_sec = duration_ms / 1000

    print(f"{'=' * 70}")
    print("CAPTURE SUMMARY")
    print(f"{'=' * 70}")
    print(f"  Total snapshots:    {len(df):,}")
    print(f"  Valid (with price): {len(valid):,} ({len(valid) / len(df) * 100:.1f}%)")
    print(f"  Duration:           {duration_sec / 60:.1f} minutes")
    print(f"  Snapshot rate:      {len(df) / duration_sec:.1f}/sec")
    print()

    # Price movement
    btc = valid["binance_direct_price"]
    print(f"{'=' * 70}")
    print("BTC PRICE MOVEMENT")
    print(f"{'=' * 70}")
    print(f"  Start:  ${btc.iloc[0]:,.2f}")
    print(f"  End:    ${btc.iloc[-1]:,.2f}")
    print(f"  Min:    ${btc.min():,.2f}")
    print(f"  Max:    ${btc.max():,.2f}")
    print(f"  Range:  ${btc.max() - btc.min():,.2f} ({(btc.max() / btc.min() - 1) * 100:.3f}%)")
    print()

    # Lag analysis
    lag = valid["lag_ms"].dropna()
    print(f"{'=' * 70}")
    print("LAG DISTRIBUTION (Binance → Chainlink)")
    print(f"{'=' * 70}")
    print(f"  Samples:  {len(lag):,}")
    print(f"  Mean:     {lag.mean():.0f}ms")
    print(f"  Std:      {lag.std():.0f}ms")
    print(f"  P25:      {lag.quantile(0.25):.0f}ms")
    print(f"  P50:      {lag.quantile(0.50):.0f}ms")
    print(f"  P75:      {lag.quantile(0.75):.0f}ms")
    print(f"  P95:      {lag.quantile(0.95):.0f}ms")
    print(f"  P99:      {lag.quantile(0.99):.0f}ms")
    print()

    # Model predictions
    if "model_prob_up" in valid.columns:
        prob = valid["model_prob_up"].dropna()
        print(f"{'=' * 70}")
        print("MODEL PREDICTIONS")
        print(f"{'=' * 70}")
        print(
            f"  Coverage:        {len(prob):,} / {len(valid):,} ({len(prob) / len(valid) * 100:.1f}%)"
        )
        print(f"  Mean P(UP):      {prob.mean():.3f}")
        print(f"  Std:             {prob.std():.3f}")
        print("  Distribution:")
        print(
            f"    < 0.2 (Strong DOWN):  {(prob < 0.2).sum():>6,} ({(prob < 0.2).mean() * 100:>5.1f}%)"
        )
        print(
            f"    0.2-0.4 (Lean DOWN):  {((prob >= 0.2) & (prob < 0.4)).sum():>6,} ({((prob >= 0.2) & (prob < 0.4)).mean() * 100:>5.1f}%)"
        )
        print(
            f"    0.4-0.6 (Neutral):    {((prob >= 0.4) & (prob < 0.6)).sum():>6,} ({((prob >= 0.4) & (prob < 0.6)).mean() * 100:>5.1f}%)"
        )
        print(
            f"    0.6-0.8 (Lean UP):    {((prob >= 0.6) & (prob < 0.8)).sum():>6,} ({((prob >= 0.6) & (prob < 0.8)).mean() * 100:>5.1f}%)"
        )
        print(
            f"    > 0.8 (Strong UP):    {(prob >= 0.8).sum():>6,} ({(prob >= 0.8).mean() * 100:>5.1f}%)"
        )
        print()

    # Candle tracking
    if "candle_open_price" in valid.columns:
        candle_opens = valid["candle_open_price"].dropna()
        unique_opens = candle_opens.nunique()
        print(f"{'=' * 70}")
        print("CANDLE TRACKING (15-minute windows)")
        print(f"{'=' * 70}")
        print(f"  Windows tracked:  {unique_opens}")
        print(f"  Open prices:      {sorted(candle_opens.unique())}")
        # Deviation from candle open
        deviation = (
            (valid["binance_direct_price"] - valid["candle_open_price"])
            / valid["candle_open_price"]
            * 100
        )
        print("  Deviation from open:")
        print(f"    Mean:   {deviation.mean():+.4f}%")
        print(f"    Min:    {deviation.min():+.4f}%")
        print(f"    Max:    {deviation.max():+.4f}%")
        print("  Signal thresholds (±0.1%):")
        print(f"    UP triggers:    {(deviation > 0.1).sum():,}")
        print(f"    DOWN triggers:  {(deviation < -0.1).sum():,}")
        print()

    # Signal detections
    if "signal_detected" in valid.columns:
        signals = valid[valid["signal_detected"].notna()]
        print(f"{'=' * 70}")
        print("SIGNAL DETECTIONS")
        print(f"{'=' * 70}")
        print(f"  Total signals:  {len(signals)}")
        if len(signals) > 0:
            for sig_type, count in signals["signal_detected"].value_counts().items():
                print(f"    {sig_type}: {count}")
        else:
            print("    (No signals detected)")
        print()

    # Edge analysis
    if "edge_after_fees" in valid.columns:
        edge = valid["edge_after_fees"].dropna()
        print(f"{'=' * 70}")
        print("EDGE ANALYSIS")
        print(f"{'=' * 70}")
        print(f"  Coverage:       {len(edge):,} snapshots")
        print(f"  Mean edge:      {edge.mean() * 100:.2f}%")
        print(f"  Max edge:       {edge.max() * 100:.2f}%")
        print(f"  Positive edge:  {(edge > 0).sum():,} ({(edge > 0).mean() * 100:.1f}%)")
        print(f"  Edge > 1%:      {(edge > 0.01).sum():,}")
        print(f"  Edge > 2%:      {(edge > 0.02).sum():,}")
        print(f"  Edge > 5%:      {(edge > 0.05).sum():,}")
        print()

    # CLOB markets
    clob_cols = [c for c in df.columns if c.startswith("clob_")]
    if clob_cols:
        market_ids = list({c.split("_")[1] for c in clob_cols})
        print(f"{'=' * 70}")
        print(f"CLOB MARKETS ({len(market_ids)} tracked)")
        print(f"{'=' * 70}")
        for mid in sorted(market_ids)[:5]:  # Show first 5
            bid_col = f"clob_{mid}_bid"
            ask_col = f"clob_{mid}_ask"
            bids = valid[bid_col].dropna()
            asks = valid[ask_col].dropna()
            if len(bids) > 0:
                combined = (bids + asks).mean()
                print(
                    f"  {mid}: bid={bids.mean():.3f} ask={asks.mean():.3f} combined={combined:.3f}"
                )
        if len(market_ids) > 5:
            print(f"  ... and {len(market_ids) - 5} more markets")
        print()

    print(f"{'=' * 70}")
    print("ANALYSIS COMPLETE")
    print(f"{'=' * 70}")

    return 0


# =============================================================================
# Command: reset
# =============================================================================


def cmd_reset(args) -> int:
    """Clear old observation data."""
    import glob

    target_dir = args.dir

    if not os.path.exists(target_dir):
        print(f"Directory does not exist: {target_dir}")
        return 1

    # Find files to delete
    patterns = ["snapshots_*.parquet", "lag_report_*.txt"]
    files_to_delete = []
    for pattern in patterns:
        files_to_delete.extend(glob.glob(os.path.join(target_dir, pattern)))

    if not files_to_delete:
        print(f"No observation files found in {target_dir}")
        return 0

    # Show what will be deleted
    print(f"Files to delete ({len(files_to_delete)}):")
    for f in sorted(files_to_delete):
        size_kb = os.path.getsize(f) / 1024
        print(f"  {os.path.basename(f)} ({size_kb:.1f} KB)")

    # Confirm unless --force
    if not args.force:
        confirm = input("\nDelete these files? [y/N]: ")
        if confirm.lower() != "y":
            print("Cancelled.")
            return 0

    # Delete files
    deleted = 0
    for f in files_to_delete:
        try:
            os.remove(f)
            deleted += 1
        except Exception as e:
            logger.error("DELETE_FAILED", f"file={f} error={e}")

    print(f"\nDeleted {deleted} files.")
    return 0


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

    # Snapshot callback with optional enrichment + JSON stdout for API consumption
    snapshot_count = [0]

    def on_snapshot(snapshot):
        if enricher is not None:
            enricher.enrich(snapshot)

        # Emit flattened JSON to stdout so ObservationController can parse it
        snapshot_count[0] += 1
        try:
            flat = {
                "timestamp_ms": snapshot.timestamp_ms,
                "binance_price": snapshot.binance_direct.price if snapshot.binance_direct else None,
                "chainlink_price": snapshot.chainlink_rpc.price if snapshot.chainlink_rpc else None,
                "lag_ms": (
                    snapshot.binance_direct.timestamp_ms - snapshot.chainlink_rpc.timestamp_ms
                    if snapshot.binance_direct and snapshot.chainlink_rpc
                    else None
                ),
                "divergence_pct": (
                    (snapshot.binance_direct.price - snapshot.chainlink_rpc.price)
                    / snapshot.chainlink_rpc.price
                    * 100
                    if snapshot.binance_direct
                    and snapshot.chainlink_rpc
                    and snapshot.chainlink_rpc.price
                    else None
                ),
                "model_prob_up": snapshot.model_prob_up,
                "model_confidence": snapshot.model_confidence,
                "edge_after_fees": snapshot.edge_after_fees,
                "signal_detected": snapshot.signal_detected,
                "signal_confidence": snapshot.signal_confidence,
                "candle_open_price": snapshot.candle_open_price,
                "time_remaining_sec": snapshot.time_remaining_sec,
            }
            # Only emit every 10th snapshot to avoid flooding stdout
            if snapshot_count[0] % 10 == 0:
                import json as _json

                print(_json.dumps(flat), flush=True)
        except Exception:
            pass  # Don't let serialization errors crash the capture loop

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
  analyse   Analyse captured observation data
  reset     Clear old observation files

Examples:
  arb-capture init                     # First-time setup
  arb-capture observe --duration 3600  # 1-hour observation
  arb-capture analyse                  # Analyse most recent capture
  arb-capture reset                    # Clear old output files
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

    # analyse
    analyse_parser = subparsers.add_parser("analyse", help="Analyse captured observation data")
    analyse_parser.add_argument(
        "--input",
        type=str,
        default=OBSERVATIONS_DIR,
        help=f"Input directory (default: {OBSERVATIONS_DIR})",
    )
    analyse_parser.add_argument(
        "--file",
        type=str,
        default=None,
        help="Specific parquet file to analyse (default: most recent)",
    )

    # reset
    reset_parser = subparsers.add_parser("reset", help="Clear old observation files")
    reset_parser.add_argument(
        "--dir",
        type=str,
        default=OBSERVATIONS_DIR,
        help=f"Directory to clear (default: {OBSERVATIONS_DIR})",
    )
    reset_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip confirmation prompt",
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
    elif args.command == "analyse":
        return cmd_analyse(args)
    elif args.command == "reset":
        return cmd_reset(args)

    return 1


if __name__ == "__main__":
    sys.exit(main())
