"""
Market discovery via Gamma API.

Fetches active Up/Down markets from Polymarket using the /events endpoint.
Up/Down markets are restricted and only appear in /events, not /markets.
"""

import json
from datetime import UTC, datetime, timedelta

import requests

from src.config import GAMMA_HOST
from src.market.state import MarketState, MarketStateManager
from src.utils.logging import get_logger

logger = get_logger("discovery")

# Map candle intervals to series recurrence patterns
# Note: 5m removed - same fees as 15m with no advantage
INTERVAL_TO_RECURRENCE = {
    "1h": "hourly",
    "15m": "15m",
}

# Series IDs for direct lookup (most reliable method)
# These are the Gamma API series IDs for updown markets
SERIES_IDS = {
    ("bitcoin", "15m"): "10192",
    ("bitcoin", "1h"): "10191",
    ("ethereum", "15m"): "10194",
    ("ethereum", "1h"): "10193",
}

# Default crypto assets to track (14 major cryptos)
DEFAULT_ASSETS = [
    "bitcoin",
    "ethereum",
    "solana",
    "xrp",
    "bnb",
    "cardano",
    "dogecoin",
    "avalanche",
    "polkadot",
    "chainlink",
    "litecoin",
    "shiba",
    "near",
    "aptos",
]

# Asset name variations (slug can use full name or abbreviation)
ASSET_ALIASES = {
    "bitcoin": ["bitcoin", "btc"],
    "ethereum": ["ethereum", "eth"],
    "solana": ["solana", "sol"],
    "xrp": ["xrp"],
    "bnb": ["bnb", "binancecoin"],
    "cardano": ["cardano", "ada"],
    "dogecoin": ["dogecoin", "doge"],
    "avalanche": ["avalanche", "avax"],
    "polkadot": ["polkadot", "dot"],
    "chainlink": ["chainlink", "link"],
    "litecoin": ["litecoin", "ltc"],
    "shiba": ["shiba", "shib"],
    "near": ["near"],
    "aptos": ["aptos", "apt"],
}

# Map asset names to Binance trading symbols
ASSET_TO_BINANCE_SYMBOL = {
    "bitcoin": "BTCUSDT",
    "ethereum": "ETHUSDT",
    "solana": "SOLUSDT",
    "xrp": "XRPUSDT",
    "bnb": "BNBUSDT",
    "cardano": "ADAUSDT",
    "dogecoin": "DOGEUSDT",
    "avalanche": "AVAXUSDT",
    "polkadot": "DOTUSDT",
    "chainlink": "LINKUSDT",
    "litecoin": "LTCUSDT",
    "shiba": "SHIBUSDT",
    "near": "NEARUSDT",
    "aptos": "APTUSDT",
}


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


def parse_datetime(value: str | None) -> datetime | None:
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


def fetch_markets_by_series(
    asset: str = "bitcoin",
    candle_interval: str = "15m",
    max_markets: int = 5,
) -> list[dict]:
    """
    Fetch Up/Down markets using series_id (most reliable method).

    Args:
        asset: Asset name (e.g., "bitcoin", "ethereum")
        candle_interval: "1h" or "15m"
        max_markets: Maximum markets to return

    Returns:
        List of market dicts with condition_id, slug, tokens, etc.
    """
    series_id = SERIES_IDS.get((asset.lower(), candle_interval))
    if not series_id:
        logger.warning("NO_SERIES_ID", f"asset={asset} interval={candle_interval}")
        return []

    logger.info(
        "FETCH_BY_SERIES", f"series_id={series_id} asset={asset} interval={candle_interval}"
    )

    try:
        resp = requests.get(
            f"{GAMMA_HOST}/events",
            params={
                "series_id": series_id,
                "closed": "false",
                "limit": max_markets,
            },
            timeout=15,
        )
        resp.raise_for_status()
        events = resp.json()

        markets = []
        for event in events:
            for m in event.get("markets", []):
                clob_tokens = parse_json_field(m.get("clobTokenIds"))
                if len(clob_tokens) != 2:
                    continue

                markets.append(
                    {
                        "condition_id": m.get("conditionId", ""),
                        "question": m.get("question", event.get("title", "Unknown")),
                        "slug": m.get("slug", event.get("slug", "")),
                        "yes_token": clob_tokens[0],
                        "no_token": clob_tokens[1],
                        "end_date": m.get("endDate", event.get("endDate")),
                        "outcomes": parse_json_field(m.get("outcomes")),
                        "accepting_orders": m.get("acceptingOrders", True),
                    }
                )

        logger.info("FETCH_BY_SERIES_COMPLETE", f"found={len(markets)}")
        return markets

    except requests.RequestException as e:
        logger.error("FETCH_BY_SERIES_ERROR", str(e))
        return []


