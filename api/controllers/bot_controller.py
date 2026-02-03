"""
Bot Controller — subprocess manager for trading bot.

Handles:
- Spawning trading bot subprocess via trading.cli
- Reading status from PID file and metrics file
- Stopping bot via signals (SIGTERM/SIGKILL)
- Config overrides for start requests
"""

import asyncio
import contextlib
import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Optional

from trading.utils.logging import get_logger

logger = get_logger("bot_controller")

# Paths for IPC
PID_PATH = Path("/tmp/polymarket_bot.pid")
METRICS_PATH = Path("/tmp/polymarket_metrics.json")


class BotController:
    """
    Singleton controller for managing trading bot subprocess.

    Only one bot instance runs at a time. Status is read from PID/metrics files.
    """

    _instance: ClassVar[Optional["BotController"]] = None

    def __new__(cls) -> "BotController":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._process: asyncio.subprocess.Process | None = None
        self._initialized = True

        logger.info("CONTROLLER_INITIALIZED", "singleton_created=true")

    @classmethod
    def get_instance(cls) -> "BotController":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # =========================================================================
    # Status checks (read from filesystem)
    # =========================================================================

    def get_status(self) -> dict:
        """
        Get bot status from PID file and metrics file.

        Returns dict with:
        - is_running: bool
        - pid: int | None
        - uptime_sec: float | None
        - status: str (starting, running, stopped, failed)
        - started_at: str | None
        """
        pid = self._read_pid()
        is_running = pid is not None and self._is_process_running(pid)

        status = {
            "is_running": is_running,
            "pid": pid,
            "uptime_sec": None,
            "status": "running" if is_running else "stopped",
            "started_at": None,
        }

        # Read metrics file for additional info
        if METRICS_PATH.exists():
            try:
                with open(METRICS_PATH) as f:
                    metrics = json.load(f)
                    status["uptime_sec"] = metrics.get("uptime_sec", 0)
                    status["started_at"] = metrics.get("start_time")
                    # Update status based on metrics
                    if is_running:
                        status["status"] = "running"
                    elif metrics.get("bot_running") is False:
                        status["status"] = "stopped"
            except Exception as e:
                logger.warning("METRICS_READ_ERROR", str(e))

        # If we have a process but it's not running, mark as failed
        if pid is not None and not is_running:
            status["status"] = "failed"

        return status

    def _read_pid(self) -> int | None:
        """Read PID from file."""
        if not PID_PATH.exists():
            return None
        try:
            return int(PID_PATH.read_text().strip())
        except Exception:
            return None

    def _is_process_running(self, pid: int) -> bool:
        """Check if process with given PID is running."""
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    # =========================================================================
    # Start / Stop bot
    # =========================================================================

    async def start(self, config_overrides: dict = None) -> dict:
        """
        Start the trading bot subprocess.

        Args:
            config_overrides: Dict with strategy, dry_run, and other config overrides

        Returns:
            Status dict

        Raises:
            RuntimeError: If bot is already running
        """
        if self.is_running:
            raise RuntimeError("Bot already running")

        config_overrides = config_overrides or {}

        # Build CLI command
        cmd = [sys.executable, "-m", "trading.cli", "trade", "--api-mode"]

        # Add strategy
        strategy = config_overrides.get("strategy", "lag_arb")
        cmd.extend(["--strategy", strategy])

        # Add dry-run flag
        dry_run = config_overrides.get("dry_run", True)
        if dry_run:
            cmd.extend(["--dry-run"])
        else:
            cmd.extend(["--live"])

        # Add config file if specified
        config_path = config_overrides.get("config_path")
        if config_path:
            cmd.extend(["--config", str(config_path)])

        logger.info("STARTING_BOT", f"cmd={' '.join(cmd)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(Path.cwd()),
            )

            logger.info("BOT_STARTED", f"pid={self._process.pid}")

            # Wait a moment for PID file to be written
            await asyncio.sleep(0.5)

            # Return status
            return self.get_status()

        except Exception as e:
            logger.error("START_ERROR", str(e))
            self._process = None
            raise

    async def stop(self, force: bool = False) -> dict:
        """
        Stop the trading bot.

        Args:
            force: If True, use SIGKILL instead of SIGTERM

        Returns:
            Status dict
        """
        pid = self._read_pid()

        if pid is None:
            logger.warning("NOT_RUNNING", "no_pid_file")
            return self.get_status()

        if not self._is_process_running(pid):
            logger.warning("NOT_RUNNING", "process_not_running")
            return self.get_status()

        logger.info("STOPPING_BOT", f"pid={pid} force={force}")

        try:
            sig = signal.SIGKILL if force else signal.SIGTERM
            os.kill(pid, sig)

            # Wait for process to exit
            if not force:
                # Give it time to shut down gracefully
                for _ in range(10):  # Wait up to 5 seconds
                    await asyncio.sleep(0.5)
                    if not self._is_process_running(pid):
                        break
                else:
                    # Still running, force kill
                    logger.warning("FORCE_KILL_REQUIRED", "graceful_shutdown_timeout")
                    os.kill(pid, signal.SIGKILL)
                    await asyncio.sleep(0.5)

            logger.info("BOT_STOPPED", f"pid={pid}")

        except ProcessLookupError:
            logger.warning("PROCESS_ALREADY_DEAD", f"pid={pid}")
        except Exception as e:
            logger.error("STOP_ERROR", str(e))
        finally:
            self._process = None

        return self.get_status()

    async def restart(self, config_overrides: dict = None) -> dict:
        """
        Restart the bot (stop then start).

        Args:
            config_overrides: Config overrides for new instance

        Returns:
            Status dict
        """
        # Stop if running
        if self.is_running:
            await self.stop()

        # Wait a moment
        await asyncio.sleep(1.0)

        # Start with new config
        return await self.start(config_overrides)

    # =========================================================================
    # Shutdown
    # =========================================================================

    async def shutdown(self) -> None:
        """Kill bot subprocess on server shutdown."""
        if self._process is not None and self._process.returncode is None:
            logger.info("SHUTDOWN", "killing_bot_process")
            await self.stop(force=True)

    @property
    def is_running(self) -> bool:
        """Check if bot is currently running."""
        pid = self._read_pid()
        return pid is not None and self._is_process_running(pid)
