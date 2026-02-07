"""Late-entry bot for Polymarket 15m crypto Up/Down markets.

Polls for markets in the last 4 minutes before resolution,
buys the favorite side, exits on take-profit or before close.
Uses GTC maker (limit) orders with fill polling.
"""

import logging
import sys
import time
from datetime import UTC, datetime

import yaml
from dotenv import load_dotenv

from late_entry.data import get_active_markets, get_market_prices
from late_entry.executor import (
    cancel_order,
    check_order,
    init_client,
    place_order,
)
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
    log.info(f"  Polymarket Late-Entry Bot v0.2.0  [{mode}]")
    log.info(f"  Order type: GTC maker (limit)")
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
    pending_buys: list[dict] = []
    pending_sells: list[dict] = []
    session = {
        "total_pnl": 0.0,
        "trades": 0,
        "wins": 0,
        "losses": 0,
        "total_invested": 0.0,
        "total_returned": 0.0,
    }

    while True:
        try:
            _tick(
                client, assets, positions, pending_buys, pending_sells,
                strategy_cfg, dry_run, session,
            )
        except KeyboardInterrupt:
            _cancel_all_pending(client, pending_buys, pending_sells, dry_run)
            _log_session_summary(session)
            log.info("SHUTDOWN user interrupt")
            sys.exit(0)
        except Exception as e:
            log.error(f"TICK_ERROR error={e}")

        time.sleep(poll_interval)


def _log_session_summary(session: dict):
    """Log a session summary line."""
    t = session["trades"]
    if t == 0:
        return
    w, l = session["wins"], session["losses"]
    wr = (w / t * 100) if t else 0
    log.info(
        f"  SESSION │ pnl={session['total_pnl']:+.4f} USDC │ "
        f"{t} trades ({w}W {l}L {wr:.0f}%) │ "
        f"invested=${session['total_invested']:.2f} returned=${session['total_returned']:.2f}"
    )


def _cancel_all_pending(client, pending_buys, pending_sells, dry_run):
    """Cancel all resting orders on shutdown."""
    for pb in list(pending_buys):
        cancel_order(client, pb["order_id"], dry_run)
    pending_buys.clear()
    for ps in list(pending_sells):
        cancel_order(client, ps["order_id"], dry_run)
    pending_sells.clear()


