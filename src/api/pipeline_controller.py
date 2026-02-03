"""
Pipeline Controller — unified subprocess manager for all arb-capture CLI commands.

Replaces ObservationController. Handles:
- Spawning arb-capture CLI subprocesses (init, rebuild, observe, verify, analyse, reset)
- Parsing stdout in two modes: JSON (observe) and Log (everything else)
- Broadcasting progress events and snapshots to WebSocket clients
- Mutual exclusion: only one command runs at a time
- Graceful shutdown
"""

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import ClassVar, Optional

from src.api.models.pipeline import (
    PipelineJobStatus,
    PipelineProgressEvent,
    PipelineStatus,
)
from src.api.research_state import ResearchStateManager
from src.utils.logging import get_logger

logger = get_logger("pipeline_controller")

# Stage markers emitted by capture_cli.py
STAGE_MARKERS = {
    "INIT_START",
    "DOWNLOAD_START",
    "DOWNLOAD_COMPLETE",
    "EXTRACT_START",
    "EXTRACT_COMPLETE",
    "MODEL_START",
    "MODEL_COMPLETE",
    "REBUILD_START",
    "VERIFY_START",
    "CAPTURE_START",
    "CAPTURE_COMPLETE",
    "PROGRESS",
}

# Regex to match logger output: "YYYY-MM-DD HH:MM:SS | COMPONENT | LEVEL | MARKER | detail"
# or simpler: just look for known markers in the line
MARKER_PATTERN = re.compile(r"\b(" + "|".join(STAGE_MARKERS) + r")\b")

# Paths for filesystem state checks
SURFACE_PATH = Path("research/models/probability_surface.json")
RAW_DATA_PATH = Path("research/data/raw/BTCUSDT_1m.parquet")
OBSERVATIONS_DIR = Path("research/data/observations")


