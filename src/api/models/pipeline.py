"""Pydantic models for Pipeline Control API."""

from typing import Optional

from pydantic import BaseModel, Field


class PipelineProgressEvent(BaseModel):
    """A stage marker from CLI stdout."""

    stage: str = Field(description="Stage marker name (e.g., INIT_START, DOWNLOAD_COMPLETE)")
    message: str = Field(description="Human-readable progress message")
    detail: str = Field(default="", description="Additional detail from CLI output")
    timestamp: str = Field(description="ISO datetime when stage was reached")


class PipelineJobStatus(BaseModel):
    """Status of a running or completed pipeline job."""

    command: str = Field(description="CLI command being executed (init, rebuild, observe, verify, analyse)")
    args: dict = Field(default_factory=dict, description="Arguments passed to the command")
    status: str = Field(description="Job status: running, completed, failed, cancelled")
    started_at: str = Field(description="ISO datetime when job started")
    elapsed_sec: float = Field(default=0, description="Seconds elapsed since start")
    progress: list[PipelineProgressEvent] = Field(default_factory=list, description="Stage progress trail")
    exit_code: Optional[int] = Field(default=None, description="Process exit code (None if still running)")


class PipelineStatus(BaseModel):
    """Filesystem state check — what data/models exist."""

    has_model: bool = Field(description="Whether probability_surface.json exists")
    model_age_hours: Optional[float] = Field(default=None, description="Hours since model was last modified")
    has_raw_data: bool = Field(description="Whether raw candle data exists")
    observation_files: int = Field(default=0, description="Number of observation parquet files")
    observation_size_mb: float = Field(default=0, description="Total size of observation files in MB")
    current_job: Optional[PipelineJobStatus] = Field(default=None, description="Currently running job, if any")


class PipelineStartRequest(BaseModel):
    """Request body for starting a pipeline command."""

    command: str = Field(description="CLI command to run: init, rebuild, observe, verify, analyse")
    args: dict = Field(default_factory=dict, description="Command arguments (e.g., {months: 6, duration: 3600})")
