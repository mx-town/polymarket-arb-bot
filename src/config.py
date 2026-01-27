"""
Configuration management for Polymarket Arbitrage Bot.

Merge order: YAML defaults → environment variables → CLI arguments
"""

import argparse
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# API endpoints
CLOB_HOST = "https://clob.polymarket.com"
GAMMA_HOST = "https://gamma-api.polymarket.com"
CHAIN_ID = 137  # Polygon

# Fee rates by candle interval (auto-adjusted in dashboard)
INTERVAL_FEE_RATES = {"1h": 0.0, "15m": 0.03, "5m": 0.03}
INTERVAL_MAX_COMBINED = {"1h": 0.995, "15m": 0.97, "5m": 0.97}


@dataclass
class TradingConfig:
    dry_run: bool = True
    min_spread: float = 0.02
    min_net_profit: float = 0.005
    max_position_size: float = 100.0
    fee_rate: float = 0.02


@dataclass
class PollingConfig:
    interval: float = 5.0
    batch_size: int = 50
    max_markets: int = 0
    market_refresh_interval: float = 300.0  # Refresh markets every 5 minutes


@dataclass
class WebSocketConfig:
    ping_interval: float = 30.0
    reconnect_delay: float = 5.0


@dataclass
class ConservativeConfig:
    max_combined_price: float = 0.99
    min_time_to_resolution_sec: int = 300
    exit_on_pump_threshold: float = 0.10


@dataclass
class LagArbConfig:
    enabled: bool = False
    spot_momentum_window_sec: float = 10.0  # Rolling window for momentum confirmation
    spot_move_threshold_pct: float = 0.002  # 0.2% from candle open = clear direction
    max_combined_price: float = 0.995  # Entry threshold (0% fees on 1H markets)
    expected_lag_ms: int = 2000  # Polymarket typically lags 2 seconds
    max_lag_window_ms: int = 5000  # Give up after 5 seconds
    candle_interval: str = "1h"  # Use 1H candles (0% fees)
    fee_rate: float = 0.0  # 1H markets have 0% fees
    # Momentum-based trigger parameters
    momentum_trigger_threshold_pct: float = 0.001  # 0.1% momentum = trigger signal
    pump_exit_threshold_pct: float = 0.03  # 3% single-side pump = exit
    max_hold_time_sec: int = 300  # 5 min max hold before force exit
    # Side-by-side exit (sell pumped side first)
    prioritize_pump_exit: bool = False  # Sell pumped side first, hold other
    secondary_exit_threshold_pct: float = 0.02  # Exit other side at +2%


@dataclass
class PureArbConfig:
    """Pure arbitrage: enter on price threshold only (no momentum required)"""

    enabled: bool = False
    max_combined_price: float = 0.99  # Entry when combined < this
    min_net_profit: float = 0.005  # Minimum profit after fees
    fee_rate: float = 0.02  # Assume standard fees unless on 1H


@dataclass
class RiskConfig:
    max_consecutive_losses: int = 3
    max_daily_loss_usd: float = 100.0
    cooldown_after_loss_sec: int = 300
    max_total_exposure: float = 1000.0


@dataclass
class FilterConfig:
    min_liquidity_usd: float = 1000.0
    min_book_depth: float = 500.0
    max_spread_pct: float = 0.05
    market_types: list = field(default_factory=lambda: ["btc-updown", "eth-updown"])
    max_market_age_hours: float = 1.0  # Prefer markets created within 1 hour
    fallback_age_hours: float = 24.0  # Fallback to 24h if no recent markets
    min_volume_24h: float = 100.0  # Minimum volume to ensure activity


@dataclass
class BotConfig:
    """Complete bot configuration"""

    trading: TradingConfig = field(default_factory=TradingConfig)
    polling: PollingConfig = field(default_factory=PollingConfig)
    websocket: WebSocketConfig = field(default_factory=WebSocketConfig)
    conservative: ConservativeConfig = field(default_factory=ConservativeConfig)
    lag_arb: LagArbConfig = field(default_factory=LagArbConfig)
    pure_arb: PureArbConfig = field(default_factory=PureArbConfig)
    risk: RiskConfig = field(default_factory=RiskConfig)
    filters: FilterConfig = field(default_factory=FilterConfig)
    verbose: bool = False
    strategy: str = "conservative"  # "conservative" or "lag_arb"

    # Credentials (from env only, never from YAML)
    private_key: str | None = field(default=None, repr=False)
    funder_address: str | None = field(default=None, repr=False)


