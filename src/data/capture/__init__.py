"""
Data capture infrastructure for lag measurement.

Provides synchronized capture of all price feeds for analysis.
"""

from src.data.capture.synchronizer import StreamSynchronizer

__all__ = ["StreamSynchronizer"]
