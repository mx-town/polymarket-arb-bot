"""
Structured logging for Polymarket Arbitrage Bot.

Format: timestamp | level | component | event | details
"""

import logging
import sys
from typing import Optional


class ComponentLogger:
    """Logger with component-based tagging"""

    def __init__(self, component: str, level: int = logging.INFO):
        self.component = component
        self.logger = logging.getLogger(f"arb_bot.{component}")
        self.logger.setLevel(level)

    def _format(self, event: str, details: Optional[str] = None) -> str:
        msg = f"[{self.component}] {event}"
        if details:
            msg += f" | {details}"
        return msg

    def info(self, event: str, details: Optional[str] = None):
        self.logger.info(self._format(event, details))

    def warning(self, event: str, details: Optional[str] = None):
        self.logger.warning(self._format(event, details))

    def error(self, event: str, details: Optional[str] = None):
        self.logger.error(self._format(event, details))

    def debug(self, event: str, details: Optional[str] = None):
        self.logger.debug(self._format(event, details))


def setup_logging(verbose: bool = False) -> None:
    """Configure root logger with standard format"""
    level = logging.DEBUG if verbose else logging.INFO

    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S",
        stream=sys.stdout,
        force=True,
    )


def get_logger(component: str) -> ComponentLogger:
    """Get a component-tagged logger"""
    return ComponentLogger(component)
