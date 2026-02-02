# Signal detection modules for research and backtesting
from .detectors import (
    SignalType,
    Signal,
    DutchBookDetector,
    LagArbDetector,
    MomentumDetector,
    FlashCrashDetector,
    SignalArbiter,
)

__all__ = [
    "SignalType",
    "Signal",
    "DutchBookDetector",
    "LagArbDetector",
    "MomentumDetector",
    "FlashCrashDetector",
    "SignalArbiter",
]
