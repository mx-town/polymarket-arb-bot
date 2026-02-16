"""Entry point for the observer bot."""

import argparse
import asyncio
import json
import logging
import re
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from observer.analyzer import TradeAnalyzer
from observer.balance_tracker import BalanceTracker
from observer.book import BookPoller
from observer.btc_price import BtcPriceTracker
from observer.config import load_observer_config
from observer.models import C_RESET, C_YELLOW
from observer.onchain import MergeDetector
from observer.persistence.db import init_db, get_engine
from observer.persistence.schema import obs_sessions
from observer.persistence.writer import ObserverWriter
from observer.poller import ActivityPoller
from observer.positions import PositionPoller, detect_merges_from_changes


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Observer bot — reverse-engineer trading strategies",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "debug", "info", "warning", "error"],
        help="Root log level (default: INFO)",
    )
    return parser.parse_args()


class _StripAnsiFormatter(logging.Formatter):
    """Strip ANSI escape codes for clean log files."""
    _ansi_re = re.compile(r'\033\[[0-9;]*m')

    def format(self, record):
        result = super().format(record)
        return self._ansi_re.sub('', result)


class _ColorFormatter(logging.Formatter):
    """Dim DEBUG lines on the console for visual hierarchy."""
    _DIM = "\033[2m"
    _RESET = "\033[0m"

    def format(self, record):
        result = super().format(record)
        if record.levelno <= logging.DEBUG:
            return f"{self._DIM}{result}{self._RESET}"
        return result


