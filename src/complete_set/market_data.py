"""Market discovery via Gamma API + CLOB order book polling.

Discovery reuses the Gamma API pattern from late_entry/data.py.
TOB polling uses py-clob-client's get_order_book().
"""

from __future__ import annotations

import json
import logging
import time
from datetime import UTC, datetime, timezone
from decimal import Decimal
from typing import Optional

import requests
from zoneinfo import ZoneInfo

from complete_set.models import GabagoolMarket, TopOfBook

log = logging.getLogger("cs.market_data")

GAMMA_HOST = "https://gamma-api.polymarket.com"
ET = ZoneInfo("America/New_York")


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------

def _candidate_15m_slugs(asset_prefix: str, now_epoch: float) -> list[str]:
    """Generate candidate slugs for 15m updown markets.

    Format: {asset}-updown-15m-{epoch} where epoch aligns to 900s boundaries.
    """
    now_sec = int(now_epoch)
    start = (now_sec // 900) * 900
    # Cover current + next + previous window
    return [
        f"{asset_prefix}-updown-15m-{epoch}"
        for epoch in range(start - 900, start + 1800 + 1, 900)
    ]


def _candidate_1h_slugs(asset_prefix: str, now_epoch: float) -> list[str]:
    """Generate candidate slugs for 1h up-or-down markets.

    Format: {asset}-up-or-down-{month}-{day}-{hour}{ampm}-et
    """
    dt_et = datetime.fromtimestamp(now_epoch, tz=ET)
    hour_start = dt_et.replace(minute=0, second=0, microsecond=0)

    slugs = []
    for delta_h in (-2, -1, 0, 1):
        from datetime import timedelta
        candidate = hour_start + timedelta(hours=delta_h)
        month = candidate.strftime("%B").lower()
        day = candidate.day
        hour24 = candidate.hour
        hour12 = hour24 % 12
        if hour12 == 0:
            hour12 = 12
        ampm = "am" if hour24 < 12 else "pm"
        slugs.append(f"{asset_prefix}-up-or-down-{month}-{day}-{hour12}{ampm}-et")

    return slugs


# Mapping from config asset name to slug prefix
_ASSET_PREFIXES_15M = {
    "bitcoin": "btc",
    "ethereum": "eth",
}

_ASSET_PREFIXES_1H = {
    "bitcoin": "bitcoin",
    "ethereum": "ethereum",
}


# ---------------------------------------------------------------------------
# Gamma API fetch
# ---------------------------------------------------------------------------

def _parse_json_field(value) -> list:
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


def _fetch_market_by_slug(slug: str) -> Optional[GabagoolMarket]:
    """Fetch market details from Gamma API by slug."""
    try:
        resp = requests.get(
            f"{GAMMA_HOST}/events",
            params={"slug": slug},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        events = resp.json()
        if not events:
            return None

        event = events[0]
        if event.get("closed", False):
            return None

        # Determine market type
        event_slug = event.get("slug", slug)
        if "updown-15m" in event_slug:
            market_type = "updown-15m"
        elif "up-or-down" in event_slug:
            market_type = "up-or-down"
        else:
            return None

        # Parse end time
        end_time = _parse_end_time(event, event_slug, market_type)
        if end_time is None:
            return None

        # Get first market's tokens
        markets = event.get("markets", [])
        if not markets:
            return None
        first_market = markets[0]

        token_ids = _parse_json_field(first_market.get("clobTokenIds"))
        outcomes = _parse_json_field(first_market.get("outcomes"))

        up_token = None
        down_token = None
        for i, outcome in enumerate(outcomes):
            if i >= len(token_ids):
                break
            token_id = token_ids[i]
            if not token_id:
                continue
            outcome_lower = outcome.lower().strip()
            if outcome_lower == "up":
                up_token = token_id
            elif outcome_lower == "down":
                down_token = token_id

        if not up_token or not down_token:
            return None

        return GabagoolMarket(
            slug=event_slug,
            up_token_id=up_token,
            down_token_id=down_token,
            end_time=end_time,
            market_type=market_type,
        )

    except Exception as e:
        log.debug("Error fetching market %s: %s", slug, e)
        return None


def _parse_end_time(event: dict, slug: str, market_type: str) -> Optional[float]:
    """Parse end time from event data or slug."""
    end_date_str = event.get("endDate")
    if end_date_str:
        try:
            if end_date_str.endswith("Z"):
                end_date_str = end_date_str[:-1] + "+00:00"
            dt = datetime.fromisoformat(end_date_str)
            return dt.timestamp()
        except (ValueError, TypeError):
            pass

    # Fallback: parse from slug for 15m markets
    if market_type == "updown-15m":
        parts = slug.split("-")
        if len(parts) >= 4:
            try:
                epoch = int(parts[-1])
                return float(epoch + 900)  # +15 minutes
            except ValueError:
                pass
    return None


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------

def discover_markets(assets: tuple[str, ...]) -> list[GabagoolMarket]:
    """Discover active Up/Down markets for given assets via Gamma API."""
    now = time.time()
    markets: list[GabagoolMarket] = []
    seen_slugs: set[str] = set()

    for asset in assets:
        # 15m markets
        prefix_15m = _ASSET_PREFIXES_15M.get(asset)
        if prefix_15m:
            for slug in _candidate_15m_slugs(prefix_15m, now):
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)
                market = _fetch_market_by_slug(slug)
                if market and market.end_time > now:
                    markets.append(market)

        # 1h markets
        prefix_1h = _ASSET_PREFIXES_1H.get(asset)
        if prefix_1h:
            for slug in _candidate_1h_slugs(prefix_1h, now):
                if slug in seen_slugs:
                    continue
                seen_slugs.add(slug)
                market = _fetch_market_by_slug(slug)
                if market and market.end_time > now:
                    markets.append(market)

    if markets:
        log.info("Discovered %d active markets", len(markets))
        for m in markets:
            secs = int(m.end_time - now)
            mins, secs_r = divmod(secs, 60)
            log.info("  %s │ %s │ %dm%02ds", m.market_type, m.slug[:50], mins, secs_r)

    return markets


# ---------------------------------------------------------------------------
# TOB polling via CLOB
# ---------------------------------------------------------------------------

def _extract_price(entry) -> Optional[Decimal]:
    """Extract price from an OrderSummary object or dict."""
    if isinstance(entry, dict):
        raw = entry.get("price")
    else:
        raw = getattr(entry, "price", None)
    if raw is None:
        return None
    return Decimal(str(raw))


def _extract_size(entry) -> Optional[Decimal]:
    """Extract size from an OrderSummary object or dict."""
    if isinstance(entry, dict):
        raw = entry.get("size")
    else:
        raw = getattr(entry, "size", None)
    if raw is None:
        return None
    return Decimal(str(raw))


def get_top_of_book(client, token_id: str) -> Optional[TopOfBook]:
    """Fetch top-of-book from CLOB order book endpoint.

    Uses py-clob-client's client.get_order_book(token_id).
    Returns None if both sides are empty.
    """
    try:
        book = client.get_order_book(token_id)

        if isinstance(book, dict):
            bids = book.get("bids") or []
            asks = book.get("asks") or []
        else:
            bids = getattr(book, "bids", None) or []
            asks = getattr(book, "asks", None) or []

        # Sort: bids descending by price, asks ascending by price.
        # Server usually returns sorted, but py-clob-client doesn't guarantee it.
        bids = sorted(bids, key=lambda e: _extract_price(e) or Decimal(0), reverse=True)
        asks = sorted(asks, key=lambda e: _extract_price(e) or Decimal("999"), reverse=False)

        best_bid = _extract_price(bids[0]) if bids else None
        best_bid_size = _extract_size(bids[0]) if bids else None
        best_ask = _extract_price(asks[0]) if asks else None
        best_ask_size = _extract_size(asks[0]) if asks else None

        log.debug(
            "BOOK %s │ %d bids / %d asks │ best=%s/%s │ spread=%s",
            token_id[:16],
            len(bids), len(asks),
            best_bid, best_ask,
            (best_ask - best_bid) if best_bid is not None and best_ask is not None else "?",
        )

        if best_bid is None and best_ask is None:
            return None

        return TopOfBook(
            best_bid=best_bid,
            best_ask=best_ask,
            best_bid_size=best_bid_size,
            best_ask_size=best_ask_size,
            updated_at=time.time(),
        )

    except Exception as e:
        log.debug("Error fetching order book for %s: %s", token_id, e)
        return None
