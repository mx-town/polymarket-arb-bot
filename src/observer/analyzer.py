"""Trade analyzer — correlates trades into market windows and computes metrics."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from observer.models import (
    C_BOLD,
    C_DIM,
    C_GREEN,
    C_RESET,
    C_YELLOW,
    MarketWindow,
    ObservedMerge,
    ObservedTrade,
)

log = logging.getLogger("obs.analyzer")


class TradeAnalyzer:
    """Correlates trades into MarketWindow objects and computes strategy metrics."""

    def __init__(self) -> None:
        self._windows: dict[str, MarketWindow] = {}  # slug -> window
        self._closed: list[MarketWindow] = []

    def ingest_trades(self, trades: list[ObservedTrade]) -> None:
        """Add new trades and update their market windows."""
        for trade in trades:
            window = self._get_or_create_window(trade)
            window.trades.append(trade)
            window.last_trade_at = trade.timestamp
            if not window.first_trade_at:
                window.first_trade_at = trade.timestamp

            if trade.event_slug and not window.event_slug:
                window.event_slug = trade.event_slug
            if trade.title and not window.title:
                window.title = trade.title

            self._update_vwap(window, trade)
            self._update_status(window)

    def ingest_merges(self, merges: list[ObservedMerge]) -> None:
        """Associate merges with market windows by token_id matching."""
        for merge in merges:
            matched = False
            for window in self._windows.values():
                for trade in window.trades:
                    if trade.asset == merge.token_id:
                        window.merges.append(merge)
                        window.merged_shares += merge.shares
                        window.status = "MERGED"
                        matched = True
                        _log_window_merge(window, merge)
                        break
                if matched:
                    break

            if not matched:
                log.debug(
                    "MERGE_UNMATCHED │ token=%s tx=%s",
                    merge.token_id[:16], merge.tx_hash[:10],
                )

    def ingest_merge_from_position(self, slug: str, shares: float) -> None:
        """Record a merge detected from position changes (no token_id needed)."""
        window = self._windows.get(slug)
        if not window:
            log.debug("MERGE_NO_WINDOW │ slug=%s shares=%.2f", slug, shares)
            return
        window.merged_shares += shares
        window.status = "MERGED"
        mergeable = min(window.up_shares, window.down_shares)
        pnl = mergeable * window.estimated_edge if mergeable > 0 else 0.0
        log.info(
            "%sMERGE_WINDOW%s │ %s │ merged=%.1f │ pnl=$%.3f │ edge=%.3f",
            C_GREEN, C_RESET, window.slug, window.merged_shares, pnl, window.estimated_edge,
        )

    def get_window(self, slug: str) -> MarketWindow | None:
        return self._windows.get(slug)

    def get_all_windows(self) -> list[MarketWindow]:
        return list(self._windows.values())

    def get_closed_windows(self) -> list[MarketWindow]:
        return list(self._closed)

    def close_window(self, slug: str) -> MarketWindow | None:
        """Mark a window as CLOSED and move to the closed list."""
        window = self._windows.pop(slug, None)
        if window:
            window.status = "CLOSED"
            self._closed.append(window)
            _log_window_closed(window)
        return window

    @property
    def active_count(self) -> int:
        return len(self._windows)

    @property
    def closed_count(self) -> int:
        return len(self._closed)

    def summary(self) -> dict[str, Any]:
        """Return a summary of all windows for logging."""
        return {
            "active": self.active_count,
            "closed": self.closed_count,
            "windows": [_window_summary(w) for w in self._windows.values()],
        }

    def _get_or_create_window(self, trade: ObservedTrade) -> MarketWindow:
        if trade.slug not in self._windows:
            self._windows[trade.slug] = MarketWindow(slug=trade.slug)
            log.info(
                "%sWINDOW_OPEN%s │ %s │ %s",
                C_BOLD, C_RESET, trade.slug, trade.title,
            )
        return self._windows[trade.slug]

    def _update_vwap(self, window: MarketWindow, trade: ObservedTrade) -> None:
        """Update VWAP and cost tracking for the side of the trade."""
        if trade.side != "BUY":
            return

        if trade.outcome == "Up":
            window.up_cost += trade.price * trade.size
            window.up_shares += trade.size
            window.up_vwap = window.up_cost / window.up_shares if window.up_shares > 0 else 0.0
        elif trade.outcome == "Down":
            window.down_cost += trade.price * trade.size
            window.down_shares += trade.size
            if window.down_shares > 0:
                window.down_vwap = window.down_cost / window.down_shares

        window.combined_cost = window.up_cost + window.down_cost
        # Edge per merged pair = 1 - up_vwap - down_vwap (profit as fraction of $1 payout)
        # Old formula used combined_cost which includes unhedged excess shares
        if window.up_shares > 0 and window.down_shares > 0:
            window.estimated_edge = 1.0 - window.up_vwap - window.down_vwap
        else:
            window.estimated_edge = 0.0

    def _update_status(self, window: MarketWindow) -> None:
        """Update window status based on trade state."""
        has_up = any(t.outcome == "Up" and t.side == "BUY" for t in window.trades)
        has_down = any(t.outcome == "Down" and t.side == "BUY" for t in window.trades)

        if has_up and has_down and window.status == "OPEN":
            window.status = "HEDGED"
            window.hedge_delay_sec = _compute_hedge_delay(window)
            _log_window_hedged(window)


def _compute_hedge_delay(window: MarketWindow) -> float:
    """Compute seconds between first Up buy and first Down buy."""
    first_up: str = ""
    first_down: str = ""

    for t in window.trades:
        if t.side != "BUY":
            continue
        if t.outcome == "Up" and not first_up:
            first_up = t.timestamp
        elif t.outcome == "Down" and not first_down:
            first_down = t.timestamp

    if not first_up or not first_down:
        return 0.0

    try:
        # Activity API returns unix epoch as int (stored as str)
        if first_up.isdigit() and first_down.isdigit():
            return abs(int(first_down) - int(first_up))
        up_dt = datetime.fromisoformat(first_up.replace("Z", "+00:00"))
        down_dt = datetime.fromisoformat(first_down.replace("Z", "+00:00"))
        return abs((down_dt - up_dt).total_seconds())
    except (ValueError, TypeError, AttributeError):
        return 0.0


def _window_summary(window: MarketWindow) -> dict[str, Any]:
    return {
        "slug": window.slug,
        "status": window.status,
        "trades": len(window.trades),
        "up_shares": round(window.up_shares, 2),
        "down_shares": round(window.down_shares, 2),
        "up_vwap": round(window.up_vwap, 4),
        "down_vwap": round(window.down_vwap, 4),
        "combined_cost": round(window.combined_cost, 4),
        "estimated_edge": round(window.estimated_edge, 4),
        "hedge_delay_sec": round(window.hedge_delay_sec, 1),
        "merged_shares": round(window.merged_shares, 2),
    }


def _log_window_hedged(window: MarketWindow) -> None:
    log.info(
        "%sHEDGED%s │ %s │ up=%.1f@%.3f down=%.1f@%.3f │ cost=$%.2f edge=%.3f │ delay=%.1fs",
        C_YELLOW,
        C_RESET,
        window.slug,
        window.up_shares,
        window.up_vwap,
        window.down_shares,
        window.down_vwap,
        window.combined_cost,
        window.estimated_edge,
        window.hedge_delay_sec,
    )


def _log_window_merge(window: MarketWindow, merge: ObservedMerge) -> None:
    mergeable = min(window.up_shares, window.down_shares)
    pnl = mergeable * window.estimated_edge if mergeable > 0 else 0.0
    log.info(
        "%sMERGE_WINDOW%s │ %s │ merged=%.1f │ pnl=$%.3f │ edge=%.3f",
        C_GREEN,
        C_RESET,
        window.slug,
        window.merged_shares,
        pnl,
        window.estimated_edge,
    )


def _log_window_closed(window: MarketWindow) -> None:
    log.info(
        "%sWINDOW_CLOSED%s │ %s │ trades=%d up=%.1f down=%.1f merged=%.1f │ edge=%.3f",
        C_DIM,
        C_RESET,
        window.slug,
        len(window.trades),
        window.up_shares,
        window.down_shares,
        window.merged_shares,
        window.estimated_edge,
    )
