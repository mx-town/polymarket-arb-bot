"""
Shared signal engine package.

Contains:
- types.py: UnifiedSignal, Direction, SignalTier, MarketContext, ModelOutput
- config.py: SignalEvaluatorConfig, EngineConfig  
- model_bridge.py: ProbabilitySurface + EdgeCalculator wrapper
- signal_evaluator.py: Multi-tier signal detection
- events.py: EngineEvent, EventBus
- streams/: Shared stream adapters
"""

from engine.types import (
    Direction,
    MarketContext,
    ModelOutput,
    SignalTier,
    UnifiedSignal,
)
from engine.config import EngineConfig, SignalEvaluatorConfig
from engine.events import EngineEvent, EventBus, get_event_bus, emit_signal_event
from engine.model_bridge import ModelBridge
from engine.signal_evaluator import SignalEvaluator

__all__ = [
    # Types
    "Direction",
    "SignalTier",
    "MarketContext",
    "ModelOutput",
    "UnifiedSignal",
    # Config
    "EngineConfig",
    "SignalEvaluatorConfig",
    # Events
    "EngineEvent",
    "EventBus",
    "get_event_bus",
    "emit_signal_event",
    # Components
    "ModelBridge",
    "SignalEvaluator",
]
