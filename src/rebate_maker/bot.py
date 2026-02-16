"""Entry point for the rebate-maker strategy."""

import argparse
import asyncio
import logging
import os
import re
import sys
import uuid
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

from shared.client import init_client
from shared.events import consume, init_event_bus

from rebate_maker.config import load_rebate_maker_config
from rebate_maker.engine import Engine
from rebate_maker.models import C_RESET, C_YELLOW
from rebate_maker.persistence.db import cleanup_old_data, init_db
from rebate_maker.persistence.writer import BatchWriter


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Rebate-maker strategy")
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


def _setup_logging(level_str: str, dry_run: bool = True) -> None:
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s │ %(name)-16s │ %(message)s",
        datefmt="%H:%M:%S",
    )

    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            h.setFormatter(_ColorFormatter(
                fmt="%(asctime)s │ %(name)-16s │ %(message)s",
                datefmt="%H:%M:%S",
            ))

    mode = "dry" if dry_run else "live"
    log_dir = Path("logs") / mode
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"rebate_maker_{datetime.now():%Y-%m-%d_%H%M%S}.log"
    fh = logging.FileHandler(log_file)
    fh.setLevel(level)
    fh.setFormatter(_StripAnsiFormatter(
        fmt="%(asctime)s │ %(name)-16s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(fh)

    for noisy in ("httpx", "httpcore", "urllib3", "py_clob_client", "hpack", "h2", "h11", "web3", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


log = logging.getLogger("rm.bot")

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137


def main():
    args = _parse_args()
    load_dotenv()

    with open("config.yaml") as f:
        raw_cfg = yaml.safe_load(f)

    cfg = load_rebate_maker_config(raw_cfg)
    _setup_logging(args.log_level, dry_run=cfg.dry_run)

    if not cfg.enabled:
        log.info("Rebate-maker strategy is disabled in config")
        sys.exit(0)

    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
    rpc_url = os.environ.get("POLYGON_RPC_URL", "")
    funder = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")

    client = init_client(cfg.dry_run)

    w3 = None
    account = None
    if not cfg.dry_run and private_key and rpc_url:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        account = Account.from_key(private_key)
        log.info("INIT Web3+Account ready for on-chain merge/redeem (addr=%s)", account.address)
    elif not cfg.dry_run:
        log.warning("INIT missing private key or RPC URL — merge/redeem disabled")

    engine = Engine(client, cfg, w3=w3, account=account, rpc_url=rpc_url, funder_address=funder)

    try:
        asyncio.run(_run_all(engine, cfg))
    except KeyboardInterrupt:
        log.info("%sSHUTDOWN user interrupt%s", C_YELLOW, C_RESET)
        sys.exit(0)


async def _run_all(engine: Engine, cfg) -> None:
    """Run engine + event dispatcher + persistence concurrently."""
    init_event_bus()
    db_engine = init_db()
    session_id = str(uuid.uuid4())[:8]
    writer = BatchWriter(session_id)

    import json
    import time
    from rebate_maker.persistence.schema import sessions
    with db_engine.begin() as conn:
        conn.execute(sessions.insert().values(
            id=session_id,
            started_at=time.time(),
            mode="dry" if cfg.dry_run else "live",
            config_snapshot=json.dumps({"bankroll_usd": float(cfg.bankroll_usd), "min_edge": float(cfg.min_edge)}),
        ))

    cleanup_old_data(retention_days=30)

    log.info("PERSISTENCE │ event bus initialized (session=%s)", session_id)

    async def _event_dispatcher():
        """Consume events and fan out to writer."""
        while True:
            try:
                event = await consume()
                await writer.enqueue(event)
            except Exception as e:
                log.error("EVENT_DISPATCH │ error: %s", e)

    try:
        await asyncio.gather(
            engine.run(),
            _event_dispatcher(),
            writer.run_flush_loop(),
        )
    finally:
        with db_engine.begin() as conn:
            conn.execute(
                sessions.update()
                .where(sessions.c.id == session_id)
                .values(ended_at=time.time())
            )
        log.info("SESSION │ ended_at recorded for session=%s", session_id)


if __name__ == "__main__":
    main()
