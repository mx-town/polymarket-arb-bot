"""
Singleton state manager for the Research API.

Manages observation state, signal buffering, and WebSocket connections
for the research dashboard.
"""

from __future__ import annotations

import asyncio
import subprocess
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, ClassVar

from fastapi import WebSocket

from src.utils.logging import get_logger

logger = get_logger("research_state")


@dataclass
class ObservationState:
    """State of the current observation session."""

    is_running: bool = False
    started_at: datetime | None = None
    duration_sec: int | None = None
    snapshots_collected: int = 0
    signals_detected: int = 0
    process: subprocess.Popen | None = field(default=None, repr=False)

    def to_dict(self) -> dict[str, Any]:
        """Serialize to dict, excluding process."""
        return {
            "is_running": self.is_running,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "duration_sec": self.duration_sec,
            "snapshots_collected": self.snapshots_collected,
            "signals_detected": self.signals_detected,
        }


class ResearchStateManager:
    """
    Singleton state manager for research API.

    Handles observation state, signal buffering, and WebSocket broadcasting.
    """

    _instance: ClassVar[ResearchStateManager | None] = None
    _initialized: bool = False

    def __new__(cls) -> ResearchStateManager:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self) -> None:
        # Only initialize once
        if self._initialized:
            return

        self.observation_state = ObservationState()
        self.signal_buffer: deque[dict] = deque(maxlen=100)
        self.websocket_connections: set[WebSocket] = set()
        self._lock = asyncio.Lock()
        self._initialized = True

        logger.info("INITIALIZED", "singleton_created=true")

    @classmethod
    def get_instance(cls) -> ResearchStateManager:
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def add_signal(self, signal: dict) -> None:
        """
        Add a signal to the buffer (newest first).

        Args:
            signal: Signal dict to add
        """
        # Insert at the beginning (newest first)
        self.signal_buffer.appendleft(signal)
        self.observation_state.signals_detected += 1
        logger.info("SIGNAL_ADDED", f"total_signals={len(self.signal_buffer)}")

    def get_signals(self, limit: int = 50) -> list[dict]:
        """
        Get signals from buffer.

        Args:
            limit: Maximum number of signals to return

        Returns:
            List of signals (newest first)
        """
        return list(self.signal_buffer)[:limit]

    def update_observation_state(self, **kwargs: Any) -> None:
        """
        Update observation state with provided kwargs.

        Args:
            **kwargs: Fields to update on ObservationState
        """
        for key, value in kwargs.items():
            if hasattr(self.observation_state, key):
                setattr(self.observation_state, key, value)
                logger.debug("STATE_UPDATED", f"{key}={value}")
            else:
                logger.warning("UNKNOWN_FIELD", f"field={key}")

    def get_observation_status(self) -> dict[str, Any]:
        """
        Get current observation status.

        Returns:
            Dict representation of observation state
        """
        return self.observation_state.to_dict()

    def register_websocket(self, ws: WebSocket) -> None:
        """
        Register a WebSocket connection.

        Args:
            ws: WebSocket to register
        """
        self.websocket_connections.add(ws)
        logger.info("WS_REGISTERED", f"total_connections={len(self.websocket_connections)}")

    def unregister_websocket(self, ws: WebSocket) -> None:
        """
        Unregister a WebSocket connection.

        Args:
            ws: WebSocket to unregister
        """
        self.websocket_connections.discard(ws)
        logger.info("WS_UNREGISTERED", f"total_connections={len(self.websocket_connections)}")

    async def broadcast(self, message_type: str, data: dict) -> None:
        """
        Broadcast a message to all registered WebSocket connections.

        Args:
            message_type: Type of message (e.g., "signal", "status_update")
            data: Data payload to send
        """
        if not self.websocket_connections:
            return

        message = {"type": message_type, "data": data}
        disconnected: list[WebSocket] = []

        async with self._lock:
            for ws in self.websocket_connections:
                try:
                    await ws.send_json(message)
                except Exception as e:
                    logger.warning("BROADCAST_ERROR", f"error={e}")
                    disconnected.append(ws)

            # Clean up disconnected sockets
            for ws in disconnected:
                self.websocket_connections.discard(ws)

        if disconnected:
            logger.info(
                "WS_CLEANUP",
                f"removed={len(disconnected)} remaining={len(self.websocket_connections)}",
            )

    def reset(self) -> None:
        """Reset state for testing."""
        self.observation_state = ObservationState()
        self.signal_buffer.clear()
        self.websocket_connections.clear()
        logger.info("STATE_RESET", "all_state_cleared=true")
