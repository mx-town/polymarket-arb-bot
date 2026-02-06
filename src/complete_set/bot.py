"""Entry point for the complete-set arbitrage strategy."""

import asyncio
import logging
import os
import sys

import yaml
from dotenv import load_dotenv
from py_clob_client.client import ClobClient

from complete_set.config import load_complete_set_config
from complete_set.engine import Engine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s │ %(name)-16s │ %(message)s",
    datefmt="%H:%M:%S",
)
for noisy in ("httpx", "httpcore", "urllib3", "py_clob_client"):
    logging.getLogger(noisy).setLevel(logging.WARNING)

log = logging.getLogger("cs.bot")

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137


def _init_client(dry_run: bool) -> ClobClient:
    """Initialize ClobClient. Authenticated for live, read-only for dry run."""
    if dry_run:
        log.info("INIT read-only client (DRY_RUN)")
        return ClobClient(CLOB_HOST)

    private_key = os.environ.get("POLYMARKET_PRIVATE_KEY")
    funder = os.environ.get("POLYMARKET_FUNDER_ADDRESS")

    if not private_key or not funder:
        raise ValueError("POLYMARKET_PRIVATE_KEY and POLYMARKET_FUNDER_ADDRESS required")

    client = ClobClient(
        CLOB_HOST,
        key=private_key,
        chain_id=CHAIN_ID,
        signature_type=1,
        funder=funder,
    )
    client.set_api_creds(client.create_or_derive_api_creds())
    log.info("INIT authenticated client ready")
    return client


def main():
    load_dotenv()

    with open("config.yaml") as f:
        raw_cfg = yaml.safe_load(f)

    cfg = load_complete_set_config(raw_cfg)

    if not cfg.enabled:
        log.info("Complete-set strategy is disabled in config")
        sys.exit(0)

    client = _init_client(cfg.dry_run)
    engine = Engine(client, cfg)

    try:
        asyncio.run(engine.run())
    except KeyboardInterrupt:
        log.info("SHUTDOWN user interrupt")
        sys.exit(0)


if __name__ == "__main__":
    main()
