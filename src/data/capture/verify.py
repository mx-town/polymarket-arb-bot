"""
5-minute verification script for data capture infrastructure.

Connects all 5 streams, runs for 5 minutes, and reports status.
"""

import time
from dataclasses import dataclass

from src.data.capture.synchronizer import StreamSynchronizer, SynchronizerConfig
from src.data.streams.base import StreamSource
from src.data.streams.binance_direct import BinanceDirectStream
from src.data.streams.chainlink_rpc import ChainlinkRPCPoller
from src.data.streams.clob_adapter import SimpleCLOBStream
from src.data.streams.rtds import RTDSStream
from src.market.discovery import fetch_markets_by_series
from src.utils.logging import get_logger, setup_logging

logger = get_logger("verify")


@dataclass
class VerificationResult:
    """Result of stream verification."""

    source: str
    passed: bool
    update_count: int
    message: str


def verify_streams(duration_sec: int = 300) -> list[VerificationResult]:
    """
    Run verification of all data streams.

    Args:
        duration_sec: How long to run (default 5 minutes)

    Returns:
        List of verification results
    """
    logger.info("VERIFY_START", f"duration={duration_sec}s")

    # Set up synchronizer
    config = SynchronizerConfig(snapshot_interval_ms=100)
    sync = StreamSynchronizer(config=config)

    # Connect streams
    binance_stream = BinanceDirectStream(on_update=sync.on_price_update)
    rtds_stream = RTDSStream(
        on_binance_update=sync.on_price_update,
        on_chainlink_update=sync.on_price_update,
    )
    chainlink_poller = ChainlinkRPCPoller(on_update=sync.on_price_update)

    # Discover 15m BTC markets for CLOB using series_id (most reliable)
    token_ids = []
    try:
        markets = fetch_markets_by_series(asset="bitcoin", candle_interval="15m", max_markets=5)
        for m in markets:
            token_ids.append(m["yes_token"])
            token_ids.append(m["no_token"])
        logger.info("MARKETS_FOUND", f"count={len(markets)} tokens={len(token_ids)}")
    except Exception as e:
        logger.warning("MARKET_DISCOVERY_FAILED", str(e))

    clob_stream = (
        SimpleCLOBStream(token_ids=token_ids, on_update=sync.on_clob_update) if token_ids else None
    )

    # Start everything
    logger.info("STARTING_STREAMS", "Connecting all streams...")
    sync.start()

    logger.info("CONNECT_BINANCE", "Connecting Binance Direct...")
    binance_stream.connect()

    logger.info("CONNECT_RTDS", "Connecting RTDS...")
    rtds_stream.connect()

    logger.info("CONNECT_CHAINLINK", "Connecting Chainlink RPC...")
    chainlink_poller.connect()

    if clob_stream:
        logger.info("CONNECT_CLOB", f"Connecting CLOB with {len(token_ids)} tokens...")
        clob_stream.connect()

    # Wait for streams to connect
    logger.info("WAITING", "Waiting 5s for connections...")
    time.sleep(5)

    # Log connection states
    logger.info(
        "CONNECTION_STATUS",
        f"binance={binance_stream.is_connected} rtds={rtds_stream.is_connected} "
        f"chainlink={chainlink_poller.is_connected} clob={clob_stream.is_connected if clob_stream else 'N/A'}",
    )

    # Run for duration
    start_time = time.time()
    while time.time() - start_time < duration_sec:
        elapsed = int(time.time() - start_time)
        stats = sync.get_stats()

        # Progress update every 10 seconds for first minute, then every 30 seconds
        interval = 10 if elapsed < 60 else 30
        if elapsed % interval == 0 and elapsed > 0:
            counts = {s.name: stats[s].update_count for s in StreamSource}
            clob_count = sync.get_clob_update_count()
            logger.info("PROGRESS", f"elapsed={elapsed}s counts={counts} clob={clob_count}")

        time.sleep(1)

    # Stop everything
    sync.stop()
    binance_stream.disconnect()
    rtds_stream.disconnect()
    chainlink_poller.disconnect()
    if clob_stream:
        clob_stream.disconnect()

    # Collect results
    stats = sync.get_stats()
    clob_count = sync.get_clob_update_count()

    results = []

    # Binance Direct
    binance_stats = stats[StreamSource.BINANCE_DIRECT]
    results.append(
        VerificationResult(
            source="Binance Direct",
            passed=binance_stats.update_count > 100,
            update_count=binance_stats.update_count,
            message=f"{binance_stats.update_count} updates"
            if binance_stats.update_count > 100
            else f"FAILED - only {binance_stats.update_count} updates",
        )
    )

    # RTDS Binance (optional - may be geo-blocked)
    rtds_binance_stats = stats[StreamSource.RTDS_BINANCE]
    rtds_binance_ok = rtds_binance_stats.update_count > 10
    results.append(
        VerificationResult(
            source="RTDS Binance",
            passed=rtds_binance_ok,
            update_count=rtds_binance_stats.update_count,
            message=f"{rtds_binance_stats.update_count} updates"
            if rtds_binance_ok
            else f"UNAVAILABLE - {rtds_binance_stats.update_count} updates (may be geo-blocked)",
        )
    )

    # RTDS Chainlink (optional - may be geo-blocked)
    rtds_chainlink_stats = stats[StreamSource.RTDS_CHAINLINK]
    rtds_chainlink_ok = rtds_chainlink_stats.update_count > 0
    results.append(
        VerificationResult(
            source="RTDS Chainlink",
            passed=rtds_chainlink_ok,
            update_count=rtds_chainlink_stats.update_count,
            message=f"{rtds_chainlink_stats.update_count} updates"
            if rtds_chainlink_ok
            else "UNAVAILABLE - may be geo-blocked",
        )
    )

    # Chainlink RPC (only emits on NEW rounds, ~60s heartbeat)
    chainlink_rpc_stats = stats[StreamSource.CHAINLINK_RPC]
    # Expect at least 1 update per 60 seconds (Chainlink heartbeat)
    min_expected = max(1, duration_sec // 60)
    chainlink_ok = chainlink_rpc_stats.update_count >= min_expected
    results.append(
        VerificationResult(
            source="Chainlink RPC",
            passed=chainlink_ok,
            update_count=chainlink_rpc_stats.update_count,
            message=f"{chainlink_rpc_stats.update_count} updates"
            if chainlink_ok
            else f"FAILED - only {chainlink_rpc_stats.update_count} updates (expected >={min_expected})",
        )
    )

    # CLOB
    if clob_stream:
        results.append(
            VerificationResult(
                source="CLOB",
                passed=clob_count > 10,
                update_count=clob_count,
                message=f"{clob_count} updates"
                if clob_count > 10
                else f"FAILED - only {clob_count} updates",
            )
        )
    else:
        results.append(
            VerificationResult(
                source="CLOB",
                passed=False,
                update_count=0,
                message="SKIPPED - no markets discovered",
            )
        )

    return results


def print_results(results: list[VerificationResult]) -> bool:
    """
    Print verification results.

    Returns:
        True if all passed, False otherwise
    """
    print("\n" + "=" * 60)
    print("VERIFICATION RESULTS")
    print("=" * 60)

    all_passed = True
    for r in results:
        status = "PASSED" if r.passed else "FAILED"
        print(f"[{status}] {r.source}: {r.message}")
        if not r.passed:
            all_passed = False

    print("=" * 60)
    if all_passed:
        print("VERIFICATION PASSED - All streams operational")
    else:
        print("VERIFICATION FAILED - Some streams not working")
    print("=" * 60 + "\n")

    return all_passed


def main():
    """Run verification."""
    setup_logging(verbose=True)
    results = verify_streams(duration_sec=300)
    success = print_results(results)
    return 0 if success else 1


if __name__ == "__main__":
    import sys

    sys.exit(main())
