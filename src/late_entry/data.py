"""Market discovery and price fetching for 15m Up/Down markets."""

import json
import logging
from datetime import UTC, datetime

import requests

log = logging.getLogger("data")

GAMMA_HOST = "https://gamma-api.polymarket.com"

# Series IDs for 15m updown markets
SERIES_IDS = {
    "bitcoin": "10192",
    "ethereum": "10194",
}


def parse_json_field(value) -> list:
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
    if not value:
        return None
    try:
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        return datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None


def get_active_markets(assets: list[str]) -> list[dict]:
    """
    Fetch active 15m Up/Down markets for given assets.

    Returns list of dicts:
        {condition_id, question, slug, up_token, down_token, end_date, accepting_orders}
    """
    all_markets = []

    for asset in assets:
        series_id = SERIES_IDS.get(asset.lower())
        if not series_id:
            log.warning(f"NO_SERIES_ID asset={asset}")
            continue

        try:
            resp = requests.get(
                f"{GAMMA_HOST}/events",
                params={"series_id": series_id, "closed": "false", "limit": 5},
                timeout=15,
            )
            resp.raise_for_status()
            events = resp.json()
        except requests.RequestException as e:
            log.error(f"FETCH_ERROR asset={asset} error={e}")
            continue

        now = datetime.now(UTC)

        for event in events:
            for m in event.get("markets", []):
                clob_tokens = parse_json_field(m.get("clobTokenIds"))
                if len(clob_tokens) != 2:
                    continue

                if not m.get("acceptingOrders", True):
                    continue

                end_date = parse_datetime(m.get("endDate", event.get("endDate")))
                if not end_date or end_date <= now:
                    continue

                outcomes = parse_json_field(m.get("outcomes"))
                up_token = clob_tokens[0]
                down_token = clob_tokens[1]
                if len(outcomes) >= 2 and "down" in outcomes[0].lower():
                    up_token, down_token = down_token, up_token

                all_markets.append({
                    "condition_id": m.get("conditionId", ""),
                    "question": m.get("question", event.get("title", "Unknown")),
                    "slug": m.get("slug", event.get("slug", "")),
                    "up_token": up_token,
                    "down_token": down_token,
                    "end_date": end_date,
                    "asset": asset,
                })

    log.info(f"MARKETS_FOUND count={len(all_markets)}")
    return all_markets


def get_prices(client, token_id: str) -> dict | None:
    """
    Fetch best bid/ask for a token from the CLOB order book.

    Returns: {best_bid, best_ask} or None
    """
    try:
        book = client.get_order_book(token_id)
        bids = getattr(book, "bids", []) or []
        asks = getattr(book, "asks", []) or []

        best_bid = float(bids[0].price) if bids else 0.0
        best_ask = float(asks[0].price) if asks else 1.0

        return {"best_bid": best_bid, "best_ask": best_ask}
    except Exception as e:
        log.error(f"PRICE_ERROR token={token_id[:16]}... error={e}")
        return None


def get_market_prices(client, market: dict) -> dict | None:
    """
    Fetch prices for both sides of a market.

    Returns: {up_bid, up_ask, down_bid, down_ask} or None
    """
    up = get_prices(client, market["up_token"])
    down = get_prices(client, market["down_token"])

    if not up or not down:
        return None

    return {
        "up_bid": up["best_bid"],
        "up_ask": up["best_ask"],
        "down_bid": down["best_bid"],
        "down_ask": down["best_ask"],
    }
