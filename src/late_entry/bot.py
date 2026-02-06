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
    format="%(asctime)s %(name)-10s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
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

    # Merge trading + late_entry config for strategy functions
    strategy_cfg = {**cfg["late_entry"], "max_position_size": cfg["trading"]["max_position_size"]}

    log.info(f"STARTING dry_run={dry_run} assets={assets} poll={poll_interval}s")

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

    # Check exits first
    closed = []
    for pos in positions:
        prices = get_market_prices(client, pos)
        if not prices:
            continue

        signal = should_exit(pos, prices, cfg)
        if signal:
            result = place_order(
                client, signal["token_id"], "sell", signal["price"], signal["size"], dry_run
            )
            if result["success"]:
                pnl = (signal["price"] - pos["entry_price"]) * signal["size"]
                log.info(
                    f"CLOSED market={pos['market_slug']} reason={signal['reason']} pnl={pnl:+.4f}"
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
            continue

        signal = should_enter(market, prices, cfg)
        if not signal:
            continue

        result = place_order(
            client, signal["token_id"], "buy", signal["price"], signal["size"], dry_run
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
            log.info(f"OPENED market={signal['market_slug']} side={signal['side']}")


if __name__ == "__main__":
    main()
