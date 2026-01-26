"""
Performance metrics tracking for Polymarket Arbitrage Bot.
"""

import json
import os
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

# Default paths for IPC
DEFAULT_METRICS_PATH = "/tmp/polymarket_metrics.json"
DEFAULT_PID_PATH = "/tmp/polymarket_bot.pid"

# Event types for unified event stream
EVENT_TYPES = [
    "DIRECTION",
    "POSITION_OPENED",
    "POSITION_CLOSED",
    "LAG_WINDOW_OPEN",
    "LAG_WINDOW_EXPIRED",
    "ENTRY_SKIP",
    "BLOCKED",
    "ENTRY_FAILED",
]


@dataclass
class TradingEvent:
    """A single trading event for the unified event stream"""

    event_type: str
    symbol: str
    timestamp: str
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "type": self.event_type,
            "symbol": self.symbol,
            "timestamp": self.timestamp,
            **self.details,
        }


@dataclass
class PnlSnapshot:
    """P&L snapshot for time-series chart"""

    timestamp: str
    total_pnl: float
    realized_pnl: float
    unrealized_pnl: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "total_pnl": self.total_pnl,
            "realized_pnl": self.realized_pnl,
            "unrealized_pnl": self.unrealized_pnl,
        }


@dataclass
class ClosedTrade:
    """Record of a closed trade for bar chart visualization"""

    timestamp: str
    market_slug: str
    pnl: float
    exit_reason: str
    hold_duration_sec: float

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "market_slug": self.market_slug,
            "pnl": self.pnl,
            "exit_reason": self.exit_reason,
            "hold_duration_sec": self.hold_duration_sec,
        }


