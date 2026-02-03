"""
Polymarket Arbitrage Bot - Main Entry Point

Orchestrates market discovery, real-time data feeds, and strategy execution.

Strategy: Lag Arbitrage
- Simple mode: Momentum-first trigger from Binance spot price vs candle open
- Enhanced mode: When P() model available, signals enriched with probability estimates
"""

import os
import signal
import threading
import time

from engine import ModelBridge, SignalEvaluator
from engine.config import EngineConfig, SignalEvaluatorConfig
from engine.types import MarketContext, UnifiedSignal

from trading.config import BotConfig, build_config
from trading.data.binance_ws import BinanceWebSocket
from trading.data.polymarket_ws import PolymarketWebSocket
from trading.data.price_tracker import DirectionSignal, PriceTracker
from trading.execution.orders import OrderExecutor
from trading.execution.position import PositionManager
from trading.execution.risk import RiskManager
from trading.market.discovery import (
    ASSET_TO_BINANCE_SYMBOL,
    fetch_recent_updown_markets,
)
from trading.market.state import MarketState, MarketStateManager, MarketStatus
from trading.strategy.lag_arb import LagArbStrategy
from trading.strategy.signals import ArbOpportunity
from trading.utils.logging import get_logger, setup_logging
from trading.utils.metrics import BotMetrics, remove_pid, write_pid

logger = get_logger("main")


