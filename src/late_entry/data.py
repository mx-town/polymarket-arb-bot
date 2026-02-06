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
    "ethereum": "10191",
    "solana": "10423",
    "xrp": "10422",
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
                params={"series_id": series_id, "closed": "false", "limit": 2},
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

                # Parse Gamma prices
                outcome_prices = parse_json_field(m.get("outcomePrices"))
                if len(outcome_prices) != 2:
                    continue
                up_price = float(outcome_prices[0])
                down_price = float(outcome_prices[1])
                # Swap if outcomes are reversed
                if len(outcomes) >= 2 and "down" in outcomes[0].lower():
                    up_price, down_price = down_price, up_price

                all_markets.append({
                    "condition_id": m.get("conditionId", ""),
                    "question": m.get("question", event.get("title", "Unknown")),
                    "slug": m.get("slug", event.get("slug", "")),
                    "up_token": up_token,
                    "down_token": down_token,
                    "end_date": end_date,
                    "asset": asset,
                    "up_price": up_price,
                    "down_price": down_price,
                    "best_bid": float(m.get("bestBid", 0)),
                    "best_ask": float(m.get("bestAsk", 1)),
                    "spread": float(m.get("spread", 1)),
                })

    # Only log markets within ~5 minutes (actionable soon)
    now = datetime.now(UTC)
    nearby = [m for m in all_markets if (m["end_date"] - now).total_seconds() <= 300]
    if nearby:
        for m in nearby:
            secs_left = (m["end_date"] - now).total_seconds()
            mins, secs = divmod(int(secs_left), 60)
            fav = "UP" if m["up_price"] > m["down_price"] else "DN"
            spread = abs(m["up_price"] - m["down_price"])
            log.info(
                f"  {m['asset'].upper():>5} │ {m['slug'][:40]:<40} │ "
                f"{mins}m{secs:02d}s │ U={m['up_price']:.3f} D={m['down_price']:.3f} "
                f"│ {fav} +{spread:.1%}"
            )
    else:
        log.info(f"  {len(all_markets)} markets tracked, none within 5m yet")
    return all_markets


def get_market_prices(market: dict) -> dict:
    """
    Extract Gamma outcome prices already embedded in the market dict.

    Returns: {up_price, down_price, best_bid, best_ask, spread}
    """
    return {
        "up_price": market["up_price"],
        "down_price": market["down_price"],
        "best_bid": market.get("best_bid", 0),
        "best_ask": market.get("best_ask", 1),
        "spread": market.get("spread", 1),
    }