@dataclass
class BotMetrics:
    """Track bot performance metrics"""

    # Cycle stats
    cycles: int = 0
    start_time: datetime | None = None
    last_cycle_time: datetime | None = None

    # Market stats
    markets_fetched: int = 0
    markets_scanned: int = 0

    # Opportunity stats
    opportunities_seen: int = 0
    opportunities_taken: int = 0
    opportunities_missed: int = 0

    # Execution stats
    trades_attempted: int = 0
    trades_filled: int = 0
    trades_partial: int = 0
    trades_failed: int = 0

    # P&L
    total_pnl: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    daily_pnl: float = 0.0

    # Risk tracking
    consecutive_losses: int = 0
    current_exposure: float = 0.0

    # Latency tracking
    ws_message_count: int = 0
    avg_message_latency_ms: float = 0.0
    ws_reconnects: int = 0

    # Event buffers (initialized in __post_init__)
    _events: deque = field(default_factory=lambda: deque(maxlen=100))
    _pnl_history: deque = field(default_factory=lambda: deque(maxlen=500))
    _trades_history: list = field(default_factory=list)

    def start(self):
        """Mark bot start time"""
        self.start_time = datetime.now()

    def cycle_complete(self):
        """Mark cycle completion"""
        self.cycles += 1
        self.last_cycle_time = datetime.now()

    def record_opportunity(self, taken: bool):
        """Record an opportunity"""
        self.opportunities_seen += 1
        if taken:
            self.opportunities_taken += 1
        else:
            self.opportunities_missed += 1

    def record_trade(self, success: bool, pnl: float = 0.0, partial: bool = False):
        """Record trade result"""
        self.trades_attempted += 1
        if success:
            self.trades_filled += 1
            self.realized_pnl += pnl
            self.total_pnl += pnl
            self.daily_pnl += pnl
            if pnl < 0:
                self.consecutive_losses += 1
            else:
                self.consecutive_losses = 0
        elif partial:
            self.trades_partial += 1
        else:
            self.trades_failed += 1

    def record_ws_message(self, latency_ms: float):
        """Track WebSocket message latency"""
        self.ws_message_count += 1
        # Running average
        self.avg_message_latency_ms = (
            self.avg_message_latency_ms * (self.ws_message_count - 1) + latency_ms
        ) / self.ws_message_count

    def reset_daily(self):
        """Reset daily metrics"""
        self.daily_pnl = 0.0

    def record_event(
        self,
        event_type: str,
        symbol: str,
        details: dict | None = None,
    ):
        """Record a trading event to the unified event stream"""
        event = TradingEvent(
            event_type=event_type,
            symbol=symbol,
            timestamp=datetime.now().isoformat(),
            details=details or {},
        )
        self._events.appendleft(event)

    def record_pnl_snapshot(self):
        """Record current P&L state for time-series chart"""
        snapshot = PnlSnapshot(
            timestamp=datetime.now().isoformat(),
            total_pnl=self.total_pnl,
            realized_pnl=self.realized_pnl,
            unrealized_pnl=self.unrealized_pnl,
        )
        self._pnl_history.append(snapshot)

    def record_closed_trade(
        self,
        market_slug: str,
        pnl: float,
        exit_reason: str,
        hold_duration_sec: float,
    ):
        """Record a closed trade for bar chart visualization"""
        trade = ClosedTrade(
            timestamp=datetime.now().isoformat(),
            market_slug=market_slug,
            pnl=pnl,
            exit_reason=exit_reason,
            hold_duration_sec=hold_duration_sec,
        )
        self._trades_history.append(trade)

    def get_events(self) -> list[dict]:
        """Get events as list of dicts for export"""
        return [e.to_dict() for e in self._events]

    def get_pnl_history(self) -> list[dict]:
        """Get P&L history as list of dicts for export"""
        return [s.to_dict() for s in self._pnl_history]

    def get_trades_history(self) -> list[dict]:
        """Get trades history as list of dicts for export"""
        return [t.to_dict() for t in self._trades_history]

    @property
    def win_rate(self) -> float:
        """Calculate win rate"""
        if self.trades_filled == 0:
            return 0.0
        wins = sum(1 for _ in range(self.trades_filled) if self.total_pnl > 0)
        return wins / self.trades_filled

    @property
    def uptime_seconds(self) -> float:
        """Calculate uptime"""
        if not self.start_time:
            return 0.0
        return (datetime.now() - self.start_time).total_seconds()

    def summary(self) -> dict:
        """Return metrics summary"""
        return {
            "cycles": self.cycles,
            "uptime_sec": self.uptime_seconds,
            "markets_scanned": self.markets_scanned,
            "opportunities_seen": self.opportunities_seen,
            "opportunities_taken": self.opportunities_taken,
            "trades_filled": self.trades_filled,
            "trades_failed": self.trades_failed,
            "total_pnl": self.total_pnl,
            "daily_pnl": self.daily_pnl,
            "consecutive_losses": self.consecutive_losses,
            "ws_reconnects": self.ws_reconnects,
            "avg_latency_ms": self.avg_message_latency_ms,
        }

    def export_to_file(
        self,
        path: str = DEFAULT_METRICS_PATH,
        active_markets: list | None = None,
        active_windows: list | None = None,
        config_summary: dict | None = None,
    ) -> bool:
        """Export metrics to JSON file for IPC with API server"""
        try:
            data = self.summary()
            data["timestamp"] = datetime.now().isoformat()
            data["start_time"] = self.start_time.isoformat() if self.start_time else None

            # Bot status (single source of truth for ControlPanel)
            data["pid"] = os.getpid()
            data["bot_running"] = True  # If we're exporting, bot is running

            # Add additional fields for dashboard
            data["markets_fetched"] = self.markets_fetched
            data["trades_attempted"] = self.trades_attempted
            data["trades_partial"] = self.trades_partial
            data["realized_pnl"] = self.realized_pnl
            data["unrealized_pnl"] = self.unrealized_pnl
            data["current_exposure"] = self.current_exposure
            data["ws_message_count"] = self.ws_message_count

            # Live visibility data for dashboard
            data["active_markets"] = active_markets or []
            data["active_windows"] = active_windows or []
            data["config_summary"] = config_summary or {}

            # Unified event stream for dashboard
            data["events"] = self.get_events()
            data["pnl_history"] = self.get_pnl_history()
            data["trades_history"] = self.get_trades_history()

            # Atomic write using temp file
            temp_path = f"{path}.tmp"
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2)
            os.replace(temp_path, path)
            return True
        except Exception:
            return False


def write_pid(path: str = DEFAULT_PID_PATH) -> bool:
    """Write current process PID to file"""
    try:
        pid = os.getpid()
        Path(path).write_text(str(pid))
        return True
    except Exception:
        return False


def remove_pid(path: str = DEFAULT_PID_PATH) -> bool:
    """Remove PID file"""
    try:
        Path(path).unlink(missing_ok=True)
        return True
    except Exception:
        return False


def read_pid(path: str = DEFAULT_PID_PATH) -> int | None:
    """Read PID from file"""
    try:
        content = Path(path).read_text().strip()
        return int(content)
    except Exception:
        return None
