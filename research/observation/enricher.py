"""
Snapshot Enricher for Observation Mode

Adds model predictions, edge calculations, and signal detections to
synchronized snapshots during live data capture.
"""

from pathlib import Path

from engine.streams.base import SynchronizedSnapshot
from trading.utils.logging import get_logger

logger = get_logger("enricher")

# 15-minute window in milliseconds
WINDOW_MS = 15 * 60 * 1000


def get_session_from_hour(hour: int) -> str:
    """
    Get trading session from UTC hour.

    Sessions (from feature_extractor convention):
    - asia: 00:00-08:00 UTC
    - europe: 08:00-13:00 UTC
    - us_eu_overlap: 13:00-17:00 UTC
    - us: 17:00-21:00 UTC
    - late_us: 21:00-24:00 UTC
    """
    if 0 <= hour < 8:
        return "asia"
    elif 8 <= hour < 13:
        return "europe"
    elif 13 <= hour < 17:
        return "us_eu_overlap"
    elif 17 <= hour < 21:
        return "us"
    else:
        return "late_us"


class SnapshotEnricher:
    """
    Enriches snapshots with model predictions and signal detections.

    Tracks 15-minute candle windows and calculates:
    - P(UP) from probability surface
    - Edge after fees
    - Signal detections from all detectors

    Usage:
        enricher = SnapshotEnricher("research/models/surface.json")
        enricher.enrich(snapshot)  # Modifies snapshot in-place
    """

    def __init__(
        self,
        surface_path: str | None = None,
        fee_rate: float = 0.03,  # 3% for 15m markets
    ):
        """
        Args:
            surface_path: Path to saved ProbabilitySurface JSON
            fee_rate: Trading fee rate (0.03 = 3%)
        """
        self.surface = None
        self.edge_calc = None
        self.arbiter = None
        self.fee_rate = fee_rate

        # Candle tracking
        self.candle_open_price: float | None = None
        self.candle_start_ms: int | None = None

        # Load models if path provided
        if surface_path and Path(surface_path).exists():
            self._load_models(surface_path)
        else:
            logger.warning("ENRICHER_NO_MODEL", f"path={surface_path}")

    def _load_models(self, surface_path: str) -> None:
        """Load probability surface and initialize calculators."""
        try:
            from research.models.edge_calculator import EdgeCalculator
            from research.models.probability_surface import ProbabilitySurface
            from research.signals.detectors import SignalArbiter

            self.surface = ProbabilitySurface.load(surface_path)
            self.edge_calc = EdgeCalculator(
                self.surface,
                fee_rate=self.fee_rate,
                min_edge_threshold=0.03,  # Lower threshold for observation
                require_reliable=False,  # Allow all buckets for data collection
            )
            self.arbiter = SignalArbiter()

            logger.info("ENRICHER_LOADED", f"surface={surface_path}")

        except Exception as e:
            logger.error("ENRICHER_LOAD_ERROR", str(e))
            self.surface = None
            self.edge_calc = None
            self.arbiter = None

    def _get_window_start_ms(self, timestamp_ms: int) -> int:
        """Get the start timestamp of the current 15-minute window."""
        return (timestamp_ms // WINDOW_MS) * WINDOW_MS

    def _update_candle_tracking(self, snapshot: SynchronizedSnapshot) -> None:
        """Update candle open tracking for new windows."""
        window_start = self._get_window_start_ms(snapshot.timestamp_ms)

        # Check if we've entered a new window
        if self.candle_start_ms is None or window_start > self.candle_start_ms:
            # New window - capture the open price
            binance_price = snapshot.binance_price
            if binance_price is not None:
                self.candle_open_price = binance_price
                self.candle_start_ms = window_start
                logger.info(
                    "CANDLE_NEW",
                    f"open=${binance_price:.2f} window_start={window_start}",
                )

    def _get_time_remaining_sec(self, timestamp_ms: int) -> int:
        """Calculate seconds remaining in current 15-minute window."""
        window_start = self._get_window_start_ms(timestamp_ms)
        window_end = window_start + WINDOW_MS
        remaining_ms = max(0, window_end - timestamp_ms)
        return remaining_ms // 1000

    def _get_clob_prices(self, snapshot: SynchronizedSnapshot) -> tuple[float | None, float | None]:
        """
        Extract UP and DOWN prices from CLOB books.

        Returns (up_price, down_price) or (None, None) if not available.
        """
        if not snapshot.clob_books:
            return None, None

        # We need to identify UP and DOWN tokens
        # Convention: UP token should have higher price when Binance is up from open
        # For now, take first two tokens and assume order
        # TODO: Better token identification based on market metadata

        books = list(snapshot.clob_books.values())
        if len(books) < 2:
            return None, None

        # Use best ask as executable price (what we'd pay to buy)
        price1 = books[0].best_ask if books[0].best_ask > 0 else None
        price2 = books[1].best_ask if books[1].best_ask > 0 else None

        return price1, price2

    def enrich(self, snapshot: SynchronizedSnapshot) -> None:
        """
        Enrich a snapshot with model predictions and signals.

        Modifies the snapshot in-place by setting observation fields:
        - model_prob_up
        - model_confidence
        - edge_after_fees
        - signal_detected
        - signal_confidence
        - candle_open_price
        - time_remaining_sec
        """
        # Update candle tracking
        self._update_candle_tracking(snapshot)

        # Always set candle info
        snapshot.candle_open_price = self.candle_open_price
        snapshot.time_remaining_sec = self._get_time_remaining_sec(snapshot.timestamp_ms)

        # Early exit if no model loaded
        if self.surface is None or self.edge_calc is None:
            return

        # Need Binance price for deviation calculation
        binance_price = snapshot.binance_price
        if binance_price is None or self.candle_open_price is None:
            return

        # Calculate deviation from candle open
        deviation_pct = (binance_price - self.candle_open_price) / self.candle_open_price

        # Convert time remaining to minutes for model
        time_remaining_min = max(1, snapshot.time_remaining_sec // 60)

        # Get model probability
        try:
            prob_up, ci_lower, ci_upper, is_reliable = self.surface.get_probability(
                deviation_pct=deviation_pct,
                time_remaining=time_remaining_min,
                vol_regime="all",
                session=get_session_from_hour((snapshot.timestamp_ms // 1000 // 3600) % 24),
            )
            snapshot.model_prob_up = prob_up

            # Get CLOB prices for edge calculation
            up_price, down_price = self._get_clob_prices(snapshot)

            if up_price is not None and down_price is not None:
                # Calculate edge
                opp = self.edge_calc.calculate_edge(
                    deviation_pct=deviation_pct,
                    time_remaining=time_remaining_min,
                    market_price_up=up_price,
                    market_price_down=down_price,
                    vol_regime="all",
                )
                snapshot.model_confidence = opp.confidence_score
                snapshot.edge_after_fees = opp.edge_after_fees

                # Detect signals if arbiter available
                if self.arbiter is not None:
                    chainlink_price = snapshot.chainlink_price
                    signals = self.arbiter.evaluate_all(
                        up_executable_price=up_price,
                        down_executable_price=down_price,
                        binance_price=binance_price,
                        chainlink_price=chainlink_price,
                        open_price=self.candle_open_price,
                        deviation_pct=deviation_pct,
                        timestamp_ms=snapshot.timestamp_ms,
                        time_remaining_sec=snapshot.time_remaining_sec,
                        model_prob_up=prob_up,
                    )

                    if signals:
                        best = self.arbiter.get_best_signal(signals)
                        if best:
                            snapshot.signal_detected = best.signal_type.value
                            snapshot.signal_confidence = best.confidence
                            logger.info(
                                "SIGNAL_DETECTED",
                                f"type={best.signal_type.value} confidence={best.confidence:.2f} "
                                f"edge={snapshot.edge_after_fees:.4f if snapshot.edge_after_fees else 'N/A'} "
                                f"direction={best.direction.value if best.direction else 'N/A'} "
                                f"time_remaining={snapshot.time_remaining_sec}s",
                            )

        except Exception as e:
            logger.debug("ENRICH_ERROR", str(e))

    def reset_candle(self) -> None:
        """Force reset candle tracking (e.g., at window boundaries)."""
        self.candle_open_price = None
        self.candle_start_ms = None
