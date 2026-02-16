"""Order book poller — fetches book snapshots for active token IDs."""

from __future__ import annotations

import logging
import time
from typing import Any

import requests

from observer.models import BookSnapshot

log = logging.getLogger("obs.book")

BOOKS_URL = "https://clob.polymarket.com/books"
BOOK_URL = "https://clob.polymarket.com/book"

# Polymarket CLOB rate limit: 50 requests per 10 seconds.
# Batch endpoint accepts up to 500 token_ids per request, so we rarely
# need multiple requests. Sleep between batches to stay under limit.
MAX_BATCH_SIZE = 500
MIN_REQUEST_INTERVAL = 0.2  # 5 req/s max


class BookPoller:
    """Polls the CLOB order book API for token snapshots."""

    def __init__(self) -> None:
        self._last_request_at: float = 0.0

    def poll(self, token_ids: list[str]) -> list[BookSnapshot]:
        """Fetch order book snapshots for the given token IDs.

        Uses the batch POST /books endpoint for efficiency (max 500 per call).
        Returns a list of BookSnapshot dataclass instances.
        """
        if not token_ids:
            return []

        snapshots: list[BookSnapshot] = []

        # Split into batches of MAX_BATCH_SIZE
        for i in range(0, len(token_ids), MAX_BATCH_SIZE):
            batch = token_ids[i : i + MAX_BATCH_SIZE]
            self._rate_limit()
            batch_snaps = self._fetch_batch(batch)
            snapshots.extend(batch_snaps)

        if snapshots:
            log.info(
                "BOOK_POLL │ requested=%d tokens │ received=%d snapshots",
                len(token_ids),
                len(snapshots),
            )
        else:
            log.debug("BOOK_POLL │ no snapshots for %d tokens", len(token_ids))

        return snapshots

    def _rate_limit(self) -> None:
        """Enforce minimum interval between requests."""
        now = time.monotonic()
        elapsed = now - self._last_request_at
        if elapsed < MIN_REQUEST_INTERVAL:
            time.sleep(MIN_REQUEST_INTERVAL - elapsed)
        self._last_request_at = time.monotonic()

    def _fetch_batch(self, token_ids: list[str]) -> list[BookSnapshot]:
        """Fetch a batch of books via POST /books."""
        body = [{"token_id": tid} for tid in token_ids]
        try:
            resp = requests.post(BOOKS_URL, json=body, timeout=10)
            resp.raise_for_status()
            items: list[dict[str, Any]] = resp.json()
        except (requests.ConnectionError, requests.Timeout) as exc:
            log.warning("BOOK_FETCH_FAIL │ %s", exc)
            return []
        except Exception as exc:
            log.debug("BOOK_FETCH_ERROR │ %s", exc)
            return []

        snapshots: list[BookSnapshot] = []
        now = time.time()
        for item in items:
            snap = _parse_book(item, now)
            if snap:
                snapshots.append(snap)
        return snapshots


def _parse_book(item: dict[str, Any], now: float) -> BookSnapshot | None:
    """Parse a CLOB book response into a BookSnapshot."""
    try:
        token_id = item.get("asset_id", "")
        if not token_id:
            return None

        bids = _parse_levels(item.get("bids", []))
        asks = _parse_levels(item.get("asks", []))

        if not bids and not asks:
            log.debug("BOOK_EMPTY │ token=%s", token_id[:12])
            return None

        best_bid = bids[0][0] if bids else 0.0
        best_ask = asks[0][0] if asks else 0.0
        spread = (best_ask - best_bid) if (best_bid > 0 and best_ask > 0) else 0.0
        mid_price = (best_bid + best_ask) / 2 if (best_bid > 0 and best_ask > 0) else 0.0

        # Depth within 10 cents of best bid/ask
        bid_depth_10c = sum(
            size for price, size in bids if price >= best_bid - 0.10
        ) if bids else 0.0
        ask_depth_10c = sum(
            size for price, size in asks if price <= best_ask + 0.10
        ) if asks else 0.0

        total_bid_size = sum(size for _, size in bids)
        total_ask_size = sum(size for _, size in asks)

        return BookSnapshot(
            token_id=token_id,
            timestamp=now,
            best_bid=best_bid,
            best_ask=best_ask,
            spread=round(spread, 4),
            mid_price=round(mid_price, 4),
            bid_depth_10c=round(bid_depth_10c, 2),
            ask_depth_10c=round(ask_depth_10c, 2),
            bid_levels=len(bids),
            ask_levels=len(asks),
            total_bid_size=round(total_bid_size, 2),
            total_ask_size=round(total_ask_size, 2),
        )
    except (ValueError, TypeError, KeyError) as exc:
        log.debug("BOOK_PARSE_FAIL │ %s │ item=%s", exc, item)
        return None


def _parse_levels(raw_levels: list[dict[str, str]]) -> list[tuple[float, float]]:
    """Parse bid/ask levels from API response.

    Returns list of (price, size) tuples sorted by price descending for bids,
    ascending for asks (matching API order).
    """
    levels: list[tuple[float, float]] = []
    for level in raw_levels:
        try:
            price = float(level.get("price", "0"))
            size = float(level.get("size", "0"))
            if price > 0 and size > 0:
                levels.append((price, size))
        except (ValueError, TypeError):
            continue
    return levels
