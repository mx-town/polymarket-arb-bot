"""Event bus — thread-safe, non-blocking pub/sub for dashboard data pipeline.

The engine tick loop runs in a thread pool via asyncio.to_thread(). Events are
emitted with put_nowait() which is thread-safe and never blocks the tick.

Consumer runs on the main asyncio event loop and fans out to WebSocket broadcast
and persistence writer.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

log = logging.getLogger("cs.events")

# Module-level queue — initialized by init_event_bus(), None until then.
_queue: asyncio.Queue | None = None
_drop_count: int = 0

MAX_QUEUE_SIZE = 10_000


class EventType(str, Enum):
    TICK_SNAPSHOT = "tick_snapshot"
    BTC_PRICE = "btc_price"
    VOLUME_STATE = "volume_state"
    ORDER_PLACED = "order_placed"
    ORDER_FILLED = "order_filled"
    ORDER_CANCELLED = "order_cancelled"
    HEDGE_COMPLETE = "hedge_complete"
    MERGE_COMPLETE = "merge_complete"
    MARKET_ENTERED = "market_entered"
    MARKET_EXITED = "market_exited"
    PNL_SNAPSHOT = "pnl_snapshot"


@dataclass(frozen=True)
class Event:
    type: EventType
    timestamp: float
    data: dict[str, Any] = field(default_factory=dict)
    market_slug: str | None = None


def init_event_bus() -> asyncio.Queue:
    """Initialize the event bus. Call once from the main asyncio loop."""
    global _queue
    _queue = asyncio.Queue(maxsize=MAX_QUEUE_SIZE)
    log.info("EVENT_BUS │ initialized (maxsize=%d)", MAX_QUEUE_SIZE)
    return _queue


def emit(event_type: EventType, data: dict[str, Any], market_slug: str | None = None) -> None:
    """Emit an event. Thread-safe, non-blocking. No-op if bus not initialized."""
    global _drop_count
    if _queue is None:
        return
    event = Event(
        type=event_type,
        timestamp=time.time(),
        data=data,
        market_slug=market_slug,
    )
    try:
        _queue.put_nowait(event)
    except asyncio.QueueFull:
        _drop_count += 1
        if _drop_count % 100 == 1:
            log.warning("EVENT_BUS │ queue full, dropped %d events total", _drop_count)


async def consume() -> Event:
    """Consume the next event. Blocks until available. Call from async context."""
    if _queue is None:
        raise RuntimeError("Event bus not initialized — call init_event_bus() first")
    return await _queue.get()


def get_drop_count() -> int:
    """Return the total number of dropped events since startup."""
    return _drop_count


def is_initialized() -> bool:
    """Return True if the event bus has been initialized."""
    return _queue is not None