def _setup_logging(level_str: str) -> None:
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s │ %(name)-16s │ %(message)s",
        datefmt="%H:%M:%S",
    )

    # Replace console handler formatter with dim-aware version
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            h.setFormatter(_ColorFormatter(
                fmt="%(asctime)s │ %(name)-16s │ %(message)s",
                datefmt="%H:%M:%S",
            ))

    # File handler
    log_dir = Path("logs") / "observer"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"observer_{datetime.now():%Y-%m-%d_%H%M%S}.log"
    fh = logging.FileHandler(log_file)
    fh.setLevel(level)
    fh.setFormatter(_StripAnsiFormatter(
        fmt="%(asctime)s │ %(name)-16s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(fh)

    for noisy in ("httpx", "httpcore", "urllib3", "requests", "hpack", "h2", "h11"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


log = logging.getLogger("obs.bot")


async def _run(cfg) -> None:
    """Main async loop — poll activity, positions, merges, and analyze."""
    # Initialize persistence
    session_id = f"obs_{datetime.now():%Y%m%d_%H%M%S}_{uuid.uuid4().hex[:6]}"
    engine = init_db()

    config_snapshot = json.dumps({
        "proxy_address": cfg.proxy_address,
        "poll_interval_sec": cfg.poll_interval_sec,
        "activity_limit": cfg.activity_limit,
        "positions_limit": cfg.positions_limit,
        "backfill_on_start": cfg.backfill_on_start,
    })
    with engine.begin() as conn:
        conn.execute(obs_sessions.insert().values(
            id=session_id,
            started_at=time.time(),
            proxy_address=cfg.proxy_address,
            config_snapshot=config_snapshot,
        ))

    writer = ObserverWriter(session_id)
    flush_task = asyncio.create_task(writer.run_flush_loop())

    poller = ActivityPoller(cfg.proxy_address, limit=cfg.activity_limit)
    pos_poller = PositionPoller(cfg.proxy_address, limit=cfg.positions_limit)
    merge_detector = MergeDetector(cfg.proxy_address, page_size=cfg.etherscan_page_size)
    analyzer = TradeAnalyzer()
    price_tracker = BtcPriceTracker()
    book_poller = BookPoller()
    balance_tracker = BalanceTracker(cfg.proxy_address)
    _last_balance_poll = 0.0

    try:
        # Initial backfill
        if cfg.backfill_on_start:
            trades = await asyncio.to_thread(poller.backfill)
            analyzer.ingest_trades(trades)
            await writer.enqueue_trades(trades)
            # Decode roles for backfilled trades
            for trade in trades:
                role = await asyncio.to_thread(merge_detector.decode_role, trade.tx_hash)
                if role:
                    log.info("ROLE │ %s │ %s %s │ %s", role, trade.side, trade.outcome, trade.slug)
                    await writer.update_trade_role(trade.tx_hash, role)

            positions = await asyncio.to_thread(pos_poller.snapshot)
            await writer.enqueue_positions(positions)

            merges = await asyncio.to_thread(merge_detector.poll_merges)
            analyzer.ingest_merges(merges)
            await writer.enqueue_merges(merges)

            price_snap = await asyncio.to_thread(price_tracker.snapshot)
            await writer.enqueue_price_snapshot(price_snap)

        log.info(
            "READY │ session=%s │ proxy=%s │ poll=%ds │ seen=%d trades │ %d windows",
            session_id,
            cfg.proxy_address[:10],
            cfg.poll_interval_sec,
            poller.seen_count,
            analyzer.active_count,
        )

        # Main polling loop
        tick = 0
        while True:
            await asyncio.sleep(cfg.poll_interval_sec)
            tick += 1

            # Activity poll
            new_trades = await asyncio.to_thread(poller.poll)
            if new_trades:
                analyzer.ingest_trades(new_trades)
                await writer.enqueue_trades(new_trades)
                # Decode roles for new trades
                for trade in new_trades:
                    role = await asyncio.to_thread(merge_detector.decode_role, trade.tx_hash)
                    if role:
                        log.info("ROLE │ %s │ %s %s │ %s", role, trade.side, trade.outcome, trade.slug)
                        await writer.update_trade_role(trade.tx_hash, role)

            # Price poll (every tick)
            price_snap = await asyncio.to_thread(price_tracker.poll)
            await writer.enqueue_price_snapshot(price_snap)

            # Book snapshot poll (every book_poll_interval ticks)
            if tick % cfg.book_poll_interval == 0:
                token_ids = pos_poller.active_token_ids
                if token_ids:
                    snapshots = await asyncio.to_thread(book_poller.poll, token_ids)
                    await writer.enqueue_book_snapshots(snapshots)

            # Position poll (every 3rd tick)
            if tick % 3 == 0:
                positions, changes = await asyncio.to_thread(pos_poller.poll)
                await writer.enqueue_positions(positions)
                await writer.enqueue_position_changes(changes)

                # Detect merges and redemptions from position decreases
                merges, redemptions = detect_merges_from_changes(changes)
                for m in merges:
                    analyzer.ingest_merge_from_position(m["slug"], m["shares"])
                    await writer.enqueue_detected_merge(m["slug"], m["shares"])
                for r in redemptions:
                    log.info(
                        "REDEMPTION │ %s │ %s │ %.1f shares (%.1f → %.1f)",
                        r["slug"], r["outcome"], r["shares"],
                        r["from_size"], r["to_size"],
                    )
                await writer.enqueue_redemptions(redemptions)

            # Balance poll (every balance_poll_interval_sec)
            current_time = time.time()
            if current_time - _last_balance_poll >= cfg.balance_poll_interval_sec:
                _last_balance_poll = current_time
                # Convert positions to dicts with current_value
                position_data = [
                    {
                        "current_value": p.current_value,
                        "slug": p.slug,
                        "outcome": p.outcome,
                        "size": p.size,
                    }
                    for p in pos_poller._prev.values()
                ]
                usdc_balance, total_position_value = await asyncio.to_thread(
                    balance_tracker.poll_balance, position_data
                )
                await writer.enqueue_balance_snapshot(usdc_balance, total_position_value)
                log.info(
                    "BALANCE │ usdc=$%.2f positions=$%.2f equity=$%.2f",
                    usdc_balance,
                    total_position_value,
                    usdc_balance + total_position_value,
                )
                # TODO: Add transfer scanning later (expensive, requires block range calculation)

            # Merge poll (every 6th tick)
            if tick % 6 == 0:
                merges = await asyncio.to_thread(merge_detector.poll_merges)
                if merges:
                    analyzer.ingest_merges(merges)
                    await writer.enqueue_merges(merges)

                # Also persist market windows on merge tick
                all_windows = analyzer.get_all_windows()
                await writer.enqueue_market_windows(all_windows)

            # Periodic summary (every 30th tick)
            if tick % 30 == 0:
                s = analyzer.summary()
                log.info(
                    "SUMMARY │ active=%d closed=%d │ seen=%d trades │ %d positions │ db=%d rows",
                    s["active"],
                    s["closed"],
                    poller.seen_count,
                    pos_poller.position_count,
                    writer.stats["total_written"],
                )
                log.info(
                    "PRICES │ btc=$%.2f eth=$%.2f │ btc_1m=%.3f%% btc_5m=%.3f%% vol_5m=%.4f%% range_5m=%.3f%%",
                    price_snap.btc_price, price_snap.eth_price,
                    price_snap.btc_pct_change_1m, price_snap.btc_pct_change_5m,
                    price_snap.btc_rolling_vol_5m, price_snap.btc_range_pct_5m,
                )

    finally:
        # Record session end
        flush_task.cancel()
        try:
            await flush_task
        except asyncio.CancelledError:
            pass

        # Final flush of any remaining buffer
        await writer._flush()

        with engine.begin() as conn:
            conn.execute(
                obs_sessions.update()
                .where(obs_sessions.c.id == session_id)
                .values(ended_at=time.time())
            )
        log.info("DB │ session %s ended, %d rows written", session_id, writer.stats["total_written"])


def main():
    args = _parse_args()
    load_dotenv()

    with open("config.yaml") as f:
        raw_cfg = yaml.safe_load(f)

    cfg = load_observer_config(raw_cfg)
    _setup_logging(cfg.log_level if args.log_level == "INFO" else args.log_level)

    if not cfg.enabled:
        log.info("Observer bot disabled in config")
        sys.exit(0)

    log.info(
        "INIT │ proxy=%s │ poll=%ds │ backfill=%s",
        cfg.proxy_address[:10],
        cfg.poll_interval_sec,
        cfg.backfill_on_start,
    )

    try:
        asyncio.run(_run(cfg))
    except KeyboardInterrupt:
        log.info("%sSHUTDOWN user interrupt%s", C_YELLOW, C_RESET)
        sys.exit(0)


if __name__ == "__main__":
    main()
