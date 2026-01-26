"""
Market discovery via Gamma API.

Fetches active Up/Down markets from Polymarket.
"""

import json
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from src.config import GAMMA_HOST
from src.market.state import MarketState, MarketStateManager
from src.utils.logging import get_logger

logger = get_logger("discovery")


def parse_json_field(value) -> list:
    """Parse a JSON string field or return as-is if already parsed"""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return []
    return []


def parse_datetime(value: Optional[str]) -> Optional[datetime]:
    """Parse ISO datetime string"""
    if not value:
        return None
    try:
        # Handle various formats
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def fetch_all_markets(
    max_markets: int = 0,
    market_types: Optional[list[str]] = None,
) -> list[dict]:
    """
    Fetch all active binary markets from Gamma API.

    Returns raw market data dicts.
    """
    all_markets = []
    offset = 0

    logger.info("FETCH_START", f"max_markets={max_markets}")

    while True:
        try:
            resp = requests.get(
                f"{GAMMA_HOST}/markets",
                params={
                    "closed": "false",
                    "archived": "false",
                    "limit": 100,
                    "offset": offset,
                },
                timeout=15,
            )
            resp.raise_for_status()
            markets = resp.json()

            if not markets:
                break

            # Parse and filter for binary markets with 2 tokens
            for m in markets:
                clob_tokens = parse_json_field(m.get("clobTokenIds"))

                if len(clob_tokens) != 2:
                    continue

                slug = m.get("slug", "").lower()
                question = m.get("question", "").lower()

                # Filter by market type if specified
                if market_types:
                    match = False
                    for mt in market_types:
                        if mt.lower() in slug or mt.lower() in question:
                            match = True
                            break
                    if not match:
                        continue

                all_markets.append({
                    "condition_id": m.get("conditionId", ""),
                    "question": m.get("question", "Unknown"),
                    "slug": m.get("slug", ""),
                    "yes_token": clob_tokens[0],
                    "no_token": clob_tokens[1],
                    "end_date": m.get("endDate"),
                    "outcomes": parse_json_field(m.get("outcomes")),
                })

            if len(markets) < 100:
                break
            offset += 100

            # Check max_markets limit
            if max_markets and len(all_markets) >= max_markets:
                all_markets = all_markets[:max_markets]
                break

        except requests.RequestException as e:
            logger.error("FETCH_ERROR", f"offset={offset} error={e}")
            break

    logger.info("FETCH_COMPLETE", f"found={len(all_markets)}")
    return all_markets


def fetch_updown_markets(
    max_markets: int = 0,
    market_types: Optional[list[str]] = None,
) -> MarketStateManager:
    """
    Fetch Up/Down markets and return a MarketStateManager.

    Filters for markets matching btc-updown, eth-updown patterns.
    """
    if market_types is None:
        market_types = ["btc-updown", "eth-updown", "up-or-down"]

    raw_markets = fetch_all_markets(max_markets=max_markets, market_types=market_types)

    manager = MarketStateManager()

    for m in raw_markets:
        # Determine which token is UP vs DOWN based on outcomes
        outcomes = m.get("outcomes", [])
        yes_token = m["yes_token"]
        no_token = m["no_token"]

        # Usually outcomes are ["Up", "Down"] or ["Yes", "No"]
        # For Up/Down markets, YES typically means "Up"
        up_token = yes_token
        down_token = no_token

        if len(outcomes) >= 2:
            if "down" in outcomes[0].lower():
                up_token, down_token = down_token, up_token

        state = MarketState(
            market_id=m["condition_id"],
            slug=m["slug"],
            question=m["question"],
            up_token_id=up_token,
            down_token_id=down_token,
            resolution_time=parse_datetime(m.get("end_date")),
        )
        manager.add_market(state)

    logger.info("UPDOWN_MARKETS", f"loaded={len(manager.markets)}")
    return manager


