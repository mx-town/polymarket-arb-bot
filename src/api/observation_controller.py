"""
Observation Controller for spawning and managing arb-capture observe subprocess.

Handles:
- Spawning arb-capture observe subprocess
- Parsing stdout for real-time updates
- Broadcasting snapshots and signals to WebSocket clients
- Graceful shutdown
"""

import asyncio
import contextlib
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Optional

from src.api.research_state import ResearchStateManager
from src.utils.logging import get_logger

logger = get_logger("observation_controller")


class ObservationController:
    """
    Controller for managing the arb-capture observe subprocess.

    Singleton pattern to ensure only one observation runs at a time.
    """

    _instance: ClassVar[Optional["ObservationController"]] = None

    def __new__(cls) -> "ObservationController":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._process: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task | None = None
        self._state = ResearchStateManager.get_instance()
        self._initialized = True

        logger.info("CONTROLLER_INITIALIZED", "singleton_created=true")

    @classmethod
    def get_instance(cls) -> "ObservationController":
        """Get the singleton instance."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    async def start(self, duration_sec: int = 3600) -> None:
        """
        Start the observation subprocess.

        Args:
            duration_sec: Duration in seconds for observation
        """
        if self._process is not None and self._process.returncode is None:
            logger.warning("ALREADY_RUNNING", "observation_in_progress")
            return

        # Build command
        python_path = sys.executable
        cmd = [
            python_path,
            "-m",
            "src.data.capture.capture_cli",
            "observe",
            "--duration",
            str(duration_sec),
        ]

        logger.info("STARTING_OBSERVATION", f"cmd={' '.join(cmd)}")

        try:
            # Start subprocess with pipes for stdout/stderr
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(Path.cwd()),
            )

            # Update state
            self._state.update_observation_state(
                is_running=True,
                started_at=datetime.now(),
                duration_sec=duration_sec,
                snapshots_collected=0,
                signals_detected=0,
                process=None,  # Don't store asyncio process in dataclass
            )

            # Start reader task
            self._reader_task = asyncio.create_task(self._read_output())

            logger.info("OBSERVATION_STARTED", f"pid={self._process.pid} duration={duration_sec}s")

            # Broadcast status update
            await self._state.broadcast(
                "observation_status",
                self._state.get_observation_status(),
            )

        except Exception as e:
            logger.error("START_ERROR", str(e))
            self._state.update_observation_state(is_running=False)
            raise

    async def stop(self) -> None:
        """Stop the observation subprocess."""
        if self._process is None:
            logger.warning("NOT_RUNNING", "no_observation_to_stop")
            return

        logger.info("STOPPING_OBSERVATION", f"pid={self._process.pid}")

        try:
            # Terminate gracefully
            self._process.terminate()

            # Wait for process to exit (with timeout)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except TimeoutError:
                logger.warning("KILL_REQUIRED", "process_did_not_terminate")
                self._process.kill()
                await self._process.wait()

            # Cancel reader task
            if self._reader_task and not self._reader_task.done():
                self._reader_task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await self._reader_task

            logger.info("OBSERVATION_STOPPED", f"exit_code={self._process.returncode}")

        except Exception as e:
            logger.error("STOP_ERROR", str(e))
        finally:
            self._process = None
            self._reader_task = None

            # Update state
            self._state.update_observation_state(
                is_running=False,
                started_at=None,
                duration_sec=None,
            )

            # Broadcast status update
            await self._state.broadcast(
                "observation_status",
                self._state.get_observation_status(),
            )

    async def _read_output(self) -> None:
        """Read and parse subprocess output."""
        if self._process is None or self._process.stdout is None:
            return

        logger.info("READER_STARTED", "parsing_stdout")

        try:
            async for line in self._process.stdout:
                line_text = line.decode().strip()
                if not line_text:
                    continue

                # Parse and handle different output types
                await self._handle_output_line(line_text)

        except asyncio.CancelledError:
            logger.info("READER_CANCELLED", "task_cancelled")
        except Exception as e:
            logger.error("READER_ERROR", str(e))
        finally:
            # Process ended
            if self._state.observation_state.is_running:
                self._state.update_observation_state(is_running=False)
                await self._state.broadcast(
                    "observation_status",
                    self._state.get_observation_status(),
                )

            logger.info("READER_STOPPED", "output_stream_ended")

    async def _handle_output_line(self, line: str) -> None:
        """Handle a line of output from the subprocess."""
        # Try to parse as JSON (enriched snapshot or signal)
        if line.startswith("{"):
            try:
                data = json.loads(line)

                # Check if it's a snapshot
                if "timestamp_ms" in data and "binance_price" in data:
                    self._state.observation_state.snapshots_collected += 1

                    # Track signals embedded in snapshots
                    if data.get("signal_detected"):
                        self._state.observation_state.signals_detected += 1
                        self._state.add_signal(data)
                        await self._state.broadcast("signal", data)

                    # Broadcast snapshot to WebSocket clients
                    await self._state.broadcast("snapshot", data)

                    # Log periodically
                    if self._state.observation_state.snapshots_collected % 100 == 0:
                        logger.info(
                            "SNAPSHOTS_PROGRESS",
                            f"count={self._state.observation_state.snapshots_collected}",
                        )

                # Check if it's a signal
                elif "signal_type" in data:
                    self._state.add_signal(data)

                    # Broadcast signal to WebSocket clients
                    await self._state.broadcast("signal", data)

                    logger.info("SIGNAL_DETECTED", f"type={data.get('signal_type')}")

            except json.JSONDecodeError:
                pass  # Not JSON, probably log output

        # Handle log lines (could extract metrics from them)
        elif "SNAPSHOT_ENRICHED" in line or "SIGNAL_DETECTED" in line:
            # These are log messages from the capture process
            pass

    @property
    def is_running(self) -> bool:
        """Check if observation is currently running."""
        return self._process is not None and self._process.returncode is None
