"""
CLI entry point for data capture.

Usage:
    uv run arb-capture --verify          # 5-minute verification
    uv run arb-capture --duration 86400  # 24-hour capture
"""

import argparse
import os
import signal
import sys
import time
from datetime import datetime

from src.data.capture.synchronizer import StreamSynchronizer, SynchronizerConfig
from src.data.capture.verify import print_results, verify_streams
from src.data.streams.base import StreamSource
from src.data.streams.binance_direct import BinanceDirectStream
from src.data.streams.chainlink_rpc import ChainlinkRPCPoller
from src.data.streams.clob_adapter import SimpleCLOBStream
from src.data.streams.rtds import RTDSStream
from src.market.discovery import fetch_updown_events
from src.utils.logging import get_logger

logger = get_logger("capture_cli")


def run_capture(
    duration_sec: int,
    output_dir: str,
    snapshot_interval_ms: int = 100,
) -> int:
    """
    Run data capture for specified duration.

    Args:
        duration_sec: How long to capture (seconds)
        output_dir: Directory for output files
        snapshot_interval_ms: Interval between snapshots

    Returns:
        Exit code (0 for success)
    """
    # Ensure output directory exists
    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    parquet_path = os.path.join(output_dir, f"snapshots_{timestamp}.parquet")
    report_path = os.path.join(output_dir, f"lag_report_{timestamp}.txt")

    logger.info("CAPTURE_START", f"duration={duration_sec}s output={output_dir}")

    # Set up synchronizer
    config = SynchronizerConfig(
        snapshot_interval_ms=snapshot_interval_ms,
        ring_buffer_size=100000,  # Larger buffer for long captures
    )
    sync = StreamSynchronizer(config=config)

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
    export_interval = 3600  # Export every hour

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


def main():
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Data capture for lag measurement")
    parser.add_argument(
        "--verify",
        action="store_true",
        help="Run 5-minute verification",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=86400,
        help="Capture duration in seconds (default: 86400 = 24 hours)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="research/data/capture",
        help="Output directory (default: research/data/capture)",
    )
    parser.add_argument(
        "--interval",
        type=int,
        default=100,
        help="Snapshot interval in ms (default: 100)",
    )

    args = parser.parse_args()

    if args.verify:
        results = verify_streams(duration_sec=300)
        success = print_results(results)
        return 0 if success else 1

    return run_capture(
        duration_sec=args.duration,
        output_dir=args.output,
        snapshot_interval_ms=args.interval,
    )


if __name__ == "__main__":
    sys.exit(main())
