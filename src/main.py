"""
Polymarket Arbitrage Bot - Main Entry Point

Orchestrates market discovery, real-time data feeds, and strategy execution.

Strategies:
- conservative: Buy both sides when combined < $0.99, hold to resolution
- lag_arb: Predict Polymarket lag using Binance spot momentum
"""

import time
import signal
import sys
from typing import Optional, Union

from src.config import build_config, BotConfig
from src.utils.logging import setup_logging, get_logger
from src.utils.metrics import BotMetrics
from src.market.discovery import fetch_updown_markets, fetch_all_markets
from src.market.state import MarketStateManager, MarketState
from src.market.filters import get_tradeable_markets
from src.strategy.signals import ArbOpportunity, SignalDetector
from src.strategy.conservative import ConservativeStrategy, scan_for_opportunities
from src.strategy.lag_arb import LagArbStrategy
from src.execution.orders import OrderExecutor
from src.execution.position import PositionManager
from src.execution.risk import RiskManager
from src.data.polymarket_ws import PolymarketWebSocket
from src.data.binance_ws import BinanceWebSocket
from src.data.price_tracker import PriceTracker, MomentumSignal

logger = get_logger("main")


class ArbBot:
    """Main arbitrage bot orchestrator"""

    def __init__(self, config: BotConfig):
        self.config = config
        self.metrics = BotMetrics()
        self.running = False

        # Components
        self.state_manager: Optional[MarketStateManager] = None
        self.executor: Optional[OrderExecutor] = None
        self.position_manager = PositionManager()
        self.risk_manager = RiskManager(config.risk)

        # WebSocket clients
        self.polymarket_ws: Optional[PolymarketWebSocket] = None
        self.binance_ws: Optional[BinanceWebSocket] = None

        # Price tracker for lag arb
        self.price_tracker: Optional[PriceTracker] = None

        # Strategy (set based on config)
        self.strategy: Optional[Union[ConservativeStrategy, LagArbStrategy]] = None

    def _print_banner(self):
        """Print startup banner"""
        cfg = self.config
        print("=" * 60)
        print("Polymarket Arbitrage Bot")
        print("=" * 60)
        print(f"  Mode:            {'DRY RUN' if cfg.trading.dry_run else 'LIVE'}")
        print(f"  Strategy:        {cfg.strategy}")
        print(f"  Min gross:       ${cfg.trading.min_spread} ({cfg.trading.min_spread*100:.1f}%)")
        print(f"  Min net profit:  ${cfg.trading.min_net_profit} ({cfg.trading.min_net_profit*100:.2f}%)")
        print(f"  Max position:    ${cfg.trading.max_position_size}")
        print(f"  WebSocket:       {'enabled' if cfg.websocket.enabled else 'disabled'}")
        print(f"  Binance feed:    {'enabled' if cfg.lag_arb.enabled else 'disabled'}")
        print(f"  Poll interval:   {cfg.polling.interval}s")
        print(f"  Est. fee rate:   {cfg.trading.fee_rate*100:.1f}%")
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

        # Discover markets
        if self.config.filters.market_types:
            logger.info("DISCOVER", f"Filtering for: {self.config.filters.market_types}")
            self.state_manager = fetch_updown_markets(
                max_markets=self.config.polling.max_markets,
                market_types=self.config.filters.market_types,
            )
        else:
            # Fetch all binary markets for polling mode
            raw_markets = fetch_all_markets(max_markets=self.config.polling.max_markets)
            self.state_manager = MarketStateManager()
            for m in raw_markets:
                state = MarketState(
                    market_id=m["condition_id"],
                    slug=m.get("slug", ""),
                    question=m["question"],
                    up_token_id=m["yes_token"],
                    down_token_id=m["no_token"],
                )
                self.state_manager.add_market(state)

        logger.info("MARKETS_LOADED", f"count={len(self.state_manager.markets)}")

        # Initialize strategy
        if self.config.strategy == "lag_arb":
            self._init_lag_arb()
        else:
            self._init_conservative()

        # Connect Polymarket WebSocket if enabled
        if self.config.websocket.enabled:
            self._init_polymarket_ws()

        self.metrics.start()
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
            on_signal=self._on_momentum_signal,
        )

        # Connect to Binance
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

        logger.info("STRATEGY", "Lag arbitrage strategy initialized")

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

    def _on_momentum_signal(self, signal: MomentumSignal):
        """Handle momentum signal from Binance price tracker"""
        if not self.running:
            return

        if not isinstance(self.strategy, LagArbStrategy):
            return

        # Forward signal to lag arb strategy
        self.strategy.on_momentum_signal(signal)

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

    def run_polling_cycle(self):
        """Run one polling-mode scan cycle"""
        self.metrics.cycles += 1
        cycle_start = time.time()

        logger.info("CYCLE_START", f"cycle={self.metrics.cycles}")

        # Fetch fresh order books
        token_ids = self.state_manager.get_all_token_ids()
        book_map = self.executor.get_order_books_batch(token_ids)

        # Update state from books
        for token_id, book in book_map.items():
            bids = book.get("bids", [])
            asks = book.get("asks", [])

            if bids and asks:
                best_bid = float(bids[0].price) if hasattr(bids[0], "price") else float(bids[0][0])
                best_ask = float(asks[0].price) if hasattr(asks[0], "price") else float(asks[0][0])
                bid_size = float(bids[0].size) if hasattr(bids[0], "size") else float(bids[0][1]) if len(bids[0]) > 1 else 0
                ask_size = float(asks[0].size) if hasattr(asks[0], "size") else float(asks[0][1]) if len(asks[0]) > 1 else 0

                self.state_manager.update_from_book(token_id, best_bid, best_ask, bid_size, ask_size)

        self.metrics.markets_scanned = len(self.state_manager.markets)

        # Scan for opportunities based on strategy
        tradeable = get_tradeable_markets(
            self.state_manager,
            self.config.filters,
            self.config.conservative.min_time_to_resolution_sec,
        )

        if isinstance(self.strategy, ConservativeStrategy):
            opportunities = scan_for_opportunities(
                tradeable,
                self.config.trading,
                self.config.conservative,
            )
        else:
            # Lag arb: check each market with strategy
            opportunities = []
            for market in tradeable:
                signal = self.strategy.check_entry(market)
                if signal and signal.opportunity:
                    opportunities.append(signal.opportunity)

        # Execute opportunities
        for opp in opportunities:
            if not self.position_manager.has_position(opp.market_id):
                self._execute_entry(opp)

        cycle_time = time.time() - cycle_start
        self.metrics.cycle_complete()

        if opportunities:
            logger.info("CYCLE_COMPLETE", f"opps={len(opportunities)} time={cycle_time:.1f}s")
        else:
            logger.info(
                "CYCLE_COMPLETE",
                f"no_opps (need >{self.config.trading.min_spread*100:.1f}% gross) time={cycle_time:.1f}s",
            )

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
            if self.config.websocket.enabled:
                # WebSocket mode: events trigger trades
                logger.info("MODE", "Running in WebSocket mode")
                while self.running:
                    time.sleep(1)

                    # For lag arb, also check for expired windows and exits
                    if isinstance(self.strategy, LagArbStrategy):
                        self._check_position_exits()
            else:
                # Polling mode: periodic scans
                logger.info("MODE", "Running in polling mode")
                while self.running:
                    self.run_polling_cycle()
                    logger.info("WAIT", f"Next scan in {self.config.polling.interval}s")
                    time.sleep(self.config.polling.interval)

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
