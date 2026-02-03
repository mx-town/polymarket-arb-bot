"""
Stream synchronizer for aligning multiple price feeds.

Collects updates from all sources and produces synchronized snapshots
at configurable intervals.
"""

import threading
import time
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass

from engine.streams.base import (
    OrderBookUpdate,
    PriceUpdate,
    StreamSource,
    StreamStats,
    SynchronizedSnapshot,
)
from trading.utils.logging import get_logger

logger = get_logger("synchronizer")


@dataclass
class SynchronizerConfig:
    """Configuration for stream synchronizer."""

    snapshot_interval_ms: int = 100  # 100ms between snapshots
    ring_buffer_size: int = 10000  # ~10 seconds at 1000 updates/sec
    max_stale_ms: int = 5000  # Consider data stale after 5 seconds


class StreamSynchronizer:
    """
    Synchronizes multiple price streams into aligned snapshots.

    Thread-safe collection of updates from all sources with
    periodic snapshot generation.
    """

    def __init__(
        self,
        config: SynchronizerConfig | None = None,
        on_snapshot: Callable[[SynchronizedSnapshot], None] | None = None,
    ):
        """
        Args:
            config: Synchronizer configuration
            on_snapshot: Callback for each synchronized snapshot
        """
        self.config = config or SynchronizerConfig()
        self.on_snapshot = on_snapshot

        # Thread safety
        self._lock = threading.Lock()

        # Latest updates by source
        self._latest_prices: dict[StreamSource, PriceUpdate] = {}
        self._clob_books: dict[str, OrderBookUpdate] = {}

        # Ring buffer for snapshots
        self._snapshots: deque[SynchronizedSnapshot] = deque(maxlen=self.config.ring_buffer_size)

        # Statistics per stream
        self._stats: dict[StreamSource, StreamStats] = {
            source: StreamStats(source=source) for source in StreamSource
        }
        self._clob_update_count = 0

        # Snapshot generation
        self._snapshot_thread: threading.Thread | None = None
        self._running = False

    def start(self) -> None:
        """Start snapshot generation."""
        if self._running:
            return

        self._running = True
        self._snapshot_thread = threading.Thread(target=self._snapshot_loop, daemon=True)
        self._snapshot_thread.start()
        logger.info("STARTED", f"interval={self.config.snapshot_interval_ms}ms")

    def stop(self) -> None:
        """Stop snapshot generation."""
        self._running = False
        logger.info("STOPPED", "Synchronizer stopped")

    def _snapshot_loop(self) -> None:
        """Generate snapshots at fixed intervals."""
        interval_sec = self.config.snapshot_interval_ms / 1000.0

        while self._running:
            try:
                snapshot = self._create_snapshot()
                with self._lock:
                    self._snapshots.append(snapshot)

                if self.on_snapshot:
                    self.on_snapshot(snapshot)

            except Exception as e:
                logger.error("SNAPSHOT_ERROR", str(e))

            time.sleep(interval_sec)

    def _create_snapshot(self) -> SynchronizedSnapshot:
        """Create a synchronized snapshot from latest data."""
        timestamp_ms = int(time.time() * 1000)

        with self._lock:
            snapshot = SynchronizedSnapshot(
                timestamp_ms=timestamp_ms,
                binance_direct=self._latest_prices.get(StreamSource.BINANCE_DIRECT),
                rtds_binance=self._latest_prices.get(StreamSource.RTDS_BINANCE),
                rtds_chainlink=self._latest_prices.get(StreamSource.RTDS_CHAINLINK),
                chainlink_rpc=self._latest_prices.get(StreamSource.CHAINLINK_RPC),
                clob_books=dict(self._clob_books),
            )

        return snapshot

    def on_price_update(self, update: PriceUpdate) -> None:
        """
        Handle incoming price update.

        Thread-safe callback for stream clients.
        """
        with self._lock:
            self._latest_prices[update.source] = update
            self._stats[update.source].record(update)

    def on_clob_update(self, update: OrderBookUpdate) -> None:
        """
        Handle incoming CLOB order book update.

        Thread-safe callback for CLOB adapter.
        """
        with self._lock:
            self._clob_books[update.token_id] = update
            self._clob_update_count += 1

    def get_snapshots(self) -> list[SynchronizedSnapshot]:
        """Get all snapshots in the ring buffer."""
        with self._lock:
            return list(self._snapshots)

    def get_latest_snapshot(self) -> SynchronizedSnapshot | None:
        """Get the most recent snapshot."""
        with self._lock:
            return self._snapshots[-1] if self._snapshots else None

    def get_stats(self) -> dict[StreamSource, StreamStats]:
        """Get statistics for all streams."""
        with self._lock:
            return dict(self._stats)

    def get_clob_update_count(self) -> int:
        """Get total CLOB update count."""
        with self._lock:
            return self._clob_update_count

    def reset_stats(self) -> None:
        """Reset all statistics."""
        with self._lock:
            self._stats = {source: StreamStats(source=source) for source in StreamSource}
            self._clob_update_count = 0
            self._snapshots.clear()

    def get_lag_stats(self) -> dict:
        """
        Calculate lag statistics from collected snapshots.

        Returns:
            Dict with p50, p95, p99 lag metrics.
        """
        with self._lock:
            snapshots = list(self._snapshots)

        if not snapshots:
            return {"p50": None, "p95": None, "p99": None, "count": 0}

        lags = []
        for snap in snapshots:
            lag = snap.lag_binance_to_chainlink_ms
            if lag is not None:
                lags.append(lag)

        if not lags:
            return {"p50": None, "p95": None, "p99": None, "count": 0}

        lags.sort()
        n = len(lags)

        return {
            "p50": lags[int(n * 0.50)],
            "p95": lags[int(n * 0.95)] if n >= 20 else None,
            "p99": lags[int(n * 0.99)] if n >= 100 else None,
            "count": n,
            "min": lags[0],
            "max": lags[-1],
        }

    def export_to_parquet(self, path: str) -> int:
        """
        Export snapshots to Parquet file.

        Args:
            path: Output file path

        Returns:
            Number of snapshots exported
        """
        import pandas as pd

        with self._lock:
            snapshots = list(self._snapshots)

        if not snapshots:
            logger.warning("EXPORT_EMPTY", "No snapshots to export")
            return 0

        # Convert to records
        records = []
        for snap in snapshots:
            record = {
                "timestamp_ms": snap.timestamp_ms,
                "binance_direct_price": snap.binance_direct.price if snap.binance_direct else None,
                "binance_direct_ts": snap.binance_direct.timestamp_ms
                if snap.binance_direct
                else None,
                "rtds_binance_price": snap.rtds_binance.price if snap.rtds_binance else None,
                "rtds_binance_ts": snap.rtds_binance.timestamp_ms if snap.rtds_binance else None,
                "rtds_chainlink_price": snap.rtds_chainlink.price if snap.rtds_chainlink else None,
                "rtds_chainlink_ts": snap.rtds_chainlink.timestamp_ms
                if snap.rtds_chainlink
                else None,
                "chainlink_rpc_price": snap.chainlink_rpc.price if snap.chainlink_rpc else None,
                "chainlink_rpc_ts": snap.chainlink_rpc.timestamp_ms if snap.chainlink_rpc else None,
                "lag_ms": snap.lag_binance_to_chainlink_ms,
                "divergence_pct": snap.price_divergence_pct,
            }

            # Add CLOB books as flattened columns
            for token_id, book in snap.clob_books.items():
                short_id = token_id[:8]  # Truncate for column names
                record[f"clob_{short_id}_bid"] = book.best_bid
                record[f"clob_{short_id}_ask"] = book.best_ask

            # Add observation mode columns if present
            record["model_prob_up"] = snap.model_prob_up
            record["model_confidence"] = snap.model_confidence
            record["edge_after_fees"] = snap.edge_after_fees
            record["signal_detected"] = snap.signal_detected
            record["signal_confidence"] = snap.signal_confidence
            record["candle_open_price"] = snap.candle_open_price
            record["time_remaining_sec"] = snap.time_remaining_sec

            records.append(record)

        df = pd.DataFrame(records)
        df.to_parquet(path, index=False)

        logger.info("EXPORTED", f"path={path} snapshots={len(records)}")
        return len(records)