def _tick(client, assets, positions, pending_buys, pending_sells, cfg, dry_run, session):
    """Single polling tick: check fills, manage exits, check entries."""
    now = datetime.now(UTC)

    # ── Phase 1: Check pending buy fills ──────────────────────────
    for pb in list(pending_buys):
        info = check_order(client, pb["order_id"], dry_run)

        if info["status"] in ("filled", "partial"):
            filled_size = info["matched_size"] or pb["size"]
            cost = pb["price"] * filled_size
            session["total_invested"] += cost

            positions.append({
                "market_slug": pb["market_slug"],
                "side": pb["side"],
                "token_id": pb["token_id"],
                "entry_price": pb["price"],
                "size": filled_size,
                "up_token": pb["up_token"],
                "down_token": pb["down_token"],
                "end_date": pb["end_date"],
            })
            log.info(
                f"  FILLED_BUY {pb['market_slug']} "
                f"side={pb['side']} @ {pb['price']:.4f} x{filled_size} "
                f"cost=${cost:.2f}"
            )
            pending_buys.remove(pb)

        elif info["status"] in ("cancelled", "rejected"):
            log.info(f"  DEAD_BUY {pb['market_slug']} order={pb['order_id']} status={info['status']}")
            pending_buys.remove(pb)
        # 'pending' / 'unknown' → keep waiting

    # ── Phase 2: Check pending sell fills ─────────────────────────
    closed = []
    for ps in list(pending_sells):
        info = check_order(client, ps["order_id"], dry_run)

        if info["status"] in ("filled", "partial"):
            pos = ps["position"]
            filled_size = info["matched_size"] or ps["size"]
            pnl = (ps["price"] - pos["entry_price"]) * filled_size
            returned = ps["price"] * filled_size

            session["total_pnl"] += pnl
            session["trades"] += 1
            session["total_returned"] += returned
            if pnl >= 0:
                session["wins"] += 1
            else:
                session["losses"] += 1

            log.info(
                f"  FILLED_SELL {pos['market_slug']} "
                f"reason={ps['reason']} pnl={pnl:+.4f} │ "
                f"session={session['total_pnl']:+.4f} USDC "
                f"({session['trades']}t {session['wins']}W {session['losses']}L)"
            )
            closed.append(pos)
            pending_sells.remove(ps)

        elif info["status"] in ("cancelled", "rejected"):
            log.info(f"  DEAD_SELL {ps['position']['market_slug']} order={ps['order_id']} status={info['status']}")
            pending_sells.remove(ps)

    for pos in closed:
        if pos in positions:
            positions.remove(pos)

    if closed and not positions:
        _log_session_summary(session)

    # ── Phase 3: Discover markets ─────────────────────────────────
    markets = get_active_markets(assets)
    if not markets:
        return

    # ── Phase 4: Cancel stale pending buys near resolution ────────
    for pb in list(pending_buys):
        secs_left = (pb["end_date"] - now).total_seconds()
        if secs_left < cfg["exit_buffer_sec"]:
            log.info(f"  CANCEL_STALE_BUY {pb['market_slug']} secs_left={secs_left:.0f}")
            cancel_order(client, pb["order_id"], dry_run)
            pending_buys.remove(pb)

    # ── Phase 5: Check exits for active positions ─────────────────
    sell_slugs = {ps["position"]["market_slug"] for ps in pending_sells}

    for pos in list(positions):
        if pos["market_slug"] in sell_slugs:
            continue  # already have a pending sell

        pos_market = next((m for m in markets if m["slug"] == pos["market_slug"]), None)
        if not pos_market:
            continue

        prices = get_market_prices(pos_market)
        signal = should_exit(pos, prices, cfg)
        if not signal:
            continue

        result = place_order(
            client, pos["market_slug"], signal["token_id"],
            "sell", signal["price"], signal["size"], dry_run,
        )
        if not result["success"]:
            continue

        if result["status"] == "filled":
            # Dry-run instant fill
            pnl = (signal["price"] - pos["entry_price"]) * signal["size"]
            returned = signal["price"] * signal["size"]
            session["total_pnl"] += pnl
            session["trades"] += 1
            session["total_returned"] += returned
            if pnl >= 0:
                session["wins"] += 1
            else:
                session["losses"] += 1

            log.info(
                f"  CLOSED {pos['market_slug']} "
                f"reason={signal['reason']} pnl={pnl:+.4f} │ "
                f"session={session['total_pnl']:+.4f} USDC "
                f"({session['trades']}t {session['wins']}W {session['losses']}L)"
            )
            positions.remove(pos)
        else:
            # Live: track pending sell
            pending_sells.append({
                "order_id": result["order_id"],
                "position": pos,
                "market_slug": pos["market_slug"],
                "price": signal["price"],
                "size": signal["size"],
                "reason": signal["reason"],
                "placed_at": time.time(),
            })
            log.info(
                f"  SELL_PLACED {pos['market_slug']} "
                f"@ {signal['price']:.4f} x{signal['size']} "
                f"reason={signal['reason']} order={result['order_id']}"
            )

    # Log summary if all positions just closed (dry-run instant sells)
    if not positions and not pending_sells and session["trades"] > 0:
        pass  # summary already logged above when closed list was processed

    # ── Phase 6: Check entries ────────────────────────────────────
    active_slugs = {p["market_slug"] for p in positions}
    pending_slugs = {pb["market_slug"] for pb in pending_buys}

    for market in markets:
        slug = market["slug"]
        if slug in active_slugs or slug in pending_slugs:
            continue

        prices = get_market_prices(market)
        signal = should_enter(market, prices, cfg)
        if not signal:
            continue

        result = place_order(
            client, signal["market_slug"], signal["token_id"],
            "buy", signal["price"], signal["size"], dry_run,
        )
        if not result["success"]:
            continue

        if result["status"] == "filled":
            # Dry-run instant fill
            cost = signal["price"] * signal["size"]
            session["total_invested"] += cost
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
                f"side={signal['side']} @ {signal['price']:.4f} x{signal['size']} "
                f"cost=${cost:.2f}"
            )
        else:
            # Live: track pending buy
            pending_buys.append({
                "order_id": result["order_id"],
                "market_slug": signal["market_slug"],
                "side": signal["side"],
                "token_id": signal["token_id"],
                "price": signal["price"],
                "size": signal["size"],
                "up_token": market["up_token"],
                "down_token": market["down_token"],
                "end_date": market["end_date"],
                "placed_at": time.time(),
            })
            log.info(
                f"  BUY_PLACED {signal['market_slug']} "
                f"side={signal['side']} @ {signal['price']:.4f} x{signal['size']} "
                f"order={result['order_id']}"
            )


if __name__ == "__main__":
    main()
