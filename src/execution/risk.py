"""
Risk management for Polymarket Arbitrage Bot.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from src.config import RiskConfig
from src.execution.position import PositionManager
from src.utils.logging import get_logger

logger = get_logger("risk")


@dataclass
class RiskState:
    """Current risk state"""

    consecutive_losses: int = 0
    daily_pnl: float = 0.0
    last_loss_time: Optional[datetime] = None
    is_paused: bool = False
    pause_reason: Optional[str] = None
    pause_until: Optional[datetime] = None


class RiskManager:
    """Manages risk limits and circuit breakers"""

    def __init__(self, config: RiskConfig):
        self.config = config
        self.state = RiskState()

    def record_trade_result(self, pnl: float):
        """Record a trade result for risk tracking"""
        self.state.daily_pnl += pnl

        if pnl < 0:
            self.state.consecutive_losses += 1
            self.state.last_loss_time = datetime.now()

            # Check consecutive loss limit
            if self.state.consecutive_losses >= self.config.max_consecutive_losses:
                self._pause(
                    reason=f"consecutive_losses={self.state.consecutive_losses}",
                    seconds=self.config.cooldown_after_loss_sec,
                )
        else:
            self.state.consecutive_losses = 0

        # Check daily loss limit
        if self.state.daily_pnl <= -self.config.max_daily_loss_usd:
            self._pause(
                reason=f"daily_loss={self.state.daily_pnl:.2f}",
                seconds=86400,  # Pause for rest of day
            )

    def _pause(self, reason: str, seconds: int):
        """Pause trading"""
        self.state.is_paused = True
        self.state.pause_reason = reason
        self.state.pause_until = datetime.now()
        # Add seconds to pause_until
        from datetime import timedelta
        self.state.pause_until += timedelta(seconds=seconds)

        logger.warning(
            "TRADING_PAUSED",
            f"reason={reason} until={self.state.pause_until.isoformat()}",
        )

    def check_can_trade(self) -> tuple[bool, Optional[str]]:
        """
        Check if trading is allowed.

        Returns:
            Tuple of (can_trade, reason_if_not)
        """
        # Check if paused
        if self.state.is_paused:
            if self.state.pause_until and datetime.now() >= self.state.pause_until:
                # Pause expired
                self.state.is_paused = False
                self.state.pause_reason = None
                self.state.pause_until = None
                logger.info("TRADING_RESUMED", "Pause expired")
            else:
                return False, self.state.pause_reason

        return True, None

    def check_exposure_limit(
        self,
        position_manager: PositionManager,
        new_position_size: float,
    ) -> tuple[bool, Optional[str]]:
        """
        Check if new position would exceed exposure limits.

        Args:
            position_manager: Current positions
            new_position_size: Size of proposed new position

        Returns:
            Tuple of (allowed, reason_if_not)
        """
        current_exposure = position_manager.total_exposure()
        new_total = current_exposure + new_position_size

        if new_total > self.config.max_total_exposure:
            return False, f"exposure_limit: {new_total:.2f} > {self.config.max_total_exposure:.2f}"

        return True, None

    def reset_daily(self):
        """Reset daily metrics (call at midnight)"""
        self.state.daily_pnl = 0.0
        # Don't reset consecutive_losses - that persists

    def get_status(self) -> dict:
        """Get current risk status"""
        return {
            "is_paused": self.state.is_paused,
            "pause_reason": self.state.pause_reason,
            "consecutive_losses": self.state.consecutive_losses,
            "daily_pnl": self.state.daily_pnl,
        }