def load_yaml_config(config_path: Path) -> dict:
    """Load configuration from YAML file"""
    if not config_path.exists():
        return {}
    with open(config_path) as f:
        return yaml.safe_load(f) or {}


def parse_args() -> argparse.Namespace:
    """Parse command line arguments"""
    parser = argparse.ArgumentParser(
        description="Polymarket Arbitrage Bot",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument(
        "--config", type=Path, default=Path("config/default.yaml"), help="Path to YAML config file"
    )
    parser.add_argument(
        "--live",
        dest="dry_run",
        action="store_false",
        help="Enable live trading (default: dry run)",
    )
    parser.add_argument(
        "--min-spread", type=float, default=None, help="Minimum gross profit per share"
    )
    parser.add_argument(
        "--min-net-profit", type=float, default=None, help="Minimum net profit after fees"
    )
    parser.add_argument("--max-position", type=float, default=None, help="Maximum USDC per trade")
    parser.add_argument("--interval", type=float, default=None, help="Seconds between market scans")
    parser.add_argument(
        "--max-markets", type=int, default=None, help="Max markets to scan (0 = all)"
    )
    parser.add_argument(
        "--batch-size", type=int, default=None, help="Order books to fetch per API call"
    )
    parser.add_argument(
        "--strategy",
        choices=["conservative", "lag_arb"],
        default=None,
        help="Trading strategy to use",
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="Show detailed progress")

    return parser.parse_args()


def build_config(args: argparse.Namespace | None = None) -> BotConfig:
    """
    Build configuration by merging:
    1. Defaults (from dataclass)
    2. YAML config file
    3. Environment variables
    4. CLI arguments
    """
    if args is None:
        args = parse_args()

    # Start with defaults
    config = BotConfig()

    # Load YAML if exists
    yaml_config = load_yaml_config(args.config)

    # Apply YAML values
    if "trading" in yaml_config:
        t = yaml_config["trading"]
        config.trading = TradingConfig(
            dry_run=t.get("dry_run", config.trading.dry_run),
            min_spread=t.get("min_spread", config.trading.min_spread),
            min_net_profit=t.get("min_net_profit", config.trading.min_net_profit),
            max_position_size=t.get("max_position_size", config.trading.max_position_size),
            fee_rate=t.get("fee_rate", config.trading.fee_rate),
        )

    if "polling" in yaml_config:
        p = yaml_config["polling"]
        config.polling = PollingConfig(
            interval=p.get("interval", config.polling.interval),
            batch_size=p.get("batch_size", config.polling.batch_size),
            max_markets=p.get("max_markets", config.polling.max_markets),
            market_refresh_interval=p.get(
                "market_refresh_interval", config.polling.market_refresh_interval
            ),
        )

    if "websocket" in yaml_config:
        w = yaml_config["websocket"]
        config.websocket = WebSocketConfig(
            ping_interval=w.get("ping_interval", config.websocket.ping_interval),
            reconnect_delay=w.get("reconnect_delay", config.websocket.reconnect_delay),
        )

    if "conservative" in yaml_config:
        c = yaml_config["conservative"]
        config.conservative = ConservativeConfig(
            max_combined_price=c.get("max_combined_price", config.conservative.max_combined_price),
            min_time_to_resolution_sec=c.get(
                "min_time_to_resolution_sec", config.conservative.min_time_to_resolution_sec
            ),
            exit_on_pump_threshold=c.get(
                "exit_on_pump_threshold", config.conservative.exit_on_pump_threshold
            ),
        )

    if "lag_arb" in yaml_config:
        la = yaml_config["lag_arb"]
        config.lag_arb = LagArbConfig(
            enabled=la.get("enabled", config.lag_arb.enabled),
            spot_momentum_window_sec=la.get(
                "spot_momentum_window_sec", config.lag_arb.spot_momentum_window_sec
            ),
            spot_move_threshold_pct=la.get(
                "spot_move_threshold_pct", config.lag_arb.spot_move_threshold_pct
            ),
            max_combined_price=la.get("max_combined_price", config.lag_arb.max_combined_price),
            expected_lag_ms=la.get("expected_lag_ms", config.lag_arb.expected_lag_ms),
            max_lag_window_ms=la.get("max_lag_window_ms", config.lag_arb.max_lag_window_ms),
            candle_interval=la.get("candle_interval", config.lag_arb.candle_interval),
            fee_rate=la.get("fee_rate", config.lag_arb.fee_rate),
            momentum_trigger_threshold_pct=la.get(
                "momentum_trigger_threshold_pct", config.lag_arb.momentum_trigger_threshold_pct
            ),
            pump_exit_threshold_pct=la.get(
                "pump_exit_threshold_pct", config.lag_arb.pump_exit_threshold_pct
            ),
            max_hold_time_sec=la.get("max_hold_time_sec", config.lag_arb.max_hold_time_sec),
            prioritize_pump_exit=la.get(
                "prioritize_pump_exit", config.lag_arb.prioritize_pump_exit
            ),
            secondary_exit_threshold_pct=la.get(
                "secondary_exit_threshold_pct", config.lag_arb.secondary_exit_threshold_pct
            ),
        )

    if "pure_arb" in yaml_config:
        pa = yaml_config["pure_arb"]
        config.pure_arb = PureArbConfig(
            enabled=pa.get("enabled", config.pure_arb.enabled),
            max_combined_price=pa.get("max_combined_price", config.pure_arb.max_combined_price),
            min_net_profit=pa.get("min_net_profit", config.pure_arb.min_net_profit),
            fee_rate=pa.get("fee_rate", config.pure_arb.fee_rate),
        )

    if "risk" in yaml_config:
        r = yaml_config["risk"]
        config.risk = RiskConfig(
            max_consecutive_losses=r.get(
                "max_consecutive_losses", config.risk.max_consecutive_losses
            ),
            max_daily_loss_usd=r.get("max_daily_loss_usd", config.risk.max_daily_loss_usd),
            cooldown_after_loss_sec=r.get(
                "cooldown_after_loss_sec", config.risk.cooldown_after_loss_sec
            ),
            max_total_exposure=r.get("max_total_exposure", config.risk.max_total_exposure),
        )

    if "filters" in yaml_config:
        f = yaml_config["filters"]
        config.filters = FilterConfig(
            min_liquidity_usd=f.get("min_liquidity_usd", config.filters.min_liquidity_usd),
            min_book_depth=f.get("min_book_depth", config.filters.min_book_depth),
            max_spread_pct=f.get("max_spread_pct", config.filters.max_spread_pct),
            market_types=f.get("market_types", config.filters.market_types),
            max_market_age_hours=f.get("max_market_age_hours", config.filters.max_market_age_hours),
            fallback_age_hours=f.get("fallback_age_hours", config.filters.fallback_age_hours),
            min_volume_24h=f.get("min_volume_24h", config.filters.min_volume_24h),
        )

    # Apply top-level YAML settings
    if "strategy" in yaml_config:
        config.strategy = yaml_config["strategy"]
        # Sync lag_arb.enabled with strategy choice
        if config.strategy == "lag_arb":
            config.lag_arb.enabled = True
    elif config.lag_arb.enabled:
        # Derive strategy from lag_arb.enabled if strategy not explicitly set
        config.strategy = "lag_arb"

    if "verbose" in yaml_config:
        config.verbose = yaml_config["verbose"]

    # Apply environment variables (override YAML)
    if os.getenv("MIN_SPREAD"):
        config.trading.min_spread = float(os.getenv("MIN_SPREAD"))
    if os.getenv("MAX_POSITION_SIZE"):
        config.trading.max_position_size = float(os.getenv("MAX_POSITION_SIZE"))
    if os.getenv("POLL_INTERVAL"):
        config.polling.interval = float(os.getenv("POLL_INTERVAL"))

    # Credentials from env only
    config.private_key = os.getenv("POLYMARKET_PRIVATE_KEY")
    config.funder_address = os.getenv("POLYMARKET_FUNDER_ADDRESS")

    # Apply CLI arguments (override everything)
    if hasattr(args, "dry_run") and not args.dry_run:
        config.trading.dry_run = False
    if args.min_spread is not None:
        config.trading.min_spread = args.min_spread
    if args.min_net_profit is not None:
        config.trading.min_net_profit = args.min_net_profit
    if args.max_position is not None:
        config.trading.max_position_size = args.max_position
    if args.interval is not None:
        config.polling.interval = args.interval
    if args.max_markets is not None:
        config.polling.max_markets = args.max_markets
    if args.batch_size is not None:
        config.polling.batch_size = args.batch_size
    if args.strategy is not None:
        config.strategy = args.strategy
        if args.strategy == "lag_arb":
            config.lag_arb.enabled = True
    if args.verbose:
        config.verbose = True

    return config
