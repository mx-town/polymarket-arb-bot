"""Async batch writer — buffers events and flushes to SQLite periodically.

Never blocks the engine tick. Events arrive via enqueue(), flushed every 2s
or 500 rows via asyncio.to_thread().
"""

from __future__ import annotations

import asyncio
import logging
import time

from sqlalchemy import Table

from complete_set.events import Event, EventType
from complete_set.persistence.db import get_engine
from complete_set.persistence.schema import (
    btc_prices,
    market_windows,
    pnl_snapshots,
    probability_snapshots,
    trades,
)

log = logging.getLogger("cs.persistence.writer")

FLUSH_INTERVAL_SEC = 2.0
FLUSH_THRESHOLD_ROWS = 500


class BatchWriter:
    def __init__(self, session_id: str):
        self._session_id = session_id
        self._buffer: list[tuple[Table, dict]] = []
        self._pending_updates: list[tuple[Table, dict, str]] = []  # (table, values, slug)
        self._lock = asyncio.Lock()
        self._last_prob_ts: dict[str, float] = {}  # slug -> last written ts (1/sec dedup)
        self._total_written: int = 0
        self._total_flushed: int = 0

    async def enqueue(self, event: Event) -> None:
        """Convert event to table rows and buffer them."""
        rows = self._event_to_rows(event)
        if not rows:
            return
        async with self._lock:
            self._buffer.extend(rows)

    async def run_flush_loop(self) -> None:
        """Periodically flush buffered rows to database. Runs forever."""
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SEC)
            await self._flush()

    async def _flush(self) -> None:
        """Flush buffer to database in a thread pool."""
        async with self._lock:
            if not self._buffer and not self._pending_updates:
                return
            batch = self._buffer[:]
            self._buffer.clear()
            updates = self._pending_updates[:]
            self._pending_updates.clear()

        try:
            count = await asyncio.to_thread(self._write_batch, batch, updates)
            self._total_written += count
            self._total_flushed += 1
        except Exception as e:
            log.error("DB_WRITE │ flush failed (%d rows): %s", len(batch), e)

    def _write_batch(
        self,
        batch: list[tuple[Table, dict]],
        updates: list[tuple[Table, dict, str]] | None = None,
    ) -> int:
        """Synchronous batch insert + updates. Runs in thread pool."""
        engine = get_engine()
        by_table: dict[str, list[dict]] = {}
        table_map: dict[str, Table] = {}

        for table, row in batch:
            key = table.name
            if key not in by_table:
                by_table[key] = []
                table_map[key] = table
            by_table[key].append(row)

        total = 0
        with engine.begin() as conn:
            for name, rows in by_table.items():
                conn.execute(table_map[name].insert(), rows)
                total += len(rows)

            for table, values, slug in (updates or []):
                conn.execute(
                    table.update().where(table.c.slug == slug).values(**values)
                )
                total += 1

        return total

    def _event_to_rows(self, event: Event) -> list[tuple[Table, dict]]:
        """Map an Event to zero or more (table, row_dict) pairs."""
        t = event.type
        d = event.data
        ts = event.timestamp

        if t == EventType.BTC_PRICE:
            return [(btc_prices, {
                "ts": ts,
                "price": d.get("price"),
                "open_price": d.get("open"),
                "high": d.get("high"),
                "low": d.get("low"),
                "deviation": d.get("deviation"),
                "range_pct": d.get("range_pct"),
                "session_id": self._session_id,
            })]

        if t == EventType.TICK_SNAPSHOT:
            rows = []
            for m in d.get("markets", []):
                slug = m.get("slug", "")
                # Deduplicate: max 1 probability snapshot per second per market
                ts_sec = int(ts)
                last = self._last_prob_ts.get(slug, 0)
                if ts_sec <= last:
                    continue
                self._last_prob_ts[slug] = ts_sec
                rows.append((probability_snapshots, {
                    "ts": ts,
                    "market_slug": slug,
                    "up_bid": m.get("up_bid"),
                    "up_ask": m.get("up_ask"),
                    "down_bid": m.get("down_bid"),
                    "down_ask": m.get("down_ask"),
                    "edge": m.get("edge"),
                    "up_bid_size": m.get("up_bid_size"),
                    "up_ask_size": m.get("up_ask_size"),
                    "down_bid_size": m.get("down_bid_size"),
                    "down_ask_size": m.get("down_ask_size"),
                    "session_id": self._session_id,
                }))
            return rows

        if t in (EventType.ORDER_PLACED, EventType.ORDER_FILLED, EventType.ORDER_CANCELLED):
            return [(trades, {
                "ts": ts,
                "market_slug": event.market_slug,
                "event_type": t.value,
                "direction": d.get("direction"),
                "side": d.get("side"),
                "price": d.get("price"),
                "shares": d.get("shares"),
                "reason": d.get("reason"),
                "btc_price_at": d.get("btc_price_at"),
                "order_id": d.get("order_id"),
                "session_id": self._session_id,
                "strategy": d.get("strategy", "complete_set"),
            })]

        if t == EventType.HEDGE_COMPLETE:
            return [(trades, {
                "ts": ts,
                "market_slug": event.market_slug,
                "event_type": "hedge_complete",
                "direction": d.get("direction"),
                "price": d.get("edge"),
                "shares": d.get("hedged_shares"),
                "session_id": self._session_id,
                "strategy": d.get("strategy", "complete_set"),
            })]

        if t == EventType.MERGE_COMPLETE:
            return [(trades, {
                "ts": ts,
                "market_slug": event.market_slug,
                "event_type": "merge_complete",
                "shares": d.get("merged_shares"),
                "tx_hash": d.get("tx_hash"),
                "session_id": self._session_id,
                "strategy": d.get("strategy", "complete_set"),
            })]

        if t == EventType.PNL_SNAPSHOT:
            return [(pnl_snapshots, {
                "ts": ts,
                "realized": d.get("realized"),
                "unrealized": d.get("unrealized"),
                "total": d.get("total"),
                "exposure": d.get("exposure"),
                "exposure_pct": d.get("exposure_pct"),
                "session_id": self._session_id,
            })]

        if t == EventType.MARKET_ENTERED:
            return [(market_windows, {
                "slug": event.market_slug,
                "market_type": d.get("market_type"),
                "end_time": d.get("end_time"),
                "up_token_id": d.get("up_token_id"),
                "down_token_id": d.get("down_token_id"),
                "entered_at": ts,
                "session_id": self._session_id,
            })]

        if t == EventType.MARKET_EXITED:
            self._pending_updates.append((
                market_windows,
                {"exited_at": ts, "outcome": d.get("outcome"), "total_pnl": d.get("total_pnl")},
                event.market_slug,
            ))
            return []

        return []

    @property
    def stats(self) -> dict:
        return {
            "total_written": self._total_written,
            "total_flushed": self._total_flushed,
            "buffer_size": len(self._buffer),
        }
