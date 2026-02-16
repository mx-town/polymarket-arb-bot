"""Polymarket CLOB client initialization — shared across strategies."""

from __future__ import annotations

import logging
import os

from py_builder_signing_sdk.config import BuilderConfig
from py_builder_signing_sdk.sdk_types import BuilderApiKeyCreds
from py_clob_client.client import ClobClient

log = logging.getLogger("shared.client")

CLOB_HOST = "https://clob.polymarket.com"
CHAIN_ID = 137


def init_client(dry_run: bool) -> ClobClient:
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