class PipelineController:
    """
    Singleton controller for managing arb-capture CLI subprocesses.

    Only one command runs at a time. Observe mode uses JSON parsing;
    all other commands use log-mode stage marker parsing.
    """

    _instance: ClassVar[Optional["PipelineController"]] = None

    def __new__(cls) -> "PipelineController":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._process: Optional[asyncio.subprocess.Process] = None
        self._reader_task: Optional[asyncio.Task] = None
        self._current_job: Optional[PipelineJobStatus] = None
        self._state = ResearchStateManager.get_instance()
        self._initialized = True

        logger.info("CONTROLLER_INITIALIZED", "singleton_created=true")

    @classmethod
    def get_instance(cls) -> "PipelineController":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    # =========================================================================
    # Filesystem status (no subprocess needed)
    # =========================================================================

    def get_pipeline_status(self) -> PipelineStatus:
        """Check filesystem state and current job."""
        has_model = SURFACE_PATH.exists()
        model_age_hours = None
        if has_model:
            mtime = SURFACE_PATH.stat().st_mtime
            model_age_hours = round((time.time() - mtime) / 3600, 1)

        has_raw_data = RAW_DATA_PATH.exists()

        observation_files = 0
        observation_size_mb = 0.0
        if OBSERVATIONS_DIR.exists():
            parquets = list(OBSERVATIONS_DIR.glob("snapshots_*.parquet"))
            observation_files = len(parquets)
            observation_size_mb = round(sum(f.stat().st_size for f in parquets) / (1024 * 1024), 2)

        return PipelineStatus(
            has_model=has_model,
            model_age_hours=model_age_hours,
            has_raw_data=has_raw_data,
            observation_files=observation_files,
            observation_size_mb=observation_size_mb,
            current_job=self._current_job,
        )

    # =========================================================================
    # Start / Stop commands
    # =========================================================================

    async def start_command(self, command: str, args: dict) -> PipelineJobStatus:
        """
        Start a CLI command. Returns 409-style error via exception if busy.

        Args:
            command: CLI command name (init, rebuild, observe, verify, analyse)
            args: Command arguments dict
        """
        if self._process is not None and self._process.returncode is None:
            raise RuntimeError("Pipeline busy — another command is running")

        # Build CLI args
        cmd = [sys.executable, "-m", "src.data.capture.capture_cli", command]

        if command == "init":
            months = args.get("months", 6)
            cmd.extend(["--months", str(months)])
        elif command == "observe":
            duration = args.get("duration", 3600)
            cmd.extend(["--duration", str(duration)])
        elif command == "verify":
            duration = args.get("duration", 300)
            cmd.extend(["--duration", str(duration)])
        elif command == "analyse":
            if args.get("file"):
                cmd.extend(["--file", str(args["file"])])

        logger.info("STARTING_COMMAND", f"cmd={' '.join(cmd)}")

        now = datetime.now()
        self._current_job = PipelineJobStatus(
            command=command,
            args=args,
            status="running",
            started_at=now.isoformat(),
            elapsed_sec=0,
            progress=[],
            exit_code=None,
        )

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                cwd=str(Path.cwd()),
            )

            # For observe, also update observation state
            if command == "observe":
                self._state.update_observation_state(
                    is_running=True,
                    started_at=now,
                    duration_sec=args.get("duration", 3600),
                    snapshots_collected=0,
                    signals_detected=0,
                )
                await self._state.broadcast(
                    "observation_status",
                    self._state.get_observation_status(),
                )

            # Start reader task
            self._reader_task = asyncio.create_task(self._read_output(command))

            logger.info("COMMAND_STARTED", f"pid={self._process.pid} command={command}")

            # Broadcast initial status
            await self._state.broadcast(
                "pipeline_progress",
                PipelineProgressEvent(
                    stage=f"{command.upper()}_STARTED",
                    message=f"Started {command}",
                    detail=f"pid={self._process.pid}",
                    timestamp=now.isoformat(),
                ).model_dump(),
            )

            return self._current_job

        except Exception as e:
            logger.error("START_ERROR", str(e))
            self._current_job = None
            raise

    async def stop_command(self) -> Optional[PipelineJobStatus]:
        """Stop the currently running command."""
        if self._process is None:
            logger.warning("NOT_RUNNING", "no_command_to_stop")
            return None

        logger.info("STOPPING_COMMAND", f"pid={self._process.pid}")

        try:
            self._process.terminate()
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                logger.warning("KILL_REQUIRED", "process_did_not_terminate")
                self._process.kill()
                await self._process.wait()

            if self._reader_task and not self._reader_task.done():
                self._reader_task.cancel()
                try:
                    await self._reader_task
                except asyncio.CancelledError:
                    pass

        except Exception as e:
            logger.error("STOP_ERROR", str(e))
        finally:
            if self._current_job:
                self._current_job.status = "cancelled"
                self._current_job.exit_code = self._process.returncode if self._process else -1

                # Broadcast completion
                await self._state.broadcast(
                    "pipeline_complete",
                    self._current_job.model_dump(),
                )

            # If it was observe, update observation state
            if self._current_job and self._current_job.command == "observe":
                self._state.update_observation_state(
                    is_running=False,
                    started_at=None,
                    duration_sec=None,
                )
                await self._state.broadcast(
                    "observation_status",
                    self._state.get_observation_status(),
                )

            result = self._current_job
            self._process = None
            self._reader_task = None

            logger.info("COMMAND_STOPPED", f"exit_code={result.exit_code if result else 'unknown'}")
            return result

    # =========================================================================
    # Stdout reader
    # =========================================================================

    async def _read_output(self, command: str) -> None:
        """Read and parse subprocess output based on command type."""
        if self._process is None or self._process.stdout is None:
            return

        is_observe = command == "observe"
        start_time = time.time()

        logger.info("READER_STARTED", f"mode={'json' if is_observe else 'log'}")

        try:
            async for line in self._process.stdout:
                line_text = line.decode().strip()
                if not line_text:
                    continue

                # Update elapsed time
                if self._current_job:
                    self._current_job.elapsed_sec = round(time.time() - start_time, 1)

                if is_observe:
                    await self._handle_json_line(line_text)
                else:
                    await self._handle_log_line(line_text)

        except asyncio.CancelledError:
            logger.info("READER_CANCELLED", "task_cancelled")
        except Exception as e:
            logger.error("READER_ERROR", str(e))
        finally:
            # Process ended — update job status
            exit_code = self._process.returncode if self._process else None
            if self._current_job and self._current_job.status == "running":
                self._current_job.status = "completed" if exit_code == 0 else "failed"
                self._current_job.exit_code = exit_code
                self._current_job.elapsed_sec = round(time.time() - start_time, 1)

                await self._state.broadcast(
                    "pipeline_complete",
                    self._current_job.model_dump(),
                )

            # If observe ended, clear observation state
            if is_observe and self._state.observation_state.is_running:
                self._state.update_observation_state(is_running=False)
                await self._state.broadcast(
                    "observation_status",
                    self._state.get_observation_status(),
                )

            self._process = None
            self._reader_task = None

            logger.info("READER_STOPPED", f"exit_code={exit_code}")

    async def _handle_json_line(self, line: str) -> None:
        """Parse JSON stdout from observe command (snapshots + signals)."""
        if not line.startswith("{"):
            # Could be a log line from observe — check for stage markers too
            await self._handle_log_line(line)
            return

        try:
            data = json.loads(line)

            if "timestamp_ms" in data and "binance_price" in data:
                self._state.observation_state.snapshots_collected += 1

                if data.get("signal_detected"):
                    self._state.observation_state.signals_detected += 1
                    self._state.add_signal(data)
                    await self._state.broadcast("signal", data)

                await self._state.broadcast("snapshot", data)

                if self._state.observation_state.snapshots_collected % 100 == 0:
                    logger.info(
                        "SNAPSHOTS_PROGRESS",
                        f"count={self._state.observation_state.snapshots_collected}",
                    )

            elif "signal_type" in data:
                self._state.add_signal(data)
                await self._state.broadcast("signal", data)
                logger.info("SIGNAL_DETECTED", f"type={data.get('signal_type')}")

        except json.JSONDecodeError:
            pass

    async def _handle_log_line(self, line: str) -> None:
        """Parse log output for stage markers and broadcast progress."""
        match = MARKER_PATTERN.search(line)
        if not match:
            return

        stage = match.group(1)
        # Extract the part after the marker as detail
        detail = line[match.end():].strip().lstrip("|").strip()

        event = PipelineProgressEvent(
            stage=stage,
            message=stage.replace("_", " ").title(),
            detail=detail,
            timestamp=datetime.now().isoformat(),
        )

        if self._current_job:
            self._current_job.progress.append(event)

        await self._state.broadcast("pipeline_progress", event.model_dump())

        logger.info("STAGE_MARKER", f"stage={stage} detail={detail[:80]}")

    # =========================================================================
    # Reset (no subprocess — direct file deletion)
    # =========================================================================

    async def reset(self, target_dir: str = "research/data/observations", force: bool = True) -> dict:
        """Delete observation files directly (no subprocess needed)."""
        target = Path(target_dir)
        if not target.exists():
            return {"deleted": 0, "error": f"Directory does not exist: {target_dir}"}

        patterns = ["snapshots_*.parquet", "lag_report_*.txt"]
        files_to_delete = []
        for pattern in patterns:
            files_to_delete.extend(target.glob(pattern))

        deleted = 0
        for f in files_to_delete:
            try:
                os.remove(f)
                deleted += 1
            except Exception as e:
                logger.error("DELETE_FAILED", f"file={f} error={e}")

        logger.info("RESET_COMPLETE", f"deleted={deleted}")
        return {"deleted": deleted, "files": [str(f) for f in files_to_delete]}

    # =========================================================================
    # Shutdown
    # =========================================================================

    async def shutdown(self) -> None:
        """Kill any running subprocess on server shutdown."""
        if self._process is not None and self._process.returncode is None:
            logger.info("SHUTDOWN", "killing_running_process")
            await self.stop_command()

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def current_job(self) -> Optional[PipelineJobStatus]:
        return self._current_job
