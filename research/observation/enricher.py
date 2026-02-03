"""
Snapshot Enricher for Observation Mode

Adds model predictions, edge calculations, and signal detections to
synchronized snapshots during live data capture.

Uses the shared engine pipeline (ModelBridge + SignalEvaluator) for
consistent signal evaluation between trading and research.
"""

from pathlib import Path

from engine.config import SignalEvaluatorConfig
from engine.model_bridge import ModelBridge
from engine.signal_evaluator import SignalEvaluator
from engine.streams.base import SynchronizedSnapshot
from engine.types import MarketContext
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

    Uses engine.ModelBridge and engine.SignalEvaluator for consistent
    signal evaluation with the trading bot.

    Tracks 15-minute candle windows and calculates:
    - P(UP) from probability surface
    - Edge after fees
    - Signal detections from all tiers

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
        self.model_bridge: ModelBridge | None = None
        self.signal_evaluator: SignalEvaluator | None = None
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
        """Load engine components (ModelBridge + SignalEvaluator)."""
        try:
            self.model_bridge = ModelBridge(
                surface_path=surface_path,
                fee_rate=self.fee_rate,
                min_edge=0.03,  # Lower threshold for observation
                require_reliable=False,  # Allow all buckets for data collection
            )

            self.signal_evaluator = SignalEvaluator(
                model_bridge=self.model_bridge,
                config=SignalEvaluatorConfig(),
            )

            logger.info("ENRICHER_LOADED", f"surface={surface_path}")

        except Exception as e:
            logger.error("ENRICHER_LOAD_ERROR", str(e))
            self.model_bridge = None
            self.signal_evaluator = None

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

    def _get_clob_prices(
        self, snapshot: SynchronizedSnapshot
    ) -> tuple[float | None, float | None, float | None, float | None]:
        """
        Extract UP and DOWN prices from CLOB books.

        Returns (up_ask, down_ask, up_bid, down_bid) or (None, None, None, None).
        """
        if not snapshot.clob_books:
            return None, None, None, None

        books = list(snapshot.clob_books.values())
        if len(books) < 2:
            return None, None, None, None

        up_ask = books[0].best_ask if books[0].best_ask > 0 else None
        down_ask = books[1].best_ask if books[1].best_ask > 0 else None
        up_bid = books[0].best_bid if books[0].best_bid > 0 else None
        down_bid = books[1].best_bid if books[1].best_bid > 0 else None

        return up_ask, down_ask, up_bid, down_bid

    def enrich(self, snapshot: SynchronizedSnapshot) -> None:
        """
        Enrich a snapshot with model predictions and signals.

        Uses engine.SignalEvaluator.evaluate() for the same signal pipeline
        as the trading bot.

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

        # Early exit if no engine loaded
        if self.model_bridge is None or self.signal_evaluator is None:
            return

        # Need Binance price for deviation calculation
        binance_price = snapshot.binance_price
        if binance_price is None or self.candle_open_price is None:
            return

        # Calculate deviation from candle open
        deviation_pct = (binance_price - self.candle_open_price) / self.candle_open_price

        # Calculate momentum (use deviation as proxy in observation mode)
        momentum = deviation_pct

        # Get CLOB prices
        up_ask, down_ask, up_bid, down_bid = self._get_clob_prices(snapshot)

        time_remaining = snapshot.time_remaining_sec or 0
        session = get_session_from_hour((snapshot.timestamp_ms // 1000 // 3600) % 24)

        # Build MarketContext if CLOB data available
        market_ctx = None
        if up_ask is not None and down_ask is not None:
            market_ctx = MarketContext(
                timestamp_ms=snapshot.timestamp_ms,
                up_price=up_ask,
                down_price=down_ask,
                up_bid=up_bid or (up_ask - 0.01),
                down_bid=down_bid or (down_ask - 0.01),
                combined_ask=up_ask + down_ask,
                combined_bid=(up_bid or 0) + (down_bid or 0),
                time_remaining_sec=time_remaining,
                session=session,
            )

        try:
            # Use engine signal evaluator (same path as trading bot)
            signals = self.signal_evaluator.evaluate(
                momentum=momentum,
                deviation_pct=deviation_pct,
                spot_price=binance_price,
                candle_open=self.candle_open_price,
                market=market_ctx,
                symbol="BTCUSDT",  # Default for observation
                time_remaining_sec=time_remaining,
            )

            # Map back to snapshot enrichment fields
            if signals:
                best = signals[0]
                snapshot.signal_detected = best.tier.name
                snapshot.signal_confidence = best.confidence
                snapshot.edge_after_fees = best.expected_edge
                if best.model:
                    snapshot.model_prob_up = best.model.prob_up
                    snapshot.model_confidence = best.model.confidence_score
                    logger.info(
                        "SIGNAL_DETECTED",
                        f"tier={best.tier.name} confidence={best.confidence:.2f} "
                        f"edge={best.expected_edge:.4f} "
                        f"direction={best.direction.value} "
                        f"model_prob_up={best.model.prob_up:.3f} "
                        f"time_remaining={time_remaining}s",
                    )
                else:
                    logger.info(
                        "SIGNAL_DETECTED",
                        f"tier={best.tier.name} confidence={best.confidence:.2f} "
                        f"edge={best.expected_edge:.4f} "
                        f"direction={best.direction.value} "
                        f"time_remaining={time_remaining}s",
                    )
            elif self.model_bridge.is_loaded and market_ctx:
                # No signal but model loaded - still get model output for enrichment
                model_output = self.model_bridge.evaluate(
                    deviation_pct=deviation_pct,
                    time_remaining_sec=time_remaining,
                    spot_price=binance_price,
                    candle_open=self.candle_open_price,
                    market_price_up=up_ask,
                    market_price_down=down_ask,
                )
                if model_output:
                    snapshot.model_prob_up = model_output.prob_up
                    snapshot.model_confidence = model_output.confidence_score
                    snapshot.edge_after_fees = model_output.edge_after_fees

        except Exception as e:
            logger.debug("ENRICH_ERROR", str(e))

    def reset_candle(self) -> None:
        """Force reset candle tracking (e.g., at window boundaries)."""
        self.candle_open_price = None
        self.candle_start_ms = None
