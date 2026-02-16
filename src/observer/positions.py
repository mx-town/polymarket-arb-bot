"""Positions API poller — tracks position changes via snapshot diffing."""

from __future__ import annotations

import logging
from typing import Any

import requests

from observer.models import C_GREEN, C_RESET, C_YELLOW, ObservedPosition

log = logging.getLogger("obs.positions")

POSITIONS_URL = "https://data-api.polymarket.com/positions"


class PositionPoller:
    """Polls the Positions API and diffs snapshots to detect changes."""

    def __init__(self, proxy_address: str, limit: int = 100) -> None:
        self._proxy = proxy_address
        self._limit = limit
        self._prev: dict[str, ObservedPosition] = {}  # asset -> position

    def poll(self) -> tuple[list[ObservedPosition], list[dict[str, Any]]]:
        """Fetch positions and return (current_positions, changes).

        Changes are dicts with keys: asset, slug, outcome, field, old, new.
        """
        try:
            resp = requests.get(
                POSITIONS_URL,
                params={"user": self._proxy, "limit": self._limit},
                timeout=10,
            )
            resp.raise_for_status()
            items: list[dict[str, Any]] = resp.json()
        except (requests.ConnectionError, requests.Timeout) as exc:
            log.warning("POS_POLL_FAIL │ %s", exc)
            return [], []
        except Exception as exc:
            log.debug("POS_POLL_ERROR │ %s", exc)
            return [], []

        current: dict[str, ObservedPosition] = {}
        for item in items:
            pos = _parse_position(item)
            if pos:
                current[pos.asset] = pos

        changes = _diff_positions(self._prev, current)
        for ch in changes:
            _log_change(ch)

        self._prev = current
        return list(current.values()), changes

    def snapshot(self) -> list[ObservedPosition]:
        """Take initial snapshot without diffing."""
        positions, _ = self.poll()
        log.info("SNAPSHOT │ %d positions tracked", len(positions))
        return positions

    @property
    def position_count(self) -> int:
        return len(self._prev)

    @property
    def active_token_ids(self) -> list[str]:
        """Return token_ids of all currently tracked positions."""
        ids = []
        for pos in self._prev.values():
            ids.append(pos.asset)
            if pos.opposite_asset:
                ids.append(pos.opposite_asset)
        return list(set(ids))


def _parse_position(item: dict[str, Any]) -> ObservedPosition | None:
    """Parse a Positions API item into an ObservedPosition."""
    try:
        return ObservedPosition(
            asset=item.get("asset", ""),
            size=float(item.get("size", 0)),
            avg_price=float(item.get("avgPrice", 0)),
            cash_pnl=float(item.get("cashPnl", 0)),
            current_value=float(item.get("currentValue", 0)),
            cur_price=float(item.get("curPrice", 0)),
            redeemable=bool(item.get("redeemable", False)),
            mergeable=bool(item.get("mergeable", False)),
            slug=item.get("slug", ""),
            outcome=item.get("outcome", ""),
            outcome_index=int(item.get("outcomeIndex", 0)),
            opposite_asset=item.get("oppositeAsset", ""),
            end_date=item.get("endDate", ""),
        )
    except (ValueError, TypeError) as exc:
        log.debug("POS_PARSE_FAIL │ %s │ item=%s", exc, item)
        return None


