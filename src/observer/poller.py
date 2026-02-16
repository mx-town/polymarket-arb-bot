"""Activity API poller — polls trade activity for the target wallet."""

from __future__ import annotations

import logging
from typing import Any

import requests

from observer.models import C_GREEN, C_RED, C_RESET, ObservedTrade

log = logging.getLogger("obs.poller")

ACTIVITY_URL = "https://data-api.polymarket.com/activity"


class ActivityPoller:
    """Polls the Activity API and yields new trades, deduplicating by txHash."""

    def __init__(self, proxy_address: str, limit: int = 50) -> None:
        self._proxy = proxy_address
        self._limit = limit
        self._seen_tx: set[str] = set()

    def poll(self) -> list[ObservedTrade]:
        """Fetch recent activity and return only new (unseen) trades."""
        try:
            resp = requests.get(
                ACTIVITY_URL,
                params={"user": self._proxy, "limit": self._limit},
                timeout=10,
            )
            resp.raise_for_status()
            items: list[dict[str, Any]] = resp.json()
        except (requests.ConnectionError, requests.Timeout) as exc:
            log.warning("POLL_FAIL │ %s", exc)
            return []
        except Exception as exc:
            log.debug("POLL_ERROR │ %s", exc)
            return []

        new_trades: list[ObservedTrade] = []
        for item in items:
            tx = item.get("transactionHash", "")
            if not tx or tx in self._seen_tx:
                continue
            self._seen_tx.add(tx)
            trade = _parse_trade(item)
            if trade:
                new_trades.append(trade)
                _log_trade(trade)

        return new_trades

    def backfill(self) -> list[ObservedTrade]:
        """Initial backfill — same as poll but logs differently."""
        log.info("BACKFILL │ fetching last %d activities", self._limit)
        trades = self.poll()
        if trades:
            log.info("BACKFILL │ loaded %d historical trades", len(trades))
        return trades

    @property
    def seen_count(self) -> int:
        return len(self._seen_tx)


def _parse_trade(item: dict[str, Any]) -> ObservedTrade | None:
    """Parse an Activity API item into an ObservedTrade."""
    try:
        return ObservedTrade(
            timestamp=str(item.get("timestamp", "")),
            side=item.get("side", ""),
            price=float(item.get("price", 0)),
            size=float(item.get("size", 0)),
            usdc_size=float(item.get("usdcSize", 0)),
            outcome=item.get("outcome", ""),
            outcome_index=int(item.get("outcomeIndex", 0)),
            tx_hash=item.get("transactionHash", ""),
            slug=item.get("slug", ""),
            event_slug=item.get("eventSlug", ""),
            condition_id=item.get("conditionId", ""),
            asset=item.get("asset", ""),
            title=item.get("title", ""),
        )
    except (ValueError, TypeError) as exc:
        log.debug("PARSE_FAIL │ %s │ item=%s", exc, item)
        return None


def _log_trade(trade: ObservedTrade) -> None:
    """Log a newly observed trade with colors."""
    color = C_GREEN if trade.side == "BUY" else C_RED
    log.info(
        "%sFILL%s │ %s %s │ %s │ price=%.2f size=%.1f usdc=$%.2f │ tx=%s",
        color,
        C_RESET,
        trade.side,
        trade.outcome,
        trade.slug,
        trade.price,
        trade.size,
        trade.usdc_size,
        trade.tx_hash[:10],
    )
