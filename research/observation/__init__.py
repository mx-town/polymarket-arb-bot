"""
Data capture infrastructure for lag measurement.

Provides synchronized capture of all price feeds for analysis.
"""

from research.observation.synchronizer import StreamSynchronizer

__all__ = ["StreamSynchronizer"]
