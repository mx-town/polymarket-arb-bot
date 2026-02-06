"""Late-entry bot for Polymarket 15m crypto Up/Down markets.

Polls for markets in the last 4 minutes before resolution,
buys the favorite side, exits on take-profit or before close.
"""

import logging
import sys
import time

import yaml
from dotenv import load_dotenv

from late_entry.data import get_active_markets, get_market_prices
from late_entry.executor import init_client, place_order
from late_entry.strategy import should_enter, should_exit

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-10s │ %(message)s",
    datefmt="%H:%M:%S",
)
# Silence noisy HTTP request logs from httpx/httpcore/urllib3
for noisy in ("httpx", "httpcore", "urllib3", "py_clob_client"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("bot")


def load_config(path: str = "config.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def main():
    load_dotenv()
    cfg = load_config()

    dry_run = cfg["trading"]["dry_run"]
    poll_interval = cfg["polling"]["interval_sec"]
    assets = cfg["assets"]
    le = cfg["late_entry"]

    # Merge trading + late_entry config for strategy functions
    strategy_cfg = {**le, "max_position_size": cfg["trading"]["max_position_size"]}

    mode = "DRY RUN" if dry_run else "LIVE"
    log.info("=" * 52)
    log.info(f"  Polymarket Late-Entry Bot v0.1.0  [{mode}]")
    log.info("=" * 52)
    log.info(f"  Assets          : {', '.join(assets)}")
    log.info(f"  Poll interval   : {poll_interval}s")
    log.info(f"  Max position    : ${cfg['trading']['max_position_size']} USDC")
    log.info(f"  Entry window    : last {le['entry_window_sec']}s ({le['entry_window_sec']//60}m)")
    log.info(f"  Exit buffer     : {le['exit_buffer_sec']}s before resolution")
    log.info(f"  Min spread      : {le['min_favorite_spread']:.0%}")
    log.info(f"  Max fav price   : {le['max_favorite_price']}")
    log.info(f"  Take profit     : {le['take_profit_pct']:.0%}")
    log.info("=" * 52)

    client = init_client(dry_run)
    positions: list[dict] = []

    while True:
        try:
            _tick(client, assets, positions, strategy_cfg, dry_run)
        except KeyboardInterrupt:
            log.info("SHUTDOWN user interrupt")
            sys.exit(0)
        except Exception as e:
            log.error(f"TICK_ERROR error={e}")

        time.sleep(poll_interval)


def _tick(client, assets, positions, cfg, dry_run):
    """Single polling tick: discover markets, check exits, check entries."""
    markets = get_active_markets(assets)

    if not markets:
        log.info("No active markets this tick")
        return

    # Check exits first
    closed = []
    for pos in positions:
        prices = get_market_prices(client, pos)
        if not prices:
            log.warning(f"  Could not fetch prices for position {pos['market_slug']}")
            continue

        signal = should_exit(pos, prices, cfg)
        if signal:
            result = place_order(
                client, pos["market_slug"], signal["token_id"],
                "sell", signal["price"], signal["size"], dry_run,
            )
            if result["success"]:
                pnl = (signal["price"] - pos["entry_price"]) * signal["size"]
                log.info(
                    f"  CLOSED {pos['market_slug']} "
                    f"reason={signal['reason']} pnl={pnl:+.4f} USDC"
                )
                closed.append(pos)

    for pos in closed:
        positions.remove(pos)

    # Check entries
    active_slugs = {p["market_slug"] for p in positions}

    for market in markets:
        if market["slug"] in active_slugs:
            continue

        prices = get_market_prices(client, market)
        if not prices:
            log.warning(f"  Could not fetch prices for {market['slug']}")
            continue

        signal = should_enter(market, prices, cfg)
        if not signal:
            continue

        result = place_order(
            client, signal["market_slug"], signal["token_id"],
            "buy", signal["price"], signal["size"], dry_run,
        )
        if result["success"]:
            positions.append({
                "market_slug": signal["market_slug"],
                "side": signal["side"],
                "token_id": signal["token_id"],
                "entry_price": signal["price"],
                "size": signal["size"],
                "up_token": market["up_token"],
                "down_token": market["down_token"],
                "end_date": market["end_date"],
            })
            log.info(
                f"  OPENED {signal['market_slug']} "
                f"side={signal['side']} @ {signal['price']:.4f} x{signal['size']}"
            )


if __name__ == "__main__":
    main()