def fetch_updown_events(
    candle_interval: str = "1h",
    assets: list[str] | None = None,
    max_markets: int = 0,
) -> list[dict]:
    """
    Fetch Up/Down markets from the /events endpoint.

    Up/Down markets are restricted and only appear in /events, not /markets.

    Args:
        candle_interval: "1h", "15m", or "5m" - determines which series to fetch
        assets: List of assets to track, e.g. ["bitcoin", "ethereum"]
        max_markets: Maximum markets to return (0 = unlimited)

    Returns:
        List of market dicts with condition_id, slug, tokens, etc.
    """
    if assets is None:
        assets = DEFAULT_ASSETS

    recurrence = INTERVAL_TO_RECURRENCE.get(candle_interval, "hourly")
    all_markets = []
    offset = 0

    logger.info(
        "FETCH_EVENTS_START",
        f"interval={candle_interval} recurrence={recurrence} assets={assets}",
    )

    while True:
        try:
            resp = requests.get(
                f"{GAMMA_HOST}/events",
                params={
                    "closed": "false",
                    "order": "id",
                    "ascending": "false",
                    "limit": 100,
                    "offset": offset,
                },
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json()

            if not events:
                break

            for event in events:
                slug = event.get("slug", "").lower()

                # Filter for up-or-down events (handles both patterns)
                # 1h uses: bitcoin-up-or-down-january-26-1pm-et
                # 15m/5m uses: btc-updown-15m-1769540400
                if "up-or-down" not in slug and "updown" not in slug:
                    continue

                # Filter by asset (check all aliases)
                asset_match = False
                for asset in assets:
                    asset_lower = asset.lower()
                    aliases = ASSET_ALIASES.get(asset_lower, [asset_lower])
                    if any(alias in slug for alias in aliases):
                        asset_match = True
                        break
                if not asset_match:
                    continue

                # Filter by series recurrence (hourly, 15m, 5m)
                series_list = event.get("series", [])
                if series_list:
                    series = series_list[0] if isinstance(series_list[0], dict) else {}
                    series_recurrence = series.get("recurrence", "")
                    if series_recurrence != recurrence:
                        continue

                # Extract markets from event
                markets = event.get("markets", [])
                for m in markets:
                    clob_tokens = parse_json_field(m.get("clobTokenIds"))
                    if len(clob_tokens) != 2:
                        continue

                    all_markets.append(
                        {
                            "condition_id": m.get("conditionId", ""),
                            "question": m.get("question", event.get("title", "Unknown")),
                            "slug": m.get("slug", event.get("slug", "")),
                            "yes_token": clob_tokens[0],
                            "no_token": clob_tokens[1],
                            "end_date": m.get("endDate", event.get("endDate")),
                            "outcomes": parse_json_field(m.get("outcomes")),
                            "series": series_list[0].get("slug", "") if series_list else "",
                            "accepting_orders": m.get("acceptingOrders", True),
                            "volume_24h": m.get("volume24hr", 0) or 0,
                        }
                    )

            if len(events) < 100:
                break
            offset += 100

            # Check max_markets limit
            if max_markets and len(all_markets) >= max_markets:
                all_markets = all_markets[:max_markets]
                break

        except requests.RequestException as e:
            logger.error("FETCH_EVENTS_ERROR", f"offset={offset} error={e}")
            break

    logger.info("FETCH_EVENTS_COMPLETE", f"found={len(all_markets)}")
    return all_markets


def fetch_all_markets(
    max_markets: int = 0,
    market_types: list[str] | None = None,
) -> list[dict]:
    """
    Fetch all active binary markets from Gamma API.

    Returns raw market data dicts.

    NOTE: This uses /markets endpoint which does NOT include restricted
    Up/Down markets. Use fetch_updown_events() for Up/Down markets.
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

                all_markets.append(
                    {
                        "condition_id": m.get("conditionId", ""),
                        "question": m.get("question", "Unknown"),
                        "slug": m.get("slug", ""),
                        "yes_token": clob_tokens[0],
                        "no_token": clob_tokens[1],
                        "end_date": m.get("endDate"),
                        "outcomes": parse_json_field(m.get("outcomes")),
                    }
                )

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
    market_types: list[str] | None = None,
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

        if len(outcomes) >= 2 and "down" in outcomes[0].lower():
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
    market_types: list[str] | None = None,
    max_markets: int = 0,
    candle_interval: str = "1h",
    assets: list[str] | None = None,
) -> MarketStateManager:
    """
    Fetch recently created Up/Down markets using /events endpoint.

    Args:
        max_age_hours: Prefer markets ending within this many hours
        fallback_age_hours: Fall back to markets ending within this many hours
        min_volume_24h: Minimum 24h volume filter
        market_types: DEPRECATED - use assets instead
        max_markets: Maximum markets to return
        candle_interval: "1h", "15m", or "5m"
        assets: List of assets e.g. ["bitcoin", "ethereum"]

    Returns:
        MarketStateManager with discovered markets
    """
    # Convert legacy market_types to assets if needed
    if assets is None and market_types:
        assets = []
        for mt in market_types:
            mt_lower = mt.lower()
            # Check all known aliases
            for asset, aliases in ASSET_ALIASES.items():
                if any(alias in mt_lower for alias in aliases):
                    if asset not in assets:
                        assets.append(asset)
                    break
        if not assets:
            assets = DEFAULT_ASSETS
    elif assets is None:
        assets = DEFAULT_ASSETS

    # Fetch from /events endpoint
    raw_markets = fetch_updown_events(
        candle_interval=candle_interval,
        assets=assets,
        max_markets=0,  # Don't limit yet, we'll filter first
    )

    now = datetime.now(UTC)
    cutoff_recent = now + timedelta(hours=max_age_hours)
    cutoff_fallback = now + timedelta(hours=fallback_age_hours)

    recent_markets = []
    fallback_markets = []

    for m in raw_markets:
        # Volume filter
        volume = m.get("volume_24h", 0) or 0
        if volume < min_volume_24h:
            continue

        # Must be accepting orders
        if not m.get("accepting_orders", True):
            continue

        # Time to resolution filter (prefer markets ending soon but not expired)
        end_date = parse_datetime(m.get("end_date"))
        if end_date:
            if end_date <= now:
                # Already expired, skip
                continue
            elif end_date <= cutoff_recent:
                recent_markets.append(m)
            elif end_date <= cutoff_fallback:
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

    # Build manager from events data
    return _build_manager_from_events(markets_to_use)


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


def _build_manager_from_events(markets: list[dict]) -> MarketStateManager:
    """Build MarketStateManager from events-based market data"""
    manager = MarketStateManager()

    for m in markets:
        yes_token = m.get("yes_token", "")
        no_token = m.get("no_token", "")
        outcomes = m.get("outcomes", [])

        # Determine UP vs DOWN
        up_token = yes_token
        down_token = no_token
        if len(outcomes) >= 2 and "down" in outcomes[0].lower():
            up_token, down_token = down_token, up_token

        state = MarketState(
            market_id=m.get("condition_id", ""),
            slug=m.get("slug", ""),
            question=m.get("question", "Unknown"),
            up_token_id=up_token,
            down_token_id=down_token,
            resolution_time=parse_datetime(m.get("end_date")),
        )
        manager.add_market(state)

    return manager
