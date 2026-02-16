"""Async batch writer — buffers observer data and flushes to SQLite periodically.

Never blocks the poll loop. Data arrives via typed enqueue methods, flushed every
2s via asyncio.to_thread().
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from sqlalchemy import Table

from observer.models import (
    MarketWindow,
    ObservedMerge,
    ObservedPosition,
    ObservedTrade,
)
from observer.persistence.db import get_engine
from observer.persistence.schema import (
    obs_market_windows,
    obs_merges,
    obs_position_changes,
    obs_positions,
    obs_trades,
)

log = logging.getLogger("obs.persistence.writer")

FLUSH_INTERVAL_SEC = 2.0


class ObserverWriter:
    def __init__(self, session_id: str):
        self._session_id = session_id
        self._buffer: list[tuple[Table, dict]] = []
        self._lock = asyncio.Lock()
        self._known_window_slugs: set[str] = set()
        self._total_written: int = 0
        self._total_flushed: int = 0

    async def enqueue_trades(self, trades: list[ObservedTrade]) -> None:
        if not trades:
            return
        rows = []
        for t in trades:
            rows.append((obs_trades, {
                "ts": _parse_ts(t.timestamp),
                "side": t.side,
                "price": t.price,
                "size": t.size,
                "usdc_size": t.usdc_size,
                "outcome": t.outcome,
                "outcome_index": t.outcome_index,
                "tx_hash": t.tx_hash,
                "slug": t.slug,
                "event_slug": t.event_slug,
                "condition_id": t.condition_id,
                "asset": t.asset,
                "title": t.title,
                "role": t.role,
                "session_id": self._session_id,
            }))
        async with self._lock:
            self._buffer.extend(rows)

    async def enqueue_merges(self, merges: list[ObservedMerge]) -> None:
        if not merges:
            return
        rows = []
        for m in merges:
            rows.append((obs_merges, {
                "ts": _parse_ts(m.timestamp),
                "tx_hash": m.tx_hash,
                "token_id": m.token_id,
                "shares": m.shares,
                "block_number": m.block_number,
                "session_id": self._session_id,
            }))
        async with self._lock:
            self._buffer.extend(rows)

    async def enqueue_detected_merge(self, slug: str, shares: float) -> None:
        """Queue a merge detected from position changes (synthetic, no tx_hash)."""
        if shares <= 0:
            return
        now = time.time()
        row = {
            "ts": now,
            "tx_hash": f"pos_merge_{slug}_{now:.0f}",
            "token_id": "",
            "shares": shares,
            "block_number": 0,
            "session_id": self._session_id,
        }
        async with self._lock:
            self._buffer.append((obs_merges, row))

    async def enqueue_positions(self, positions: list[ObservedPosition]) -> None:
        if not positions:
            return
        now = time.time()
        rows = []
        for p in positions:
            rows.append((obs_positions, {
                "ts": now,
                "asset": p.asset,
                "size": p.size,
                "avg_price": p.avg_price,
                "cash_pnl": p.cash_pnl,
                "current_value": p.current_value,
                "cur_price": p.cur_price,
                "mergeable": int(p.mergeable),
                "redeemable": int(p.redeemable),
                "slug": p.slug,
                "outcome": p.outcome,
                "session_id": self._session_id,
            }))
        async with self._lock:
            self._buffer.extend(rows)

    async def enqueue_position_changes(self, changes: list[dict]) -> None:
        if not changes:
            return
        now = time.time()
        rows = []
        for ch in changes:
            rows.append((obs_position_changes, {
                "ts": now,
                "asset": ch.get("asset", ""),
                "slug": ch.get("slug", ""),
                "outcome": ch.get("outcome", ""),
                "field": ch.get("field", ""),
                "old_val": ch.get("old", 0),
                "new_val": ch.get("new", 0),
                "session_id": self._session_id,
            }))
        async with self._lock:
            self._buffer.extend(rows)

    async def enqueue_market_windows(self, windows: list[MarketWindow]) -> None:
        if not windows:
            return
        async with self._lock:
            for w in windows:
                row = {
                    "slug": w.slug,
                    "event_slug": w.event_slug,
                    "title": w.title,
                    "status": w.status,
                    "up_vwap": w.up_vwap,
                    "down_vwap": w.down_vwap,
                    "up_shares": w.up_shares,
                    "down_shares": w.down_shares,
                    "combined_cost": w.combined_cost,
                    "estimated_edge": w.estimated_edge,
                    "hedge_delay_sec": w.hedge_delay_sec,
                    "merged_shares": w.merged_shares,
                    "first_trade_at": w.first_trade_at,
                    "last_trade_at": w.last_trade_at,
                    "session_id": self._session_id,
                }
                if w.slug in self._known_window_slugs:
                    # Mark for update (slug, values)
                    self._buffer.append(("__update_window__", row))
                else:
                    self._buffer.append((obs_market_windows, row))
                    self._known_window_slugs.add(w.slug)

    async def update_trade_role(self, tx_hash: str, role: str) -> None:
        """Queue a role update for a specific trade by tx_hash."""
        if not tx_hash or not role:
            return
        async with self._lock:
            self._buffer.append(("__update_role__", {
                "tx_hash": tx_hash,
                "role": role,
            }))

    async def run_flush_loop(self) -> None:
        """Periodically flush buffered rows to database. Runs forever."""
        while True:
            await asyncio.sleep(FLUSH_INTERVAL_SEC)
            await self._flush()

    async def _flush(self) -> None:
        async with self._lock:
            if not self._buffer:
                return
            batch = self._buffer[:]
            self._buffer.clear()

        try:
            count = await asyncio.to_thread(self._write_batch, batch)
            self._total_written += count
            self._total_flushed += 1
        except Exception as e:
            log.error("DB_WRITE │ flush failed (%d items): %s", len(batch), e)

    def _write_batch(self, batch: list[tuple]) -> int:
        """Synchronous batch insert + updates. Runs in thread pool."""
        engine = get_engine()

        # Separate inserts, window updates, and role updates
        by_table: dict[str, list[dict]] = {}
        table_map: dict[str, Table] = {}
        window_updates: list[dict] = []
        role_updates: list[dict] = []

        for table_or_tag, row in batch:
            if table_or_tag == "__update_window__":
                window_updates.append(row)
            elif table_or_tag == "__update_role__":
                role_updates.append(row)
            else:
                key = table_or_tag.name
                if key not in by_table:
                    by_table[key] = []
                    table_map[key] = table_or_tag
                by_table[key].append(row)

        total = 0
        with engine.begin() as conn:
            for name, rows in by_table.items():
                table = table_map[name]
                # Normalize keys across batch
                all_keys: set[str] = set()
                for r in rows:
                    all_keys.update(r.keys())
                normalized = [{k: r.get(k) for k in all_keys} for r in rows]

                if name in ("obs_trades", "obs_merges"):
                    # INSERT OR IGNORE for idempotent restarts
                    conn.execute(
                        table.insert().prefix_with("OR IGNORE"),
                        normalized,
                    )
                else:
                    conn.execute(table.insert(), normalized)
                total += len(rows)

            for vals in window_updates:
                slug = vals["slug"]
                update_vals = {k: v for k, v in vals.items() if k != "slug" and k != "session_id"}
                conn.execute(
                    obs_market_windows.update()
                    .where(obs_market_windows.c.slug == slug)
                    .where(obs_market_windows.c.session_id == vals["session_id"])
                    .values(**update_vals)
                )
                total += 1

            for vals in role_updates:
                conn.execute(
                    obs_trades.update()
                    .where(obs_trades.c.tx_hash == vals["tx_hash"])
                    .values(role=vals["role"])
                )
                total += 1

        return total

    @property
    def stats(self) -> dict:
        return {
            "total_written": self._total_written,
            "total_flushed": self._total_flushed,
            "buffer_size": len(self._buffer),
        }


def _parse_ts(value) -> float:
    """Convert Activity API timestamps (str/int) to float epoch."""
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        if value.isdigit():
            return float(value)
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return dt.timestamp()
        except (ValueError, TypeError):
            pass
    return time.time()
