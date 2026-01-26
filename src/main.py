"""
Polymarket Arbitrage Bot - Main Entry Point

Orchestrates market discovery, real-time data feeds, and strategy execution.

Strategies:
- conservative: Buy both sides when combined < $0.99, hold to resolution
- lag_arb: Predict Polymarket lag using Binance spot momentum
"""

import os
import signal
import threading
import time

from src.config import BotConfig, build_config
from src.data.binance_ws import BinanceWebSocket
from src.data.polymarket_ws import PolymarketWebSocket
from src.data.price_tracker import DirectionSignal, PriceTracker
from src.execution.orders import OrderExecutor
from src.execution.position import PositionManager
from src.execution.risk import RiskManager
from src.market.discovery import (
    fetch_recent_updown_markets,
)
from src.market.state import MarketState, MarketStateManager
from src.strategy.conservative import ConservativeStrategy
from src.strategy.lag_arb import LagArbStrategy
from src.strategy.signals import ArbOpportunity
from src.utils.logging import get_logger, setup_logging
from src.utils.metrics import BotMetrics, remove_pid, write_pid

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

        # Strategy (set based on config)
        self.strategy: ConservativeStrategy | LagArbStrategy | None = None

        # Recent signals buffer for dashboard visibility (max 50)
        self._recent_signals: list = []
        self._max_signals = 50

    def _print_banner(self):
        """Print startup banner"""
        cfg = self.config
        print("=" * 60)
        print("Polymarket Arbitrage Bot")
        print("=" * 60)
        print(f"  Mode:            {'DRY RUN' if cfg.trading.dry_run else 'LIVE'}")
        print(f"  Strategy:        {cfg.strategy}")
        print(f"  Min gross:       ${cfg.trading.min_spread} ({cfg.trading.min_spread * 100:.1f}%)")
        print(
            f"  Min net profit:  ${cfg.trading.min_net_profit} ({cfg.trading.min_net_profit * 100:.2f}%)"
        )
        print(f"  Max position:    ${cfg.trading.max_position_size}")
        print(f"  Market refresh:  {cfg.polling.market_refresh_interval}s")
        if cfg.strategy == "lag_arb":
            print("  Binance feed:    enabled (candle-based)")
            print(f"  Candle interval: {cfg.lag_arb.candle_interval}")
            print(f"  Move threshold:  {cfg.lag_arb.spot_move_threshold_pct * 100:.2f}% from open")
            print(f"  Fee rate:        {cfg.lag_arb.fee_rate * 100:.1f}% (1H markets)")
        else:
            print(f"  Poll interval:   {cfg.polling.interval}s")
            print(f"  Est. fee rate:   {cfg.trading.fee_rate * 100:.1f}%")
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
        logger.info("DISCOVER", f"Filtering for: {self.config.filters.market_types}")
        self.state_manager = fetch_recent_updown_markets(
            max_age_hours=self.config.filters.max_market_age_hours,
            fallback_age_hours=self.config.filters.fallback_age_hours,
            min_volume_24h=self.config.filters.min_volume_24h,
            market_types=self.config.filters.market_types,
            max_markets=self.config.polling.max_markets,
        )

        logger.info("MARKETS_LOADED", f"count={len(self.state_manager.markets)}")

        # Initialize strategy
        if self.config.strategy == "lag_arb":
            self._init_lag_arb()
        else:
            self._init_conservative()

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

    def _init_conservative(self):
        """Initialize conservative strategy"""
        self.strategy = ConservativeStrategy(
            self.config.trading,
            self.config.conservative,
        )
        logger.info("STRATEGY", "Conservative strategy initialized")

    def _init_lag_arb(self):
        """Initialize lag arbitrage strategy with Binance feed"""
        # Create lag arb strategy
        self.strategy = LagArbStrategy(
            self.config.trading,
            self.config.lag_arb,
        )

        # Create price tracker
        self.price_tracker = PriceTracker(
            self.config.lag_arb,
            on_signal=self._on_direction_signal,
        )

        # Fetch initial candle data from Binance Klines API
        logger.info("CANDLES", "Fetching candle open prices from Binance...")
        self.price_tracker.initialize()

        # Connect to Binance WebSocket for real-time trades
        self.binance_ws = BinanceWebSocket(
            symbols=["BTCUSDT", "ETHUSDT"],
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

    def _refresh_markets(self):
        """Fetch new markets and update subscriptions"""
        new_manager = fetch_recent_updown_markets(
            max_age_hours=self.config.filters.max_market_age_hours,
            fallback_age_hours=self.config.filters.fallback_age_hours,
            min_volume_24h=self.config.filters.min_volume_24h,
            market_types=self.config.filters.market_types,
            max_markets=self.config.polling.max_markets,
        )

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

        # Record signal for dashboard visibility
        if signal.is_significant:
            self._record_signal(
                "DIRECTION",
                signal.symbol,
                {
                    "direction": signal.direction.value,
                    "momentum": signal.momentum,
                    "spot_price": signal.current_price,
                    "candle_open": signal.candle_open,
                    "expected_winner": signal.expected_winner,
                    "confidence": signal.confidence,
                },
            )

        # Forward signal to lag arb strategy (opens lag window)
        self.strategy.on_direction_signal(signal)

        # Check all markets for lag arb opportunities
        if signal.is_significant:
            self._check_lag_arb_opportunities()

    def _check_lag_arb_opportunities(self):
        """Check all markets for lag arb entry opportunities"""
        for market in self.state_manager.get_valid_markets():
            if self.position_manager.has_position(market.market_id):
                continue

            entry_signal = self.strategy.check_entry(market)
            if entry_signal and entry_signal.opportunity:
                self._execute_entry(entry_signal.opportunity)

    def _on_market_update(self, market_id: str):
        """Callback when market is updated via Polymarket WebSocket"""
        if not self.running:
            return

        market = self.state_manager.get_market(market_id)
        if not market or not market.is_valid:
            return

        # Check entry signal if no position
        if not self.position_manager.has_position(market_id):
            signal = self.strategy.check_entry(market)
            if signal and signal.opportunity:
                self._execute_entry(signal.opportunity)

        # Check exit signal if has position
        else:
            position = self.position_manager.get_position(market_id)
            if position:
                exit_signal = self.strategy.check_exit(
                    market,
                    position.up_entry_price,
                    position.down_entry_price,
                )
                if exit_signal:
                    self._execute_exit(market, position, exit_signal.exit_reason.value)

    def _execute_entry(self, opp: ArbOpportunity):
        """Execute entry trade"""
        # Check risk limits
        can_trade, reason = self.risk_manager.check_can_trade()
        if not can_trade:
            logger.warning("BLOCKED", f"reason={reason}")
            return

        can_expose, reason = self.risk_manager.check_exposure_limit(
            self.position_manager,
            self.config.trading.max_position_size,
        )
        if not can_expose:
            logger.warning("EXPOSURE_LIMIT", f"reason={reason}")
            return

        # Execute
        up_result, down_result = self.executor.execute_arb_entry(
            opp,
            self.config.trading.max_position_size,
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
        else:
            self.metrics.record_opportunity(taken=False)
            logger.warning("ENTRY_FAILED", f"market={opp.slug}")

    def _execute_exit(self, market: MarketState, position, reason: str):
        """Execute exit trade"""
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
                self.risk_manager.record_trade_result(pnl)
                self.metrics.record_trade(success=True, pnl=pnl)
                logger.info(
                    "POSITION_CLOSED",
                    f"market={market.slug} pnl=${pnl:.4f} reason={reason}",
                )

    def _record_signal(self, signal_type: str, symbol: str, details: dict):
        """Record a signal for dashboard visibility"""
        from datetime import datetime

        signal_entry = {
            "type": signal_type,
            "symbol": symbol,
            "timestamp": datetime.now().isoformat(),
            **details,
        }
        self._recent_signals.insert(0, signal_entry)
        # Keep only the most recent signals
        if len(self._recent_signals) > self._max_signals:
            self._recent_signals = self._recent_signals[: self._max_signals]

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
                        "last_updated": market.last_updated.isoformat()
                        if market.last_updated
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
            "strategy": self.config.strategy,
            "dry_run": self.config.trading.dry_run,
            "lag_arb_enabled": self.config.lag_arb.enabled,
            "market_types": self.config.filters.market_types,
            "momentum_threshold": self.config.lag_arb.momentum_trigger_threshold_pct,
            "max_lag_window_ms": self.config.lag_arb.max_lag_window_ms,
            "max_combined_price": self.config.lag_arb.max_combined_price,
        }

        return {
            "active_markets": active_markets,
            "active_windows": active_windows,
            "recent_signals": self._recent_signals,
            "config_summary": config_summary,
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

        signal.signal(signal.SIGINT, handle_shutdown)
        signal.signal(signal.SIGTERM, handle_shutdown)

        try:
            # WebSocket mode: events trigger trades
            logger.info("MODE", "Running in WebSocket mode")
            while self.running:
                time.sleep(1)

                # Export metrics to file for API server (with dashboard visibility data)
                dashboard_data = self._get_dashboard_data()
                self.metrics.export_to_file(
                    active_markets=dashboard_data["active_markets"],
                    active_windows=dashboard_data["active_windows"],
                    recent_signals=dashboard_data["recent_signals"],
                    config_summary=dashboard_data["config_summary"],
                )

                # For lag arb, also check for expired windows and exits
                if isinstance(self.strategy, LagArbStrategy):
                    self._check_position_exits()

        finally:
            self.shutdown()

    def _check_position_exits(self):
        """Check all positions for exit conditions"""
        for position in self.position_manager.get_open_positions():
            market = self.state_manager.get_market(position.market_id)
            if not market or not market.is_valid:
                continue

            exit_signal = self.strategy.check_exit(
                market,
                position.up_entry_price,
                position.down_entry_price,
            )
            if exit_signal:
                self._execute_exit(market, position, exit_signal.exit_reason.value)

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
