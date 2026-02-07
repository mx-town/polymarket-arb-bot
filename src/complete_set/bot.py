"""Entry point for the complete-set arbitrage strategy."""

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
from py_builder_signing_sdk.config import BuilderConfig
from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds
from py_clob_client.client import ClobClient
from web3 import Web3

from complete_set.config import load_complete_set_config
from complete_set.engine import Engine


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Complete-set arb strategy")
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


def _setup_logging(level_str: str) -> None:
    level = getattr(logging, level_str.upper(), logging.INFO)
    logging.basicConfig(
        level=level,
        format="%(asctime)s │ %(name)-16s │ %(message)s",
        datefmt="%H:%M:%S",
    )

    # File handler — full timestamps, no ANSI colors
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)
    log_file = log_dir / f"complete_set_{datetime.now():%Y-%m-%d_%H%M%S}.log"
    fh = logging.FileHandler(log_file)
    fh.setLevel(level)
    fh.setFormatter(_StripAnsiFormatter(
        fmt="%(asctime)s │ %(name)-16s │ %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(fh)

    for noisy in ("httpx", "httpcore", "urllib3", "py_clob_client", "hpack", "h2", "h11"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("cs.bot")

# ANSI colors for log highlights
C_YELLOW = "\033[33m"
C_RESET = "\033[0m"

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137


def _init_client(dry_run: bool) -> ClobClient:
    """Initialize ClobClient. Authenticated for live, read-only for dry run."""
    if dry_run:
        log.info("INIT read-only client (DRY_RUN)")
        return ClobClient(CLOB_HOST, chain_id=CHAIN_ID)

    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
    funder = os.environ.get("POLYMARKET_FUNDER_ADDRESS")

    if not private_key or not funder:
        raise ValueError("POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER_ADDRESS required")

    # Builder code for fee rebates (optional)
    builder_config = None
    builder_key = os.environ.get("POLYMARKET_BUILDER_KEY")
    builder_secret = os.environ.get("POLYMARKET_BUILDER_SECRET")
    builder_passphrase = os.environ.get("POLYMARKET_BUILDER_PASSPHRASE")
    if builder_key and builder_secret and builder_passphrase:
        builder_config = BuilderConfig(
            local_builder_creds=BuilderApiKeyCreds(
                key=builder_key,
                secret=builder_secret,
                passphrase=builder_passphrase,
            ),
        )
        log.info("INIT builder code configured for fee rebates")

    sig_type = int(os.environ.get("POLYMARKET_SIGNATURE_TYPE", "0"))
    log.info("INIT signature_type=%d", sig_type)

    client = ClobClient(
        CLOB_HOST,
        key=private_key,
        chain_id=CHAIN_ID,
        signature_type=sig_type,
        funder=funder,
        builder_config=builder_config,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    log.info("INIT authenticated client ready (builder=%s)", builder_config is not None)
    return client


def main():
    args = _parse_args()
    _setup_logging(args.log_level)
    load_dotenv()

    with open("config.yaml") as f:
        raw_cfg = yaml.safe_load(f)

    cfg = load_complete_set_config(raw_cfg)

    if not cfg.enabled:
        log.info("Complete-set strategy is disabled in config")
        sys.exit(0)

    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY", "")
    rpc_url = os.environ.get("POLYGON_RPC_URL", "")
    funder = os.environ.get("POLYMARKET_FUNDER_ADDRESS", "")

    client = _init_client(cfg.dry_run)

    # Create Web3 + Account for direct on-chain merge/redeem
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
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        log.info("%sSHUTDOWN user interrupt%s", C_YELLOW, C_RESET)
        sys.exit(0)


if __name__ == "__main__":
    main()
