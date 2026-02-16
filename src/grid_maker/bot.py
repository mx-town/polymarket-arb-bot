"""Entry point for the grid-maker strategy."""

import argparse
import asyncio
import logging
import os
import re
import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from eth_account import Account
from web3 import Web3

from shared.client import init_client

from grid_maker.config import load_grid_maker_config
from grid_maker.engine import GridMakerEngine

log = logging.getLogger("gm.bot")


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


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Grid-maker strategy (Gabagool clone)")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "debug", "info", "warning", "error"],
        help="Root log level (default: INFO)",
    )
    return parser.parse_args()


def _setup_logging(level_str: str, dry_run: bool = True) -> None:
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s │ %(name)-16s │ %(message)s",
        datefmt="%H:%M:%S",
    )

    # Dim-aware console formatter
    for h in logging.getLogger().handlers:
        if isinstance(h, logging.StreamHandler) and not isinstance(h, logging.FileHandler):
            h.setFormatter(_ColorFormatter(
                fmt="%(asctime)s │ %(name)-16s │ %(message)s",
                datefmt="%H:%M:%S",
            ))

    # File handler
    mode = "dry" if dry_run else "live"
    log_dir = Path("logs") / mode
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"grid_maker_{datetime.now():%Y-%m-%d_%H%M%S}.log"
    fh = logging.FileHandler(log_file)
    fh.setLevel(level)
    fh.setFormatter(_StripAnsiFormatter(
        fmt="%(asctime)s │ %(name)-16s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(fh)

    for noisy in ("httpx", "httpcore", "urllib3", "py_clob_client", "hpack", "h2", "h11", "web3", "websockets"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def main():
    args = _parse_args()
    load_dotenv()

    with open("config.yaml") as f:
        raw_cfg = yaml.safe_load(f)

    cfg = load_grid_maker_config(raw_cfg)
    _setup_logging(args.log_level, dry_run=cfg.dry_run)

    if not cfg.enabled:
        log.info("Grid-maker strategy is disabled in config")
        sys.exit(0)

    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
    rpc_url = os.environ.get("POLYGON_RPC_URL", "")
    funder = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")

    client = init_client(cfg.dry_run)

    # Web3 + Account for on-chain merge
    w3 = None
    account = None
    if not cfg.dry_run and private_key and rpc_url:
        w3 = Web3(Web3.HTTPProvider(rpc_url))
        account = Account.from_key(private_key)
        log.info("INIT Web3+Account ready (addr=%s)", account.address)
    elif not cfg.dry_run:
        log.warning("INIT missing private key or RPC URL — merge disabled")

    engine = GridMakerEngine(
        client, cfg,
        w3=w3, account=account,
        rpc_url=rpc_url, funder_address=funder,
    )

    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        log.info("\033[33mSHUTDOWN user interrupt\033[0m")
        sys.exit(0)


if __name__ == "__main__":
    main()