class ArbBot:
    """Main arbitrage bot orchestrator"""

    def __init__(self, config: BotConfig):
        self.config = config
        self.metrics = BotMetrics()
        self.running = False

        # Components
        self.state_manager: MarketStateManager | None = None
        self.executor: OrderExecutor | None = None
        self.position_manager = PositionManager()
        self.risk_manager = RiskManager(config.risk)

        # WebSocket clients
        self.polymarket_ws: PolymarketWebSocket | None = None
        self.binance_ws: BinanceWebSocket | None = None

        # Price tracker for lag arb
        self.price_tracker: PriceTracker | None = None

        # Market refresh thread
        self._refresh_thread: threading.Thread | None = None

        # Strategy (always lag_arb)
        self.strategy: LagArbStrategy | None = None

        # Engine components (optional model integration)
        self.model_bridge: ModelBridge | None = None
        self.signal_evaluator: SignalEvaluator | None = None

        # P&L snapshot interval tracking
        self._last_pnl_snapshot = 0.0

    def _print_banner(self):
        """Print startup banner"""
        cfg = self.config
        print("=" * 60)
        print("Polymarket Arbitrage Bot - Lag Arb Strategy")
        print("=" * 60)
        print(f"  Mode:            {'DRY RUN' if cfg.trading.dry_run else 'LIVE'}")
        print(f"  Min gross:       ${cfg.trading.min_spread} ({cfg.trading.min_spread * 100:.1f}%)")
        print(
            f"  Min net profit:  ${cfg.trading.min_net_profit} ({cfg.trading.min_net_profit * 100:.2f}%)"
        )
        print(f"  Max position:    ${cfg.trading.max_position_size}")
        print(f"  Market refresh:  {cfg.polling.market_refresh_interval}s")
        print("  Binance feed:    enabled (candle-based)")
        print(f"  Candle interval: {cfg.lag_arb.candle_interval}")
        print(f"  Move threshold:  {cfg.lag_arb.spot_move_threshold_pct * 100:.2f}% from open")
        print(f"  Fee rate:        {cfg.lag_arb.fee_rate * 100:.1f}%")
        if self.model_bridge and self.model_bridge.is_loaded:
            print("  P() model:       LOADED (enhanced mode)")
        else:
            print("  P() model:       not loaded (simple mode)")
        print("=" * 60)

    def initialize(self):
        """Initialize bot components"""
        logger.info("INIT_START", "Initializing bot components")

        # Initialize executor
        self.executor = OrderExecutor(
            self.config.trading,
            self.config.private_key,
            self.config.funder_address,
        )

        # Discover recent markets
        logger.info(
            "DISCOVER",
            f"interval={self.config.lag_arb.candle_interval} assets={self.config.filters.assets}",
        )
        self.state_manager = fetch_recent_updown_markets(
            max_age_hours=self.config.filters.max_market_age_hours,
            fallback_age_hours=self.config.filters.fallback_age_hours,
            min_volume_24h=self.config.filters.min_volume_24h,
            assets=self.config.filters.assets,
            max_markets=self.config.polling.max_markets,
            candle_interval=self.config.lag_arb.candle_interval,
        )

        logger.info("MARKETS_LOADED", f"count={len(self.state_manager.markets)}")

        # Initialize lag arb strategy (always)
        self._init_lag_arb()

        # Connect Polymarket WebSocket (always enabled)
        self._init_polymarket_ws()

        # Start market refresh thread
        if self.config.polling.market_refresh_interval > 0:
            self._start_market_refresh_thread()

        self.metrics.start()

        # Write PID file for API server
        if write_pid():
            logger.info("PID_WRITTEN", f"pid={os.getpid()}")
        else:
            logger.warning("PID_WRITE_FAILED", "Could not write PID file")

        logger.info("INIT_COMPLETE", "Bot initialized")

    def _init_lag_arb(self):
        """Initialize lag arbitrage strategy with Binance feed"""
        # Create lag arb strategy with event callback
        self.strategy = LagArbStrategy(
            self.config.trading,
            self.config.lag_arb,
            on_event=self._on_strategy_event,
        )

        # Initialize engine components (optional model integration)
        try:
            surface_path = self.config.engine.surface_path if self.config.engine.surface_path else None
            min_edge = self.config.engine.min_edge_threshold if self.config.engine.min_edge_threshold else 0.03

            self.model_bridge = ModelBridge(
                surface_path=surface_path,
                fee_rate=self.config.lag_arb.fee_rate,
                min_edge=min_edge,
            )

            signal_config = SignalEvaluatorConfig(
                momentum_trigger_threshold_pct=self.config.lag_arb.momentum_trigger_threshold_pct,
                max_combined_price=self.config.lag_arb.max_combined_price,
                expected_lag_ms=self.config.lag_arb.expected_lag_ms,
                max_lag_window_ms=self.config.lag_arb.max_lag_window_ms,
            )

            self.signal_evaluator = SignalEvaluator(
                model_bridge=self.model_bridge,
                config=signal_config,
            )

            if self.model_bridge and self.model_bridge.is_loaded:
                logger.info("ENGINE_INITIALIZED", "model_loaded=true")
            else:
                logger.info("ENGINE_INITIALIZED", "model_loaded=false (will work without model)")
        except Exception as e:
            logger.warning("ENGINE_INIT_FAILED", f"error={e} (continuing without model)")

        # Build Binance symbols from config assets
        assets = self.config.filters.assets
        binance_symbols = [
            ASSET_TO_BINANCE_SYMBOL[a] for a in assets if a in ASSET_TO_BINANCE_SYMBOL
        ]
        logger.info("BINANCE_SYMBOLS", f"tracking={len(binance_symbols)} symbols")

        # Create price tracker with config assets
        self.price_tracker = PriceTracker(
            self.config.lag_arb,
            on_signal=self._on_direction_signal,
            assets=assets,
        )

        # Fetch initial candle data from Binance Klines API
        logger.info("CANDLES", "Fetching candle open prices from Binance...")
        self.price_tracker.initialize()

        # Connect to Binance WebSocket for real-time trades
        self.binance_ws = BinanceWebSocket(
            symbols=binance_symbols,
            on_trade=self.price_tracker.on_trade,
            reconnect_delay=5.0,
        )
        self.binance_ws.connect()

        # Wait for connection
        timeout = 10.0
        start = time.time()
        while not self.binance_ws.is_connected and (time.time() - start) < timeout:
            time.sleep(0.1)

        if self.binance_ws.is_connected:
            logger.info("BINANCE_READY", "Binance WebSocket connected")
        else:
            logger.warning("BINANCE_TIMEOUT", "Binance WebSocket connection timeout")

        logger.info("STRATEGY", "Lag arbitrage strategy initialized (candle-based)")

    def _init_polymarket_ws(self):
        """Initialize Polymarket WebSocket"""
        self.polymarket_ws = PolymarketWebSocket(
            self.config.websocket,
            self.state_manager,
            on_update=self._on_market_update,
        )
        self.polymarket_ws.connect()

        # Wait for connection
        timeout = 10.0
        start = time.time()
        while not self.polymarket_ws.is_connected and (time.time() - start) < timeout:
            time.sleep(0.1)

        if self.polymarket_ws.is_connected:
            logger.info("POLYMARKET_WS_READY", "Polymarket WebSocket connected")
        else:
            logger.warning("POLYMARKET_WS_TIMEOUT", "Polymarket WebSocket connection timeout")

    def _start_market_refresh_thread(self):
        """Start background thread to refresh markets periodically"""
        self._refresh_thread = threading.Thread(
            target=self._market_refresh_loop,
            daemon=True,
            name="market-refresh",
        )
        self._refresh_thread.start()
        logger.info(
            "REFRESH_THREAD",
            f"Started with interval={self.config.polling.market_refresh_interval}s",
        )

    def _market_refresh_loop(self):
        """Periodically check for new markets"""
        interval = self.config.polling.market_refresh_interval
        while self.running:
            time.sleep(interval)
            if not self.running:
                break
            try:
                self._refresh_markets()
            except Exception as e:
                logger.error("MARKET_REFRESH_ERROR", str(e))

    def _refresh_markets(self, force: bool = False):
        """Fetch new markets and update subscriptions.

        Args:
            force: If True, clear all markets and resubscribe from scratch.
        """
        # Remove expired/resolved markets first
        removed_count = self._remove_stale_markets()
        if removed_count > 0:
            logger.info("MARKETS_REMOVED", f"count={removed_count}")

        new_manager = fetch_recent_updown_markets(
            max_age_hours=self.config.filters.max_market_age_hours,
            fallback_age_hours=self.config.filters.fallback_age_hours,
            min_volume_24h=self.config.filters.min_volume_24h,
            market_types=self.config.filters.market_types,
            max_markets=self.config.polling.max_markets,
            candle_interval=self.config.lag_arb.candle_interval,
        )

        # Force refresh: clear everything and resubscribe
        if force:
            old_count = len(self.state_manager.markets)
            # Clear all existing markets
            for market_id in list(self.state_manager.markets.keys()):
                self.state_manager.remove_market(market_id)
            logger.info("FORCE_REFRESH", f"cleared={old_count} markets")

        # Find new markets not in current state
        new_tokens = []
        for market_id, market in new_manager.markets.items():
            if market_id not in self.state_manager.markets:
                self.state_manager.add_market(market)
                new_tokens.extend([market.up_token_id, market.down_token_id])
                logger.info("NEW_MARKET", f"slug={market.slug}")

        # Subscribe to new tokens
        if new_tokens and self.polymarket_ws:
            self.polymarket_ws.add_tokens(new_tokens)
            logger.info("SUBSCRIBED_NEW", f"tokens={len(new_tokens)}")

    def _remove_stale_markets(self) -> int:
        """Remove markets that are resolved or past their resolution time.

        Returns the count of removed markets.
        """
        from datetime import datetime

        now = datetime.now()
        to_remove = []

        for market_id, market in self.state_manager.markets.items():
            # Skip if we have an open position
            if self.position_manager and self.position_manager.has_position(market_id):
                continue

            # Remove if resolved
            if market.status == MarketStatus.RESOLVED:
                to_remove.append((market_id, "resolved"))
                continue

            # Remove if past resolution time (with 60s buffer)
            if market.resolution_time and now > market.resolution_time:
                to_remove.append((market_id, "expired"))
                continue

        for market_id, reason in to_remove:
            market = self.state_manager.get_market(market_id)
            if market:
                logger.info("MARKET_REMOVED", f"slug={market.slug} reason={reason}")
            self.state_manager.remove_market(market_id)

        return len(to_remove)

    def force_refresh_markets(self):
        """Public method to force refresh all markets. Called from API."""
        logger.info("FORCE_REFRESH_REQUESTED", "Refreshing all markets...")
        self._refresh_markets(force=True)

    def _on_direction_signal(self, signal: DirectionSignal):
        """
        Handle direction signal from Binance price tracker.

        Triggered when spot price crosses significantly above/below candle open,
        indicating which side should win at resolution.
        """
        if not self.running:
            return

        if not isinstance(self.strategy, LagArbStrategy):
            return

        # Get unified signals from engine (if available)
        unified_signals = []
        self._current_model_output = None
        if self.signal_evaluator and self.state_manager:
            # Build market context for each valid market
            for market in self.state_manager.get_valid_markets():
                market_ctx = self._build_market_context(market)
                if market_ctx:
                    signals = self.signal_evaluator.evaluate(
                        momentum=signal.momentum,
                        deviation_pct=signal.move_from_open,
                        spot_price=signal.current_price,
                        candle_open=signal.candle_open,
                        market=market_ctx,
                        symbol=signal.symbol,
                        time_remaining_sec=int(market.time_to_resolution or 0),
                    )
                    unified_signals.extend(signals)

            # Get model output from best signal if available
            if unified_signals:
                best_signal = unified_signals[0]
                self._current_model_output = best_signal.model

        # Record signal for dashboard visibility using unified event stream
        if signal.is_significant:
            details = {
                "direction": signal.direction.value,
                "momentum": signal.momentum,
                "spot_price": signal.current_price,
                "candle_open": signal.candle_open,
                "expected_winner": signal.expected_winner,
                "confidence": signal.confidence,
            }
            # Add engine signal data when available
            if unified_signals:
                best = unified_signals[0]
                details["signal_tier"] = best.tier.name
                details["engine_edge"] = best.expected_edge
                details["engine_confidence"] = best.confidence
                if best.model:
                    details["model_prob_up"] = best.model.prob_up
                    details["model_edge"] = best.model.edge_after_fees
                    details["kelly_fraction"] = best.model.kelly_fraction
                    details["model_reliable"] = best.model.is_reliable
            self.metrics.record_event("DIRECTION", signal.symbol, details)

        # Forward signal to lag arb strategy (opens lag window)
        self.strategy.on_direction_signal(signal)

        # Check all markets for lag arb opportunities
        if signal.is_significant:
            self._check_lag_arb_opportunities()

    def _on_strategy_event(self, event_type: str, symbol: str, details: dict):
        """Handle events emitted by the strategy (LAG_WINDOW_OPEN, LAG_WINDOW_EXPIRED, ENTRY_SKIP)"""
        self.metrics.record_event(event_type, symbol, details)

    def _check_lag_arb_opportunities(self):
        """Check all markets for lag arb entry opportunities"""
        model_output = getattr(self, "_current_model_output", None)
        for market in self.state_manager.get_valid_markets():
            if self.position_manager.has_position(market.market_id):
                continue

            entry_signal = self.strategy.check_entry(market, model_output=model_output)
            if entry_signal and entry_signal.opportunity:
                self._execute_entry(entry_signal.opportunity)

    def _on_market_update(self, market_id: str):
        """Callback when market is updated via Polymarket WebSocket"""
        if not self.running:
            return

        market = self.state_manager.get_market(market_id)
        if not market or not market.is_valid:
            return

        model_output = getattr(self, "_current_model_output", None)

        # Check entry signal if no position
        if not self.position_manager.has_position(market_id):
            signal = self.strategy.check_entry(market, model_output=model_output)
            if signal and signal.opportunity:
                self._execute_entry(signal.opportunity)
                return

        # Check exit signal if has position
        else:
            position = self.position_manager.get_position(market_id)
            if position:
                exit_signal = self.strategy.check_exit(
                    market,
                    position.up_entry_price,
                    position.down_entry_price,
                    position.entry_time,
                    position,  # Pass position for partial exit tracking
                    model_output=model_output,
                )
                if exit_signal:
                    self._execute_exit(
                        market,
                        position,
                        exit_signal.exit_reason.value,
                        exit_signal.exit_side,  # Pass exit_side for partial exits
                    )

    def _execute_entry(self, opp: ArbOpportunity):
        """Execute entry trade"""
        # Check risk limits
        can_trade, reason = self.risk_manager.check_can_trade()
        if not can_trade:
            logger.warning("BLOCKED", f"reason={reason}")
            self.metrics.record_event(
                "BLOCKED",
                opp.slug,
                {"reason": reason, "market_id": opp.market_id},
            )
            return

        can_expose, reason = self.risk_manager.check_exposure_limit(
            self.position_manager,
            self.config.trading.max_position_size,
        )
        if not can_expose:
            logger.warning("EXPOSURE_LIMIT", f"reason={reason}")
            self.metrics.record_event(
                "BLOCKED",
                opp.slug,
                {"reason": f"exposure_limit: {reason}", "market_id": opp.market_id},
            )
            return

        # Kelly-based position sizing when model data available
        base_size = self.config.trading.max_position_size
        kelly = opp.metadata.get("kelly_fraction")
        if kelly:
            # Cap Kelly at 25% of max, floor at 10% of max
            kelly_capped = max(0.1, min(kelly, 0.25))
            position_size = base_size * kelly_capped
        else:
            position_size = base_size  # Fallback: full size (current behavior)

        # Execute
        up_result, down_result = self.executor.execute_arb_entry(
            opp,
            position_size,
        )

        if up_result.success and down_result.success:
            self.position_manager.open_position(
                opp.market_id,
                opp.slug,
                up_result.filled_size,
                opp.up_price,
                down_result.filled_size,
                opp.down_price,
            )
            self.metrics.record_opportunity(taken=True)
            logger.info(
                "POSITION_OPENED",
                f"market={opp.slug} cost=${opp.total_cost:.4f} net_profit=${opp.net_profit:.4f}",
            )
            entry_details = {
                "market_id": opp.market_id,
                "cost": opp.total_cost,
                "expected_profit": opp.net_profit,
                "up_price": opp.up_price,
                "down_price": opp.down_price,
                "position_size": position_size,
            }
            # Attach model metadata from opportunity
            if opp.metadata.get("kelly_fraction"):
                entry_details["kelly_fraction"] = opp.metadata["kelly_fraction"]
                entry_details["model_prob_up"] = opp.metadata.get("model_prob_up")
                entry_details["model_edge"] = opp.metadata.get("model_edge")
                entry_details["model_reliable"] = opp.metadata.get("model_reliable")
            self.metrics.record_event("POSITION_OPENED", opp.slug, entry_details)
        else:
            self.metrics.record_opportunity(taken=False)
            logger.warning("ENTRY_FAILED", f"market={opp.slug}")
            self.metrics.record_event(
                "ENTRY_FAILED",
                opp.slug,
                {
                    "market_id": opp.market_id,
                    "up_success": up_result.success,
                    "down_success": down_result.success,
                },
            )

    def _execute_exit(
        self, market: MarketState, position, reason: str, exit_side: str | None = None
    ):
        """Execute exit trade (full or partial)"""
        # Partial exit: sell only one side
        if exit_side:
            if exit_side == "up":
                result = self.executor.execute_partial_exit(
                    market.up_token_id,
                    market.up_best_bid,
                    position.up_shares,
                    "up",
                )
                if result.success:
                    pos, pnl = self.position_manager.partial_exit_position(
                        market.market_id,
                        "up",
                        market.up_best_bid,
                    )
                    logger.info(
                        "PARTIAL_EXIT_UP",
                        f"market={market.slug} pnl=${pnl:.4f} reason={reason}",
                    )
                    self.metrics.record_event(
                        "PARTIAL_EXIT",
                        market.slug,
                        {
                            "market_id": market.market_id,
                            "side": "up",
                            "pnl": pnl,
                            "reason": reason,
                        },
                    )
            else:
                result = self.executor.execute_partial_exit(
                    market.down_token_id,
                    market.down_best_bid,
                    position.down_shares,
                    "down",
                )
                if result.success:
                    pos, pnl = self.position_manager.partial_exit_position(
                        market.market_id,
                        "down",
                        market.down_best_bid,
                    )
                    logger.info(
                        "PARTIAL_EXIT_DOWN",
                        f"market={market.slug} pnl=${pnl:.4f} reason={reason}",
                    )
                    self.metrics.record_event(
                        "PARTIAL_EXIT",
                        market.slug,
                        {
                            "market_id": market.market_id,
                            "side": "down",
                            "pnl": pnl,
                            "reason": reason,
                        },
                    )
            return

        # Full exit: sell both sides
        up_result, down_result = self.executor.execute_arb_exit(
            market.up_token_id,
            market.down_token_id,
            market.up_best_bid,
            market.down_best_bid,
            position.up_shares,
        )

        if up_result.success and down_result.success:
            closed = self.position_manager.close_position(
                market.market_id,
                market.up_best_bid,
                market.down_best_bid,
                reason,
            )
            if closed:
                pnl = closed.realized_pnl
                hold_duration = closed.hold_duration_seconds or 0.0
                self.risk_manager.record_trade_result(pnl)
                self.metrics.record_trade(success=True, pnl=pnl)
                logger.info(
                    "POSITION_CLOSED",
                    f"market={market.slug} pnl=${pnl:.4f} reason={reason}",
                )
                # Record to unified event stream
                self.metrics.record_event(
                    "POSITION_CLOSED",
                    market.slug,
                    {
                        "market_id": market.market_id,
                        "pnl": pnl,
                        "exit_reason": reason,
                        "hold_duration_sec": hold_duration,
                    },
                )
                # Record to trades history for bar chart
                self.metrics.record_closed_trade(
                    market_slug=market.slug,
                    pnl=pnl,
                    exit_reason=reason,
                    hold_duration_sec=hold_duration,
                )

    def _get_dashboard_data(self) -> dict:
        """Collect data for dashboard visibility"""
        # Active markets
        active_markets = []
        if self.state_manager:
            for market in self.state_manager.markets.values():
                active_markets.append(
                    {
                        "slug": market.slug,
                        "market_id": market.market_id,
                        "combined_ask": market.combined_ask,
                        "combined_bid": market.combined_bid,
                        "up_best_ask": market.up_best_ask,
                        "up_best_bid": market.up_best_bid,
                        "down_best_ask": market.down_best_ask,
                        "down_best_bid": market.down_best_bid,
                        "is_valid": market.is_valid,
                        "last_updated": market.last_update.isoformat()
                        if market.last_update
                        else None,
                    }
                )

        # Active lag windows
        active_windows = []
        if isinstance(self.strategy, LagArbStrategy):
            for window in self.strategy.get_active_windows():
                active_windows.append(
                    {
                        "symbol": window.symbol,
                        "expected_winner": window.expected_winner,
                        "direction": window.direction.value,
                        "start_time": window.start_time.isoformat(),
                        "remaining_ms": window.remaining_ms,
                        "entry_made": window.entry_made,
                        "momentum": window.signal.momentum,
                        "spot_price": window.signal.current_price,
                        "candle_open": window.signal.candle_open,
                    }
                )

        # Config summary for dashboard
        config_summary = {
            "strategy": "lag_arb",
            "dry_run": self.config.trading.dry_run,
            "model_loaded": self.model_bridge.is_loaded if self.model_bridge else False,
            "market_types": self.config.filters.market_types,
            "assets": self.config.filters.assets,
            "momentum_threshold": self.config.lag_arb.momentum_trigger_threshold_pct,
            "max_lag_window_ms": self.config.lag_arb.max_lag_window_ms,
            "max_combined_price": self.config.lag_arb.max_combined_price,
        }

        # Spot prices with history for sparklines
        spot_prices = {}
        if self.binance_ws:
            for symbol in self.binance_ws.symbols:
                spot_prices[symbol] = {
                    "price": self.binance_ws.get_price(symbol),
                    "history": self.binance_ws.get_price_history(symbol),
                }
                # Add candle info if available from price tracker
                if self.price_tracker:
                    tracker = self.price_tracker.trackers.get(symbol)
                    if tracker:
                        spot_prices[symbol]["candle_open"] = (
                            tracker.candle.open_price if tracker.candle else None
                        )
                        spot_prices[symbol]["momentum"] = tracker.get_momentum()

        return {
            "active_markets": active_markets,
            "active_windows": active_windows,
            "config_summary": config_summary,
            "spot_prices": spot_prices,
        }

    def run(self):
        """Main run loop"""
        self._print_banner()
        self.initialize()
        self.running = True

        # Setup signal handlers
        def handle_shutdown(signum, frame):
            logger.info("SHUTDOWN", "Received shutdown signal")
            self.running = False

        def handle_refresh(signum, frame):
            logger.info("REFRESH_SIGNAL", "Received SIGUSR1, refreshing markets...")
            self.force_refresh_markets()

        signal.signal(signal.SIGINT, handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)
        signal.signal(signal.SIGUSR1, handle_refresh)

        try:
            # WebSocket mode: events trigger trades
            logger.info("MODE", "Running in WebSocket mode")
            while self.running:
                time.sleep(1)

                # Record P&L snapshot every 10 seconds
                current_time = time.time()
                if current_time - self._last_pnl_snapshot >= 10.0:
                    self.metrics.record_pnl_snapshot()
                    self._last_pnl_snapshot = current_time

                # Export metrics to file for API server (with dashboard visibility data)
                dashboard_data = self._get_dashboard_data()
                self.metrics.export_to_file(
                    active_markets=dashboard_data["active_markets"],
                    active_windows=dashboard_data["active_windows"],
                    config_summary=dashboard_data["config_summary"],
                    spot_prices=dashboard_data["spot_prices"],
                )

                # For lag arb, also check for expired windows and exits
                if isinstance(self.strategy, LagArbStrategy):
                    self._check_position_exits()

        finally:
            self.shutdown()

    def _check_position_exits(self):
        """Check all positions for exit conditions"""
        model_output = getattr(self, "_current_model_output", None)
        for position in self.position_manager.get_open_positions():
            market = self.state_manager.get_market(position.market_id)
            if not market or not market.is_valid:
                continue

            exit_signal = self.strategy.check_exit(
                market,
                position.up_entry_price,
                position.down_entry_price,
                position.entry_time,
                position,  # Pass position for partial exit tracking
                model_output=model_output,
            )
            if exit_signal:
                self._execute_exit(
                    market,
                    position,
                    exit_signal.exit_reason.value,
                    exit_signal.exit_side,  # Pass exit_side for partial exits
                )

    def _build_market_context(self, market: MarketState) -> MarketContext | None:
        """Build MarketContext from MarketState for engine evaluation."""
        if not market:
            return None

        try:
            time_remaining = market.time_to_resolution
            time_remaining_sec = int(time_remaining) if time_remaining is not None else 0

            return MarketContext(
                timestamp_ms=int(time.time() * 1000),
                up_price=market.up_best_ask or 0.5,
                down_price=market.down_best_ask or 0.5,
                up_bid=market.up_best_bid or 0.49,
                down_bid=market.down_best_bid or 0.49,
                combined_ask=market.combined_ask,
                combined_bid=market.combined_bid,
                time_remaining_sec=time_remaining_sec,
                session=self._get_trading_session(),
            )
        except Exception:
            return None

    def _get_trading_session(self) -> str:
        """Get current trading session based on UTC hour."""
        from datetime import datetime, timezone

        hour = datetime.now(timezone.utc).hour
        if 0 <= hour < 8:
            return "asia"
        elif 8 <= hour < 16:
            return "europe"
        else:
            return "america"

    def shutdown(self):
        """Clean shutdown"""
        self.running = False

        # Remove PID file
        remove_pid()

        if self.polymarket_ws:
            self.polymarket_ws.disconnect()

        if self.binance_ws:
            self.binance_ws.disconnect()

        # Print final stats
        print("\n" + "=" * 60)
        print("Session Summary")
        print("=" * 60)
        summary = self.metrics.summary()
        for key, value in summary.items():
            print(f"  {key}: {value}")
        print("=" * 60)

        logger.info("SHUTDOWN_COMPLETE", "Bot stopped")


def main():
    config = build_config()
    setup_logging(config.verbose)

    bot = ArbBot(config)
    bot.run()


if __name__ == "__main__":
    main()
