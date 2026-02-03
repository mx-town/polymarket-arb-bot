"""
Event system for the shared engine.

Provides an EventBus for broadcasting signals and model evaluations
to interested subscribers (API, dashboard, logging).
"""

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable, Optional
from threading import Lock


@dataclass
class EngineEvent:
    """
    An event emitted by the engine.
    
    Events are used to communicate signal detections, model evaluations,
    and other notable occurrences to subscribers.
    """
    event_type: str           # SIGNAL_DETECTED, MODEL_EVALUATION, etc.
    tier: str                 # Signal tier name (DUTCH_BOOK, LAG_ARB, etc.)
    symbol: str               # Trading symbol (BTCUSDT, etc.)
    timestamp: str            # ISO format timestamp
    signal: dict              # Serialized UnifiedSignal data
    details: dict = field(default_factory=dict)  # Additional context
    
    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "event_type": self.event_type,
            "tier": self.tier,
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            "signal": self.signal,
            "details": self.details,
        }
    
    @classmethod
    def from_signal(cls, signal, event_type: str = "SIGNAL_DETECTED") -> "EngineEvent":
        """Create an event from a UnifiedSignal."""
        return cls(
            event_type=event_type,
            tier=signal.tier.name,
            symbol=signal.symbol,
            timestamp=signal.timestamp.isoformat(),
            signal=signal.to_dict(),
            details={
                "direction": signal.direction.value,
                "is_actionable": signal.is_actionable,
                "confidence": signal.confidence,
                "expected_edge": signal.expected_edge,
            },
        )


EventCallback = Callable[[EngineEvent], None]


class EventBus:
    """
    Simple event bus for publishing engine events to subscribers.
    
    Thread-safe. Maintains a bounded history of recent events.
    
    Usage:
        bus = EventBus()
        bus.subscribe(lambda e: print(f"Got event: {e.event_type}"))
        bus.emit(event)
    """
    
    def __init__(self, max_history: int = 100):
        """
        Initialize the event bus.
        
        Args:
            max_history: Maximum number of events to keep in history
        """
        self._subscribers: list[EventCallback] = []
        self._history: deque[EngineEvent] = deque(maxlen=max_history)
        self._lock = Lock()
    
    def subscribe(self, callback: EventCallback) -> Callable[[], None]:
        """
        Subscribe to events.
        
        Args:
            callback: Function to call when an event is emitted
            
        Returns:
            Unsubscribe function
        """
        with self._lock:
            self._subscribers.append(callback)
        
        def unsubscribe():
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)
        
        return unsubscribe
    
    def emit(self, event: EngineEvent) -> None:
        """
        Emit an event to all subscribers.
        
        Args:
            event: The event to emit
        """
        with self._lock:
            self._history.append(event)
            subscribers = list(self._subscribers)
        
        # Call subscribers outside the lock to prevent deadlocks
        for callback in subscribers:
            try:
                callback(event)
            except Exception:
                # Don't let subscriber errors affect other subscribers
                pass
    
    def get_events(self, limit: int = 50) -> list[dict]:
        """
        Get recent events from history.
        
        Args:
            limit: Maximum number of events to return
            
        Returns:
            List of event dictionaries (most recent first)
        """
        with self._lock:
            events = list(self._history)
        
        # Return most recent first, up to limit
        return [e.to_dict() for e in reversed(events)][:limit]
    
    def clear_history(self) -> None:
        """Clear the event history."""
        with self._lock:
            self._history.clear()
    
    @property
    def subscriber_count(self) -> int:
        """Number of active subscribers."""
        with self._lock:
            return len(self._subscribers)
    
    @property
    def history_size(self) -> int:
        """Number of events in history."""
        with self._lock:
            return len(self._history)


# Global event bus instance (singleton pattern)
_global_bus: Optional[EventBus] = None


def get_event_bus() -> EventBus:
    """Get the global event bus instance."""
    global _global_bus
    if _global_bus is None:
        _global_bus = EventBus()
    return _global_bus


def emit_signal_event(signal, event_type: str = "SIGNAL_DETECTED") -> None:
    """
    Convenience function to emit a signal event on the global bus.
    
    Args:
        signal: UnifiedSignal to emit
        event_type: Type of event (default: SIGNAL_DETECTED)
    """
    event = EngineEvent.from_signal(signal, event_type)
    get_event_bus().emit(event)