def _diff_positions(
    prev: dict[str, ObservedPosition],
    curr: dict[str, ObservedPosition],
) -> list[dict[str, Any]]:
    """Compare two snapshots and return a list of changes."""
    changes: list[dict[str, Any]] = []

    for asset, pos in curr.items():
        old = prev.get(asset)
        if old is None:
            changes.append({
                "asset": asset,
                "slug": pos.slug,
                "outcome": pos.outcome,
                "field": "NEW",
                "old": 0,
                "new": pos.size,
            })
            continue

        if abs(pos.size - old.size) > 0.01:
            changes.append({
                "asset": asset,
                "slug": pos.slug,
                "outcome": pos.outcome,
                "field": "size",
                "old": old.size,
                "new": pos.size,
            })
        if abs(pos.cash_pnl - old.cash_pnl) > 0.001:
            changes.append({
                "asset": asset,
                "slug": pos.slug,
                "outcome": pos.outcome,
                "field": "cash_pnl",
                "old": old.cash_pnl,
                "new": pos.cash_pnl,
            })
        if pos.mergeable != old.mergeable:
            changes.append({
                "asset": asset,
                "slug": pos.slug,
                "outcome": pos.outcome,
                "field": "mergeable",
                "old": int(old.mergeable),
                "new": int(pos.mergeable),
            })
        if pos.redeemable != old.redeemable:
            changes.append({
                "asset": asset,
                "slug": pos.slug,
                "outcome": pos.outcome,
                "field": "redeemable",
                "old": int(old.redeemable),
                "new": int(pos.redeemable),
            })

    for asset in prev:
        if asset not in curr:
            old = prev[asset]
            changes.append({
                "asset": asset,
                "slug": old.slug,
                "outcome": old.outcome,
                "field": "CLOSED",
                "old": old.size,
                "new": 0,
            })

    return changes


def detect_merges_from_changes(
    changes: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Detect merges and redemptions from position changes.

    Merges: both Up and Down sides decrease simultaneously (complete-set merge).
    Redemptions: single-sided decreases (winning position cashed out after resolution).

    Returns (merges, redemptions) where each is a list of dicts with keys:
      merges: {slug, shares}
      redemptions: {slug, outcome, shares, from_size, to_size}
    """
    # Collect size decreases by slug+outcome, keeping old/new for redemption records
    decreases: dict[str, dict[str, float]] = {}  # slug -> {outcome -> decrease}
    size_info: dict[str, dict[str, tuple[float, float]]] = {}  # slug -> {outcome -> (old, new)}
    for ch in changes:
        if ch["field"] != "size":
            continue
        delta = ch["new"] - ch["old"]
        if delta >= 0:
            continue
        slug = ch["slug"]
        outcome = ch["outcome"]
        if slug not in decreases:
            decreases[slug] = {}
            size_info[slug] = {}
        decreases[slug][outcome] = abs(delta)
        size_info[slug][outcome] = (ch["old"], ch["new"])

    merges: list[dict[str, Any]] = []
    redemptions: list[dict[str, Any]] = []
    for slug, sides in decreases.items():
        up_dec = sides.get("Up", 0.0)
        down_dec = sides.get("Down", 0.0)
        if up_dec > 0 and down_dec > 0:
            # Both sides decreased — complete-set merge
            merged = min(up_dec, down_dec)
            merges.append({"slug": slug, "shares": merged})
            log.info(
                "%sMERGE_DETECTED%s │ %s │ shares=%.2f (up -%.2f, down -%.2f)",
                C_GREEN, C_RESET, slug, merged, up_dec, down_dec,
            )
        else:
            # Single-sided decrease — redemption of winning position
            for outcome, dec in sides.items():
                old_size, new_size = size_info[slug][outcome]
                redemptions.append({
                    "slug": slug,
                    "outcome": outcome,
                    "shares": dec,
                    "from_size": old_size,
                    "to_size": new_size,
                })
                log.info(
                    "%sREDEMPTION_DETECTED%s │ %s │ %s │ shares=%.2f (%.2f → %.2f)",
                    C_YELLOW, C_RESET, slug, outcome, dec, old_size, new_size,
                )

    return merges, redemptions


def _log_change(ch: dict[str, Any]) -> None:
    """Log a position change."""
    log.info(
        "%sPOS_CHANGE%s │ %s │ %s │ %s: %.2f → %.2f",
        C_YELLOW,
        C_RESET,
        ch["slug"],
        ch["outcome"],
        ch["field"],
        ch["old"],
        ch["new"],
    )
