"""Directional position tracker — no merge/hedge, just hold-to-resolution."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from decimal import Decimal

from complete_set.events import EventType, emit
from complete_set.models import ZERO, Direction

log = logging.getLogger("tr.positions")


@dataclass
class TrendPosition:
    slug: str
    direction: Direction
    token_id: str
    shares: Decimal
    entry_price: Decimal
    cost: Decimal
    entered_at: float
    market_end_time: float


class TrendPositionTracker:
    def __init__(self):
        self._positions: dict[str, TrendPosition] = {}  # slug -> position
        self.session_realized_pnl: Decimal = ZERO

    def record_entry(
        self,
        slug: str,
        direction: Direction,
        token_id: str,
        shares: Decimal,
        price: Decimal,
        market_end_time: float,
    ) -> None:
        cost = price * shares
        pos = TrendPosition(
            slug=slug,
            direction=direction,
            token_id=token_id,
            shares=shares,
            entry_price=price,
            cost=cost,
            entered_at=time.time(),
            market_end_time=market_end_time,
        )
        self._positions[slug] = pos
        log.info(
            "TREND_POS_OPEN slug=%s dir=%s shares=%s @ %.2f cost=$%.2f",
            slug, direction.value, shares, price, cost,
        )

    def record_exit(self, slug: str, shares: Decimal, price: Decimal) -> None:
        """Record a stop-loss or early exit sell."""
        pos = self._positions.get(slug)
        if not pos:
            log.warning("TREND_POS_EXIT no position for slug=%s", slug)
            return
        proceeds = price * shares
        pnl = proceeds - pos.cost
        self.session_realized_pnl += pnl
        log.info(
            "TREND_POS_EXIT slug=%s dir=%s shares=%s exit=%.2f pnl=$%.2f",
            slug, pos.direction.value, shares, price, pnl,
        )
        emit(EventType.ORDER_FILLED, {
            "direction": pos.direction.value,
            "side": "SELL",
            "price": float(price),
            "shares": float(shares),
            "reason": "TREND_EXIT",
            "strategy": "trend_rider",
        }, market_slug=slug)
        del self._positions[slug]

    def clear_resolved(self, slug: str, won: bool) -> None:
        """Handle market resolution — position pays $1/share if won, $0 if lost."""
        pos = self._positions.get(slug)
        if not pos:
            return
        payout = pos.shares if won else ZERO
        pnl = payout - pos.cost
        self.session_realized_pnl += pnl
        log.info(
            "TREND_RESOLVED slug=%s dir=%s won=%s payout=$%.2f cost=$%.2f pnl=$%.2f",
            slug, pos.direction.value, won, payout, pos.cost, pnl,
        )
        emit(EventType.ORDER_FILLED, {
            "direction": pos.direction.value,
            "side": "RESOLVE",
            "price": float(1 if won else 0),
            "shares": float(pos.shares),
            "reason": "TREND_RESOLVED",
            "strategy": "trend_rider",
        }, market_slug=slug)
        del self._positions[slug]

    def total_exposure(self) -> Decimal:
        return sum((p.cost for p in self._positions.values()), ZERO)

    @property
    def position_count(self) -> int:
        return len(self._positions)

    def get_position(self, slug: str) -> TrendPosition | None:
        return self._positions.get(slug)

    def get_all_slugs(self) -> set[str]:
        return set(self._positions.keys())