def fetch_recent_updown_markets(
    max_age_hours: float = 1.0,
    fallback_age_hours: float = 24.0,
    min_volume_24h: float = 100.0,
    market_types: Optional[list[str]] = None,
    max_markets: int = 0,
) -> MarketStateManager:
    """
    Fetch recently created Up/Down markets.

    Strategy:
    1. First tries to find markets created within max_age_hours
    2. Falls back to fallback_age_hours if none found
    3. Only includes markets with acceptingOrders=True and volume > min_volume_24h
    """
    if market_types is None:
        market_types = ["btc-updown", "eth-updown", "up-or-down"]

    now = datetime.now(timezone.utc)
    cutoff_recent = now - timedelta(hours=max_age_hours)
    cutoff_fallback = now - timedelta(hours=fallback_age_hours)

    # Fetch all markets with full metadata
    all_markets = _fetch_markets_with_metadata()

    recent_markets = []
    fallback_markets = []

    for m in all_markets:
        # Type filter
        slug = m.get("slug", "").lower()
        question = m.get("question", "").lower()
        if not any(mt.lower() in slug or mt.lower() in question for mt in market_types):
            continue

        # Must be accepting orders
        if not m.get("acceptingOrders", False):
            continue

        # Volume filter
        volume = m.get("volume24hr", 0) or 0
        if volume < min_volume_24h:
            continue

        # Must have 2 tokens (binary market)
        clob_tokens = parse_json_field(m.get("clobTokenIds"))
        if len(clob_tokens) != 2:
            continue

        # Age filter
        created_at = parse_datetime(m.get("createdAt"))
        if created_at:
            if created_at >= cutoff_recent:
                recent_markets.append(m)
            elif created_at >= cutoff_fallback:
                fallback_markets.append(m)

    # Use recent or fall back
    markets_to_use = recent_markets if recent_markets else fallback_markets
    logger.info(
        "RECENT_MARKETS",
        f"recent={len(recent_markets)} fallback={len(fallback_markets)} using={len(markets_to_use)}",
    )

    # Apply max_markets limit
    if max_markets > 0 and len(markets_to_use) > max_markets:
        markets_to_use = markets_to_use[:max_markets]

    # Build manager
    return _build_manager_from_raw(markets_to_use)


def _fetch_markets_with_metadata() -> list[dict]:
    """Fetch markets with full metadata including createdAt, volume, acceptingOrders"""
    all_markets = []
    offset = 0

    while True:
        try:
            resp = requests.get(
                f"{GAMMA_HOST}/markets",
                params={
                    "closed": "false",
                    "archived": "false",
                    "limit": 100,
                    "offset": offset,
                },
                timeout=15,
            )
            resp.raise_for_status()
            markets = resp.json()

            if not markets:
                break

            all_markets.extend(markets)

            if len(markets) < 100:
                break
            offset += 100

        except requests.RequestException as e:
            logger.error("FETCH_ERROR", f"offset={offset} error={e}")
            break

    return all_markets


def _build_manager_from_raw(markets: list[dict]) -> MarketStateManager:
    """Build MarketStateManager from raw market data"""
    manager = MarketStateManager()

    for m in markets:
        clob_tokens = parse_json_field(m.get("clobTokenIds"))
        outcomes = parse_json_field(m.get("outcomes"))

        yes_token = clob_tokens[0]
        no_token = clob_tokens[1]

        # Determine UP vs DOWN
        up_token = yes_token
        down_token = no_token
        if len(outcomes) >= 2 and "down" in outcomes[0].lower():
            up_token, down_token = down_token, up_token

        state = MarketState(
            market_id=m.get("conditionId", ""),
            slug=m.get("slug", ""),
            question=m.get("question", "Unknown"),
            up_token_id=up_token,
            down_token_id=down_token,
            resolution_time=parse_datetime(m.get("endDate")),
        )
        manager.add_market(state)

    return manager
