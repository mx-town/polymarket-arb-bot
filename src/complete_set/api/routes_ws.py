"""WebSocket endpoint — real-time bot state streaming to dashboard clients."""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from complete_set.events import EventType, consume, is_initialized

if TYPE_CHECKING:
    from complete_set.engine import Engine

log = logging.getLogger("cs.api.ws")

# Throttle: minimum interval between messages per channel (seconds)
THROTTLE = {
    EventType.TICK_SNAPSHOT: 0.5,   # Max 2/sec
    EventType.BTC_PRICE: 1.0,       # Max 1/sec
    EventType.VOLUME_STATE: 2.0,    # Max 1/2sec
    EventType.PNL_SNAPSHOT: 10.0,   # Infrequent
}


class ConnectionManager:
    """Manage WebSocket connections and broadcast events."""

    def __init__(self):
        self._connections: dict[int, WebSocket] = {}
        self._next_id: int = 0

    async def connect(self, ws: WebSocket) -> int:
        await ws.accept()
        conn_id = self._next_id
        self._next_id += 1
        self._connections[conn_id] = ws
        log.info("WS │ client %d connected (total=%d)", conn_id, len(self._connections))
        return conn_id

    def disconnect(self, conn_id: int) -> None:
        self._connections.pop(conn_id, None)
        log.info("WS │ client %d disconnected (total=%d)", conn_id, len(self._connections))

    async def broadcast(self, message: dict) -> None:
        """Send a message to all connected clients. Remove failed connections."""
        if not self._connections:
            return
        dead = []
        payload = json.dumps(message)
        for conn_id, ws in self._connections.items():
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(conn_id)
        for conn_id in dead:
            self.disconnect(conn_id)

    @property
    def count(self) -> int:
        return len(self._connections)


_manager = ConnectionManager()
_last_sent: dict[EventType, float] = {}


async def broadcast_event(event) -> None:
    """Broadcast an event to all WebSocket clients, respecting throttle limits."""
    if _manager.count == 0:
        return

    now = time.time()
    throttle = THROTTLE.get(event.type, 0)
    last = _last_sent.get(event.type, 0)
    if now - last < throttle:
        return
    _last_sent[event.type] = now

    await _manager.broadcast({
        "type": event.type.value,
        "ts": event.timestamp,
        "data": event.data,
        "slug": event.market_slug,
    })


def create_ws_router(engine: "Engine", tr_engine=None) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/live")
    async def ws_live(ws: WebSocket):
        conn_id = await _manager.connect(ws)
        try:
            # Send initial state snapshot
            snapshot = engine.get_state_snapshot()
            if tr_engine is not None:
                snapshot["trend_rider"] = tr_engine.get_state_snapshot()
            await ws.send_json({
                "type": "initial_state",
                "ts": time.time(),
                "data": snapshot,
            })

            # Keep connection alive, handle client messages
            while True:
                try:
                    msg = await asyncio.wait_for(ws.receive_text(), timeout=30.0)
                    data = json.loads(msg)
                    if data.get("type") == "ping":
                        await ws.send_json({"type": "pong", "ts": time.time()})
                except asyncio.TimeoutError:
                    # Send keepalive ping
                    try:
                        await ws.send_json({"type": "ping", "ts": time.time()})
                    except Exception:
                        break
        except WebSocketDisconnect:
            pass
        except Exception as e:
            log.warning("WS │ client %d error: %s", conn_id, e)
        finally:
            _manager.disconnect(conn_id)

    return router


def get_ws_manager() -> ConnectionManager:
    """Access the singleton ConnectionManager for event broadcasting."""
    return _manager
